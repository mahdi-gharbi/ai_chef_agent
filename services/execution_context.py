from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionContext:
    user_id: str
    session_id: str
    execution_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    intent: str | None = None
    warning_mode: bool = False
    tools_used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


current_execution: ContextVar[ExecutionContext | None] = ContextVar('kooki_execution', default=None)
