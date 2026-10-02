import asyncio
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from api.app import create_app
from agent.guardrails import apply_output_guardrails, redact_pii
from services.errors import KookiError
from services.execution_context import current_execution
from services.kooki_service import KookiService
from services.persistence import ExecutionStore
from services.runtime import Runtime, create_runtime
from services.scoped_tools import invoke_scoped, scope_tools
from agent.models.provider import provider_name, create_provider
from utils.logger_handler import RedactingFormatter


class FakeGraph:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.content = [{'type': 'text', 'text': 'Dinner: pasta. Contact cook@example.com'}]

    async def ainvoke(self, state):
        self.calls.append((state, current_execution.get()))
        if self.failure:
            raise self.failure
        current_execution.get().tools_used.append('get_fridge_inventory')
        return {'intent': 'recipe', 'messages': state['messages'] + [{'role': 'assistant', 'content': self.content}]}


async def safe_guard(text):
    return True, redact_pii(text), ''


@pytest.fixture
def bundle(tmp_path):
    graph = FakeGraph()
    service = KookiService(graph, ExecutionStore(tmp_path/'api.db'), safe_guard, apply_output_guardrails, provider='gemini')
    events = []
    @asynccontextmanager
    async def runtime():
        events.append('start')
        try:
            yield Runtime(service, 'gemini')
        finally:
            events.append('stop')
    app = create_app(runtime)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, graph, service, events
    assert events == ['start', 'stop']


def payload(**kwargs):
    return dict(user_id='alice', session_id='chat1', message='Dinner please', metadata={'city':'Tunis','channel':'n8n'}, **kwargs)


def test_health_and_reused_service(bundle):
    client, graph, _, events = bundle
    assert client.get('/api/health').json() == {'status':'ok','service':'kooki-api','agent_graph_ready':True,'mcp_ready':True,'provider':'gemini'}
    client.post('/api/chat',json=payload())
    client.post('/api/chat',json=payload())
    assert len(graph.calls) == 2
    assert events == ['start']


@pytest.mark.parametrize('field,value', [('message',' '),('message','x'*8001),('user_id','../bob'),('session_id','../bad'),('session_id',1),('metadata',[]),('metadata',{'blob':'x'*4097}),('idempotency_key','invalid/key')])
def test_validation(field,value,bundle):
    client,graph,_,_ = bundle
    request=payload(); request[field]=value
    response=client.post('/api/chat',json=request)
    assert response.status_code == 422
    assert response.json()['error_type'] == 'VALIDATION_ERROR'
    assert response.json()['retryable'] is False
    assert graph.calls == []
    assert 'input' not in response.text


def test_success_context_redaction_and_memory_isolation(bundle):
    client, graph, service, _ = bundle
    request=payload(); request['message']='Contact alice@example.com'
    response=client.post('/api/chat',json=request)
    result=response.json()
    assert response.status_code == 200
    assert set(result) == {'status','execution_id','intent','selected_agent','response','tools_used','warnings','rag_sources','execution_time_ms'}
    assert result['selected_agent'] == 'Recipe Expert'
    assert result['rag_sources'] == []
    assert 'cook@example.com' not in result['response']
    state,context=graph.calls[0]
    assert state['intent'] == ''  # classify only inside LangGraph, no API preclassification
    assert state['user_id'] == context.user_id == 'alice'
    assert state['session_id'] == context.session_id == 'chat1'
    assert state['metadata']['city'] == 'Tunis'
    assert 'alice@example.com' not in state['messages'][-1]['content']
    client.post('/api/chat',json=payload())
    assert len(graph.calls[1][0]['messages']) == 3
    other=payload(); other['user_id']='bob'
    client.post('/api/chat',json=other)
    assert len(graph.calls[2][0]['messages']) == 1
    assert 'cook@example.com' not in str(service.store.load_history('alice','chat1'))


def test_model_failure_is_structured_and_never_reexecutes(bundle):
    client,graph,_,_=bundle
    graph.failure=TimeoutError('credential=do-not-expose')
    first=client.post('/api/chat',json=payload(idempotency_key='retry1'))
    second=client.post('/api/chat',json=payload(idempotency_key='retry1'))
    assert first.status_code == second.status_code == 503
    assert first.json() == second.json()
    assert first.json()['error_type'] == 'MODEL_TEMPORARILY_UNAVAILABLE'
    assert first.json()['retryable'] is False  # graph may have already mutated state
    assert 'do-not-expose' not in first.text
    assert len(graph.calls) == 1


def test_guard_blocks_graph(bundle):
    client,graph,service,_=bundle
    async def block(text): return False,'','blocked'
    service.input_guard=block
    response=client.post('/api/chat',json=payload())
    assert response.status_code == 400
    assert response.json()['error_type'] == 'SAFETY_BLOCKED'
    assert not graph.calls


def test_judge_failure_is_retryable_before_graph(bundle):
    client,graph,service,_=bundle
    async def fail(text): raise TimeoutError('private')
    service.input_guard=fail
    first=client.post('/api/chat',json=payload(idempotency_key='key'))
    assert first.status_code == 503 and first.json()['retryable']
    service.input_guard=safe_guard
    assert client.post('/api/chat',json=payload(idempotency_key='key')).status_code == 200
    assert len(graph.calls)==1


