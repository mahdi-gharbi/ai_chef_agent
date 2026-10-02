"""API memory and retry ledger. Kept separate from legacy Streamlit sessions."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from services.errors import KookiError


class ExecutionStore:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS api_memory (user_id TEXT, session_id TEXT, history TEXT NOT NULL, PRIMARY KEY(user_id,session_id))')
            db.execute('CREATE TABLE IF NOT EXISTS api_executions (user_id TEXT, session_id TEXT, key TEXT, fingerprint TEXT NOT NULL, execution_id TEXT NOT NULL, result TEXT, PRIMARY KEY(user_id,session_id,key))')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    @staticmethod
    def fingerprint(request):
        body = {k: request[k] for k in ('message', 'metadata')}
        return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def reserve(self, request, execution_id):
        key = request.get('idempotency_key')
        if key is None:
            return None
        identity = (request['user_id'], request['session_id'], key)
        fingerprint = self.fingerprint(request)
        with closing(self.connect()) as db, db:
            # SQLite uniqueness arbitrates even across processes/restarts.
            db.execute('INSERT OR IGNORE INTO api_executions VALUES (?,?,?,?,?,NULL)', (*identity, fingerprint, execution_id))
            row = db.execute('SELECT fingerprint,execution_id,result FROM api_executions WHERE user_id=? AND session_id=? AND key=?', identity).fetchone()
            if row[0] != fingerprint:
                raise KookiError('IDEMPOTENCY_CONFLICT', execution_id)
            if row[1] != execution_id and row[2] is None:
                raise KookiError('IDEMPOTENCY_IN_PROGRESS', row[1])
            return json.loads(row[2]) if row[2] else None

    def load_history(self, user_id, session_id):
        with closing(self.connect()) as db:
            row = db.execute('SELECT history FROM api_memory WHERE user_id=? AND session_id=?', (user_id, session_id)).fetchone()
            return json.loads(row[0]) if row else []

    def finish(self, request, result, history=None):
        # Memory and successful replay response commit in the same transaction.
        with closing(self.connect()) as db, db:
            if history is not None:
                db.execute('INSERT OR REPLACE INTO api_memory VALUES (?,?,?)', (request['user_id'],request['session_id'],json.dumps(history,ensure_ascii=False)))
            if request.get('idempotency_key') is not None:
                db.execute('UPDATE api_executions SET result=? WHERE user_id=? AND session_id=? AND key=?', (json.dumps(result,ensure_ascii=False),request['user_id'],request['session_id'],request['idempotency_key']))

    def release(self, request):
        # Only called before graph execution: no tools/side effects have run.
        if request.get('idempotency_key') is not None:
            with closing(self.connect()) as db, db:
                db.execute('DELETE FROM api_executions WHERE user_id=? AND session_id=? AND key=?', (request['user_id'],request['session_id'],request['idempotency_key']))
