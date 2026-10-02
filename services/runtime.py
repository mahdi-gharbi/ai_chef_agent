import asyncio
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from services.errors import normalize_error
from services.kooki_service import KookiService
from services.persistence import ExecutionStore


@dataclass
class Runtime:
    service: KookiService
    provider: str
    mcp_ready: bool = True


@asynccontextmanager
async def open_api_mcp():
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain_mcp_adapters.tools import load_mcp_tools
    from conf import get_project_root
    # Filesystem MCP remains available to the single-user Streamlit app. It is
    # deliberately absent here: local_privacy is not partitioned by API identity.
    client = MultiServerMCPClient({'chef_core_service': {
        'command': sys.executable,
        'args': [str(Path(get_project_root()) / 'agent' / 'mcp_server.py')],
        'transport': 'stdio',
        'env': {k: v for k, v in os.environ.items() if k in {
            'PATH', 'SYSTEMROOT', 'TEMP', 'TMP', 'PYTHONPATH', 'SPOONACULAR_API_KEY',
        }},
    }})
    # Persistent explicit session: get_tools() alone would start a subprocess per call.
    async with client.session('chef_core_service') as session:
        tools = await load_mcp_tools(session)
        yield tools


@asynccontextmanager
async def create_runtime(*, config=None, provider_factory=None, mcp_factory=None,
                         graph_builder=None, guard_factory=None, store_path=None):
    from conf import get_agent_config, get_project_root
    from agent.models.provider import create_provider
    config = config or get_agent_config()
    try:
        provider, llm = (provider_factory or create_provider)(config)
    except Exception as exc:
        raise normalize_error(exc, stage='configuration') from None
    if graph_builder is None:
        from agent.multi_agent_graph import build_multi_agent_graph
        graph_builder = build_multi_agent_graph
    if guard_factory is None:
        from agent.guardrails import apply_input_guardrails_async, apply_output_guardrails
        async def input_guard(text):
            return await apply_input_guardrails_async(text, llm)
        guard_factory = lambda: (input_guard, apply_output_guardrails)
    factory = mcp_factory or open_api_mcp
    manager = factory()
    # Keep the persistent stdio scope in the lifespan task that owns its shutdown.
    # Startup currently has no timeout; supervisors should enforce a startup deadline.
    from contextlib import AsyncExitStack
    async with AsyncExitStack() as stack:
        try:
            tools = await stack.enter_async_context(manager)
        except Exception as exc:
            raise normalize_error(exc, stage='mcp') from None
        from services.scoped_tools import scope_tools
        all_tools = scope_tools(tools)
        # Existing RAG is shared and cloud-backed. Opt in explicitly; no embedding redesign.
        if os.environ.get('KOOKI_ENABLE_RAG', 'false').lower() == 'true':
            if not os.environ.get('DASHSCOPE_API_KEY'):
                from services.errors import KookiError
                raise KookiError('MODEL_CONFIGURATION_ERROR')
            from rag.agentic_rag_core import search_private_knowledge
            async def retrieve(**kwargs):
                try:
                    return await asyncio.to_thread(search_private_knowledge.invoke, kwargs)
                except Exception as exc:
                    raise normalize_error(exc, stage='rag') from None
            all_tools.append(search_private_knowledge.model_copy(update={'coroutine': retrieve, 'func': None}))
        graph = graph_builder(llm, all_tools)
        path = store_path or os.environ.get('KOOKI_API_DB_PATH') or str(Path(get_project_root()) / 'data' / 'kooki_api.db')
        try:
            store = await asyncio.to_thread(ExecutionStore, path)
        except Exception as exc:
            raise normalize_error(exc, stage='persistence') from None
        input_guard, output_guard = guard_factory()
        yield Runtime(KookiService(graph, store, input_guard, output_guard,
                                  provider=provider, max_history=config.get('state', {}).get('max_history_messages', 20)), provider)
