"""``GET /api/personas`` and ``POST /api/session``: the demo login (M04 §8).

Not authentication: anyone may become any seed persona. It shows *where* identity
enters: the token issued here is the only thing later requests can use to say who
they are.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from opsdesk.api.schemas import PersonaOut, SessionIn, SessionOut
from opsdesk.api.state import AppState, app_state

router = APIRouter(prefix="/api", tags=["session"])


@router.get("/personas")
async def personas(state: Annotated[AppState, Depends(app_state)]) -> list[PersonaOut]:
    return [
        PersonaOut(
            id=e.id,
            tenant_id=e.tenant_id,
            name=e.full_name,
            department=e.department.value,
            roles=sorted(role.value for role in e.roles),
        )
        for e in state.personas
    ]


@router.post("/session")
async def create_session(
    body: SessionIn, state: Annotated[AppState, Depends(app_state)]
) -> SessionOut:
    matches = [e for e in state.personas if e.id == body.employee_id]
    if len(matches) != 1:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="persona not found")
    session = state.tokens.issue(matches[0])
    return SessionOut(token=session.token, expires_at=session.expires_at)
