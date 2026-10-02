from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from api.dependencies import get_service
from api.schemas import ChatRequest, SuccessResponse, ErrorResponse

router = APIRouter(prefix='/api')


@router.get('/health')
async def health(request: Request):
    ready = request.app.state.service is not None
    return JSONResponse(status_code=200 if ready else 503, content={
        'status': 'ok' if ready else 'degraded', 'service': 'kooki-api',
        'agent_graph_ready': ready, 'mcp_ready': request.app.state.mcp_ready,
        'provider': request.app.state.provider,
    })


@router.post('/chat', response_model=SuccessResponse,
             responses={400: {'model': ErrorResponse}, 409: {'model': ErrorResponse},
                        422: {'model': ErrorResponse}, 429: {'model': ErrorResponse},
                        500: {'model': ErrorResponse}, 502: {'model': ErrorResponse},
                        503: {'model': ErrorResponse}})
async def chat(payload: ChatRequest, service=Depends(get_service)):
    return await service.chat(payload)
