from fastapi import Request
from services.errors import KookiError


def get_service(request: Request):
    if request.app.state.service is None:
        raise request.app.state.startup_error or KookiError('MODEL_CONFIGURATION_ERROR')
    return request.app.state.service
