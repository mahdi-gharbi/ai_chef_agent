import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from api.routes import router
from services.errors import KookiError, normalize_error
from utils.logger_handler import get_logger

logger = get_logger('ai_chef.api')


def create_app(runtime_factory=None):
    if runtime_factory is None:
        from services.runtime import create_runtime
        runtime_factory = create_runtime

    @asynccontextmanager
    async def lifespan(app):
        app.state.service = None
        app.state.mcp_ready = False
        app.state.provider = None
        app.state.startup_error = None
        # Enter and exit in the same lifespan task: MCP/AnyIO cancel scopes require this.
        async with asynccontextmanager(_runtime_or_error)(app, runtime_factory):
            yield

    app = FastAPI(title='Kooki API', version='1.0.0', lifespan=lifespan)
    app.include_router(router)

    @app.exception_handler(KookiError)
    async def domain_error(request: Request, exc):
        exc.execution_id = exc.execution_id or 'exec-' + uuid.uuid4().hex
        return JSONResponse(status_code=exc.http_status, content=exc.payload())

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc):
        # Pydantic's raw error includes input values; deliberately do not return or log it.
        error = KookiError('VALIDATION_ERROR', 'exec-' + uuid.uuid4().hex)
        return JSONResponse(status_code=422, content=error.payload())

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc):
        error = normalize_error(exc, execution_id='exec-' + uuid.uuid4().hex)
        logger.error('Unexpected API error execution_id=%s exception_type=%s', error.execution_id, type(exc).__name__)
        return JSONResponse(status_code=error.http_status, content=error.payload())

    return app


async def _runtime_or_error(app, factory):
    from contextlib import AsyncExitStack
    async with AsyncExitStack() as stack:
        try:
            runtime = await stack.enter_async_context(factory())
            app.state.service = runtime.service
            app.state.mcp_ready = runtime.mcp_ready
            app.state.provider = runtime.provider
        except Exception as exc:
            app.state.startup_error = normalize_error(exc, stage='configuration')
            logger.error('API runtime startup failed exception_type=%s error_type=%s', type(exc).__name__, app.state.startup_error.error_type)
        yield
        app.state.service = None
        app.state.mcp_ready = False


app = create_app()
