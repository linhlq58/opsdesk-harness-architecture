"""``POST /api/threads``: the server creates a thread for the caller (M04 §8, D5)."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from opsdesk.api.deps import current_principal
from opsdesk.api.schemas import ThreadOut
from opsdesk.api.state import AppState, app_state
from opsdesk.security.principal import Principal

router = APIRouter(prefix="/api", tags=["threads"])


@router.post("/threads", status_code=status.HTTP_201_CREATED)
async def create_thread(
    principal: Annotated[Principal, Depends(current_principal)],
    state: Annotated[AppState, Depends(app_state)],
) -> ThreadOut:
    return ThreadOut(thread_id=state.threads.create(principal))
