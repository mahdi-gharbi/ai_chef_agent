import json
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, field_validator

Identifier = Annotated[str, StringConstraints(strict=True, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$')]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    user_id: Identifier
    session_id: Identifier
    message: str = Field(min_length=1, max_length=8000)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    idempotency_key: Identifier | None = None

    @field_validator('message')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Message is empty')
        return value.strip()

    @field_validator('metadata')
    @classmethod
    def metadata_size(cls, value):
        if len(json.dumps(value, allow_nan=False).encode()) > 4096:
            raise ValueError('Metadata exceeds 4096 bytes')
        return value


class SuccessResponse(BaseModel):
    status: Literal['success'] = 'success'
    execution_id: str
    intent: str | None = None
    selected_agent: str | None = None
    response: str
    tools_used: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    rag_sources: list[str] = Field(default_factory=list)
    execution_time_ms: int


class ErrorResponse(BaseModel):
    status: Literal['error'] = 'error'
    execution_id: str | None
    error_type: str
    message: str
    retryable: bool
