import sqlite3

ERRORS = {
    'VALIDATION_ERROR': (422, False, 'The request is invalid.'),
    'MODEL_TEMPORARILY_UNAVAILABLE': (503, True, 'The configured model provider is temporarily unavailable.'),
    'MODEL_RATE_LIMITED': (429, True, 'The configured model provider is rate limited.'),
    'MODEL_CONFIGURATION_ERROR': (503, False, 'The configured model provider is not ready.'),
    'MCP_UNAVAILABLE': (503, True, 'Agent tools are temporarily unavailable.'),
    'TOOL_EXECUTION_ERROR': (502, False, 'An agent tool could not complete.'),
    'RAG_UNAVAILABLE': (503, True, 'Knowledge retrieval is temporarily unavailable.'),
    'DATABASE_ERROR': (503, False, 'Application persistence is unavailable.'),
    'INTERNAL_ERROR': (500, False, 'The request could not be completed.'),
    'SAFETY_BLOCKED': (400, False, 'The request was blocked by input safety checks.'),
    'IDEMPOTENCY_CONFLICT': (409, False, 'This key was already used for a different request.'),
    'IDEMPOTENCY_IN_PROGRESS': (409, False, 'This execution is pending or requires review; do not repeat its side effects.'),
}


class KookiError(Exception):
    def __init__(self, error_type='INTERNAL_ERROR', execution_id=None, retryable=None):
        self.error_type = error_type
        self.http_status, default_retry, self.public_message = ERRORS[error_type]
        self.retryable = default_retry if retryable is None else retryable
        self.execution_id = execution_id
        super().__init__(error_type)

    def payload(self):
        return {'status': 'error', 'execution_id': self.execution_id,
                'error_type': self.error_type, 'message': self.public_message,
                'retryable': self.retryable}


def normalize_error(exc, *, stage='model', execution_id=None):
    if isinstance(exc, KookiError):
        exc.execution_id = execution_id or exc.execution_id
        return exc
    status = getattr(exc, 'status_code', None)
    status = status or getattr(getattr(exc, 'response', None), 'status_code', None)
    if isinstance(exc, (sqlite3.Error, OSError)) and stage == 'persistence':
        kind = 'DATABASE_ERROR'
    elif stage == 'mcp':
        kind = 'MCP_UNAVAILABLE'
    elif stage == 'rag':
        kind = 'RAG_UNAVAILABLE'
    elif stage == 'tool':
        kind = 'TOOL_EXECUTION_ERROR'
    elif status == 429:
        kind = 'MODEL_RATE_LIMITED'
    elif status in (401, 403) or stage == 'configuration':
        kind = 'MODEL_CONFIGURATION_ERROR'
    elif isinstance(exc, (TimeoutError, ConnectionError)) or status and status >= 500:
        kind = 'MODEL_TEMPORARILY_UNAVAILABLE'
    else:
        kind = 'INTERNAL_ERROR'
    return KookiError(kind, execution_id)
