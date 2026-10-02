import asyncio
import time
import uuid
from pydantic import ValidationError

from services.contracts import ChatRequest, SuccessResponse
from services.errors import KookiError, normalize_error
from services.execution_context import ExecutionContext, current_execution
from utils.logger_handler import get_logger

logger = get_logger('ai_chef.service')
AGENTS = {'recipe': 'Recipe Expert', 'health': 'Health & Nutrition Advisor',
          'fridge': 'Fridge Manager', 'general': 'General Chef Assistant'}


def text_content(message):
    content = message.get('content', '') if isinstance(message, dict) else message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(block if isinstance(block, str) else block.get('text', '')
                       for block in content if isinstance(block, (str, dict)))
    return ''


def last_answer(messages):
    for msg in reversed(messages):
        role = msg.get('role', msg.get('type')) if isinstance(msg, dict) else getattr(msg, 'type', None)
        calls = msg.get('tool_calls') if isinstance(msg, dict) else getattr(msg, 'tool_calls', None)
        if role in {'ai', 'assistant'} and not calls and text_content(msg):
            return text_content(msg)
    raise KookiError('INTERNAL_ERROR')


class KookiService:
    def __init__(self, graph, store, input_guard, output_guard, *, provider, max_history=20):
        self.graph, self.store = graph, store
        self.input_guard, self.output_guard = input_guard, output_guard
        self.provider = provider
        self.max_history = max_history
        # Phase 1: one execution at a time per service, protecting sessions and stdio tools.
        self._lock = asyncio.Lock()

    async def chat(self, request):
        execution_id = 'exec-' + uuid.uuid4().hex
        try:
            request = ChatRequest.model_validate(request).model_dump()
        except ValidationError:
            raise KookiError('VALIDATION_ERROR', execution_id) from None
        async with self._lock:
            return await self._execute(request, execution_id)

    async def _execute(self, request, execution_id):
        started = time.perf_counter()
        context = ExecutionContext(request['user_id'], request['session_id'], execution_id,
                                   request['metadata'], request['idempotency_key'])
        token = current_execution.set(context)
        stage, graph_started, reserved = 'persistence', False, False
        logger.info('Execution started execution_id=%s keyed=%s', execution_id, context.idempotency_key is not None)
        try:
            replay = await asyncio.to_thread(self.store.reserve, request, execution_id)
            if replay is not None:
                if replay['status'] == 'error':
                    raise KookiError(replay['error_type'], replay['execution_id'], replay['retryable'])
                return replay
            reserved = True
            history = await asyncio.to_thread(self.store.load_history, context.user_id, context.session_id)
            stage = 'model'
            safe, sanitized, _ = await self.input_guard(request['message'])
            if not safe:
                raise KookiError('SAFETY_BLOCKED')
            state = {'messages': history + [{'role': 'user', 'content': sanitized}],
                     'intent': '', 'user_id': context.user_id, 'session_id': context.session_id,
                     'metadata': context.metadata}
            graph_started = True
            result = await self.graph.ainvoke(state)
            response = self.output_guard(last_answer(result.get('messages', [])))
            intent = result.get('intent')
            payload = SuccessResponse(
                execution_id=execution_id, intent=intent if intent in AGENTS else None,
                selected_agent=AGENTS.get(intent), response=response,
                tools_used=list(dict.fromkeys(context.tools_used)),
                warnings=list(dict.fromkeys(self.output_guard(w) for w in context.warnings)),
                rag_sources=[], execution_time_ms=int((time.perf_counter()-started)*1000)
            ).model_dump()
            # Never persist raw output, intermediate tool content, or unsanitized user input.
            history = (history + [{'role': 'user', 'content': sanitized},
                                  {'role': 'assistant', 'content': response}])[-self.max_history:]
            stage = 'persistence'
            await asyncio.to_thread(self.store.finish, request, payload, history)
            return payload
        except Exception as exc:
            if not reserved and isinstance(exc, KookiError):
                raise
            error = normalize_error(exc, stage=stage, execution_id=execution_id)
            # A failure after graph entry is ambiguous: tools may already have executed.
            # Cache it and prohibit an automatic re-execution, even for model errors.
            if graph_started:
                error.retryable = False
            logger.error('Execution failed execution_id=%s stage=%s exception_type=%s error_type=%s',
                         execution_id, stage, type(exc).__name__, error.error_type)
            if reserved:
                try:
                    if graph_started or not error.retryable:
                        await asyncio.to_thread(self.store.finish, request, error.payload())
                    else:
                        await asyncio.to_thread(self.store.release, request)
                except Exception:
                    # A pending reservation deliberately remains blocked after persistence failure.
                    logger.error('Retry ledger persistence failed execution_id=%s', execution_id)
            raise error from None
        finally:
            current_execution.reset(token)
