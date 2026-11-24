"""FastAPI dependencies shared by routes: who is calling (Bearer token → Principal).

Identity enters here and only here: from the verified token, through the current
employee record and ``principal_for`` (``api.auth``). Never from the request body.
Any problem with the token is the same ``401``: the response never says which check
failed.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from opsdesk.api.auth import InvalidSession, principal_from_token
from opsdesk.api.state import AppState, app_state
from opsdesk.security.principal import Principal

# auto_error=False: a missing header gets our own 401 (FastAPI's default is 403).
_bearer = HTTPBearer(auto_error=False)

UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="invalid or expired session",
    headers={"WWW-Authenticate": "Bearer"},
)


async def current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    state: Annotated[AppState, Depends(app_state)],
) -> Principal:
    if credentials is None:
        raise UNAUTHORIZED
    try:
        return await principal_from_token(
            credentials.credentials, tokens=state.tokens, employees=state.repos.employees
        )
    except InvalidSession:
        raise UNAUTHORIZED from None
