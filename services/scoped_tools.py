"""Bind MCP tool identities on the trusted application side, never from LLM arguments."""
from services.errors import KookiError, normalize_error
from services.execution_context import current_execution

API_TOOLS = {'get_fridge_inventory', 'add_food_to_fridge', 'check_fridge_warnings',
             'check_allergen_safety', 'remove_food_from_fridge', 'clear_fridge_inventory',
             'get_nutrition_info', 'get_local_weather'}
USER_TOOLS = API_TOOLS - {'get_nutrition_info', 'get_local_weather'}
WRITE_TOOLS = {'add_food_to_fridge', 'remove_food_from_fridge', 'clear_fridge_inventory'}


async def invoke_scoped(tool, kwargs):
    context = current_execution.get()
    if context is None:
        raise KookiError('TOOL_EXECUTION_ERROR')
    if tool.name in WRITE_TOOLS and not context.idempotency_key:
        raise KookiError('VALIDATION_ERROR')
    values = dict(kwargs)
    if tool.name in USER_TOOLS:
        values['user_id'] = context.user_id
    try:
        result = await tool.ainvoke(values)
        if getattr(result, 'status', None) == 'error':
            raise KookiError('TOOL_EXECUTION_ERROR')
        return result
    except Exception as exc:
        raise normalize_error(exc, stage='tool', execution_id=context.execution_id) from None


def scope_tools(tools):
    result = []
    for original in tools:
        if original.name not in API_TOOLS:
            continue
        # MCP adapter versions may convert failures to model-visible content.
        # Force them to propagate so our public error contract can redact them.
        raw = original.model_copy(update={'handle_tool_error': False, 'handle_validation_error': False})
        async def call(_tool=raw, **kwargs):
            return await invoke_scoped(_tool, kwargs)
        # The MCP adapter returns StructuredTool instances. Preserve schemas/descriptions.
        # original.ainvoke(dict) already unwraps the adapter's content/artifact pair.
        # This wrapper therefore returns content only, even for MCP adapter tools.
        result.append(original.model_copy(update={'coroutine': call, 'func': None, 'response_format': 'content',
                                                'handle_tool_error': False, 'handle_validation_error': False}))
    return result
