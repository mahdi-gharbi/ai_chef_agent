"""Request-scoped middleware shared by the API and legacy Streamlit graph."""
import time
from langchain.agents import AgentState
from langchain.agents.middleware import before_model, wrap_tool_call, dynamic_prompt
from langgraph.runtime import Runtime
from conf import get_prompt_config
from utils.logger_handler import get_logger
from services.execution_context import current_execution

logger = get_logger("ai_chef.middleware")
_WARNING_TOOLS = {"check_fridge_warnings", "check_allergen_safety"}
_SIGNALS = ("[EXPIRED]", "[EXPIRING SOON]", "[SAFETY ALERT]")


@wrap_tool_call
async def monitor_tool(request, handler):
    tool_name = request.tool_call["name"]
    context = current_execution.get()
    start = time.perf_counter()
    if context is not None:
        context.tools_used.append(tool_name)
    try:
        result = await handler(request)
        if context is not None and tool_name in _WARNING_TOOLS:
            content = str(result.content if hasattr(result, "content") else result)
            for signal in _SIGNALS:
                if signal in content:
                    context.warning_mode = True
                    context.warnings.append(signal)
        logger.info("Tool completed name=%s elapsed_ms=%d", tool_name, (time.perf_counter()-start)*1000)
        return result
    except Exception as exc:
        # No tool arguments, user content, return previews, or raw provider errors.
        logger.error("Tool failed name=%s exception_type=%s", tool_name, type(exc).__name__)
        from services.errors import normalize_error
        raise normalize_error(exc, stage="tool") from None


@before_model
async def log_before_model(state: AgentState, runtime: Runtime) -> None:
    logger.info("Model call context_messages=%d", len(state["messages"]))


@dynamic_prompt
async def chef_dynamic_prompt(request):
    prompts = get_prompt_config()
    context = current_execution.get()
    if context is not None and context.intent:
        from agent.router import get_specialized_prompt
        base = get_specialized_prompt(context.intent)
    else:
        base = prompts.get("chef_system_prompt", "You are a professional AI chef assistant.")
    warning = context.warning_mode if context is not None else False
    if context is None:
        # Legacy single-agent CLI has no ExecutionContext. Derive alerts from
        # tool messages after the most recent human turn, without global state.
        for message in reversed(request.state.get('messages', [])):
            if getattr(message, 'type', None) == 'human':
                break
            if getattr(message, 'type', None) == 'tool' and any(signal in str(message.content) for signal in _SIGNALS):
                warning = True
    # Identity lives in the system prompt as well as in trusted tool wrappers.
    # Return the specialization explicitly: middleware used to override it with the general persona.
    if context is not None and context.execution_id != "legacy":
        base += (
            "\nTrusted user_id=" + context.user_id + ", session_id=" + context.session_id +
            ". Use this user_id for fridge/allergen tools. Ordering and private filesystem access are unavailable."
        )
    if warning:
        base += "\n\n" + prompts.get("chef_warning_prompt_addition", "Focus on ingredient risks and safety advice.")
    return base


all_middleware = [monitor_tool, log_before_model, chef_dynamic_prompt]
