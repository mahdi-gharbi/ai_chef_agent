"""Real LangGraph/LangChain smoke tests with a local fake model, no provider calls.

Skipped explicitly when the existing AI dependency stack is unavailable.
"""
import asyncio
import pytest

pytest.importorskip('langchain')
pytest.importorskip('langgraph')
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool, ToolException
from agent.multi_agent_graph import build_multi_agent_graph
from services.execution_context import ExecutionContext, current_execution
from services.scoped_tools import scope_tools


class LocalFakeModel(BaseChatModel):
    replies: list[str]

    @property
    def _llm_type(self):
        return 'local-test'

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.replies.pop(0)))])


@pytest.mark.parametrize('intent', ['recipe', 'health', 'fridge', 'general'])
def test_real_graph_routes_once_and_preserves_four_nodes(intent):
    model = LocalFakeModel(replies=[intent, 'Dinner is ready.'])
    graph = build_multi_agent_graph(model, [])
    assert {'recipe', 'health', 'fridge', 'general'}.issubset(graph.get_graph().nodes)
    async def run():
        token = current_execution.set(ExecutionContext('alice', 'chat1', 'exec-test'))
        try:
            return await graph.ainvoke({'messages':[{'role':'user','content':'Dinner please'}],
                                       'intent':'', 'user_id':'alice','session_id':'chat1','metadata':{}})
        finally:
            current_execution.reset(token)
    result = asyncio.run(run())
    assert result['intent'] == intent
    assert result['messages'][-1].content == 'Dinner is ready.'
    assert model.replies == []


def test_real_structured_tool_enforces_trusted_user():
    calls = []
    async def inventory(user_id: str):
        calls.append(user_id)
        return 'empty', {'source':'local-test'}
    tool = StructuredTool.from_function(coroutine=inventory, name='get_fridge_inventory',
                                       description='Inventory', response_format='content_and_artifact')
    wrapped = scope_tools([tool])[0]
    async def run():
        token = current_execution.set(ExecutionContext('alice','chat1','exec-test'))
        try:
            assert await wrapped.ainvoke({'user_id':'forged'}) == 'empty'
        finally:
            current_execution.reset(token)
    asyncio.run(run())
    assert calls == ['alice']


def test_mcp_style_tool_failure_cannot_become_raw_model_content():
    from services.errors import KookiError
    async def fail(user_id: str):
        raise ToolException('private provider detail')
    tool = StructuredTool.from_function(coroutine=fail, name='get_fridge_inventory',
                                       description='Inventory', handle_tool_error=True)
    wrapped = scope_tools([tool])[0]
    async def run():
        token = current_execution.set(ExecutionContext('alice','chat1','exec-test'))
        try:
            with pytest.raises(KookiError) as caught:
                await wrapped.ainvoke({'user_id':'alice'})
            assert caught.value.error_type == 'TOOL_EXECUTION_ERROR'
            assert 'private provider detail' not in str(caught.value)
        finally:
            current_execution.reset(token)
    asyncio.run(run())
