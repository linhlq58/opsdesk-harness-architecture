"""Request and response bodies of the HTTP API (M04 §8). Pydantic at the boundary."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

MAX_MESSAGE_CHARS = 4000


class _Body(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PersonaOut(_Body):
    id: str
    tenant_id: str
    name: str
    department: str
    roles: list[str]


class SessionIn(_Body):
    employee_id: str


class SessionOut(_Body):
    token: str
    expires_at: datetime


class ThreadOut(_Body):
    thread_id: str


class ChatIn(_Body):
    # The thread must come from POST /api/threads; ownership is checked (D5).
    thread_id: str
    # Whitespace-only counts as empty (H5).
    message: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_CHARS)
    ]