def test_idempotency_replay_and_conflict(bundle):
    client,graph,_,_=bundle
    request=payload(idempotency_key='key')
    first=client.post('/api/chat',json=request).json()
    assert client.post('/api/chat',json=request).json()==first
    request['message']='Different request'
    conflict=client.post('/api/chat',json=request)
    assert conflict.status_code==409
    assert conflict.json()['error_type']=='IDEMPOTENCY_CONFLICT'
    assert len(graph.calls)==1


def test_crash_reservation_and_restart(tmp_path):
    path=tmp_path/'db.sqlite'; store=ExecutionStore(path)
    request=payload(idempotency_key='key')
    assert store.reserve(request,'original') is None
    with pytest.raises(KookiError,match='IDEMPOTENCY_IN_PROGRESS'):
        ExecutionStore(path).reserve(request,'restart')


def test_same_session_concurrent_calls_are_serialized(tmp_path):
    graph=FakeGraph(); service=KookiService(graph,ExecutionStore(tmp_path/'db'),safe_guard,apply_output_guardrails,provider='ollama')
    async def run():
        results=await asyncio.gather(service.chat(payload(idempotency_key='key')), service.chat(payload(idempotency_key='key')))
        assert results[0]==results[1]
        assert current_execution.get() is None
    asyncio.run(run())
    assert len(graph.calls)==1


def test_scoped_tools_override_forged_identity_and_require_key():
    calls=[]
    async def invoke(values): calls.append(values); return 'ok'
    tool=SimpleNamespace(name='add_food_to_fridge',ainvoke=invoke)
    from services.execution_context import ExecutionContext
    async def run():
        token=current_execution.set(ExecutionContext('alice','session','exec',idempotency_key='key'))
        try:
            await invoke_scoped(tool,{'user_id':'bob','item_name':'egg'})
            current_execution.get().idempotency_key=None
            with pytest.raises(KookiError): await invoke_scoped(tool,{'user_id':'bob'})
        finally: current_execution.reset(token)
    asyncio.run(run())
    assert calls==[{'user_id':'alice','item_name':'egg'}]


def test_order_and_private_files_are_not_exposed():
    tools=[SimpleNamespace(name=n) for n in ('order_fresh_groceries','read_file','write_file','search_files')]
    assert scope_tools(tools)==[]


@pytest.mark.parametrize('provider', ['gemini','qwen','ollama'])
def test_provider_selection(provider,monkeypatch):
    monkeypatch.setenv('KOOKI_PROVIDER',provider)
    assert provider_name({})==provider


def test_provider_priority_and_configuration(monkeypatch):
    monkeypatch.delenv('KOOKI_PROVIDER',raising=False)
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    assert provider_name({'lora':{'use_lora_adapter':True},'gemini':{'use_gemini':True}})=='ollama'
    with pytest.raises(KookiError,match='MODEL_CONFIGURATION_ERROR'):
        create_provider({'gemini':{'use_gemini':True}})
    monkeypatch.setenv('KOOKI_PROVIDER','openai')
    with pytest.raises(KookiError): provider_name({})


def test_lifespan_build_once_and_cleanup(tmp_path,monkeypatch):
    monkeypatch.setenv('KOOKI_ENABLE_RAG','false')
    events=[]
    @asynccontextmanager
    async def mcp():
        events.append('mcp-start')
        try: yield []
        finally: events.append('mcp-stop')
    def build(llm,tools): events.append('build'); return FakeGraph()
    def factory():
        return create_runtime(config={'state':{'max_history_messages':20}}, provider_factory=lambda c:('gemini',object()),mcp_factory=mcp,graph_builder=build,guard_factory=lambda:(safe_guard,apply_output_guardrails),store_path=tmp_path/'db')
    with TestClient(create_app(factory)) as client:
        assert client.get('/api/health').status_code==200
        client.post('/api/chat',json=payload())
        client.post('/api/chat',json=payload())
        assert events==['mcp-start','build']
    assert events==['mcp-start','build','mcp-stop']


def test_mcp_failure_health_degraded(tmp_path):
    @asynccontextmanager
    async def mcp():
        raise ConnectionError('secret connection detail')
        yield
    def factory():
        return create_runtime(config={'state':{}},provider_factory=lambda c:('gemini',object()),mcp_factory=mcp,graph_builder=lambda *a:None,guard_factory=lambda:(safe_guard,apply_output_guardrails),store_path=tmp_path/'db')
    with TestClient(create_app(factory)) as client:
        assert client.get('/api/health').status_code==503
        response=client.post('/api/chat',json=payload())
        assert response.json()['error_type']=='MCP_UNAVAILABLE'
        assert 'secret connection detail' not in response.text


def test_log_redacts_credentials(monkeypatch):
    monkeypatch.setenv('SPOONACULAR_API_KEY','temporary-test-placeholder')
    formatter=RedactingFormatter('%(message)s')
    record=logging.LogRecord('test',40,'',0,'error url?apiKey=temporary-test-placeholder token=unrelated-placeholder',(),None)
    result=formatter.format(record)
    assert 'temporary-test-placeholder' not in result
    assert 'unrelated-placeholder' not in result
