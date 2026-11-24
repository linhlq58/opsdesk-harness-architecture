"""Demo session tokens: where identity enters the server (M04).

This is **not** an authentication system (M04 §0: "Real authentication: never in this
project"). The persona picker lets anyone become any seed employee. What it shows is
*where* identity comes from, so every later layer can trust it:

    POST /api/session {employee_id}  →  signed token  (issue)
    Authorization: Bearer <token>    →  (tenant_id, employee_id)  (verify)
                                     →  EmployeeRepository.get  →  principal_for
                                     →  Principal in RequestContext

Rules this module enforces:

* The token carries **only ids** (``tid`` = tenant, ``sub`` = employee) and times
  (``iat``, ``exp``). Roles and scopes are *not* in the token: they are derived on
  every request from the current employee record through ``principal_for``, so a
  role change takes effect immediately and a token can never grant extra scopes.
* HS256 only, stated explicitly on decode (no algorithm chosen by the token header).
* Expiry is checked against the injected ``Clock`` (not PyJWT's own clock), so tests
  can move time.
* Every failure (bad signature, malformed, expired, unknown employee) raises the same
  ``InvalidSession``; the API answers ``401`` without saying which check failed.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from opsdesk.core.clock import Clock
from opsdesk.domain.ids import EmployeeId, TenantId
from opsdesk.domain.models import Employee
from opsdesk.domain.ports import EmployeeRepository
from opsdesk.security.principal import Principal, principal_for

ALGORITHM = "HS256"
_REQUIRED_CLAIMS = ("sub", "tid", "iat", "exp")


class InvalidSession(Exception):
    """The token is missing, malformed, badly signed, expired, or names nobody."""


@dataclass(frozen=True, slots=True)
class SessionToken:
    token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class SessionClaims:
    tenant_id: TenantId
    employee_id: EmployeeId


class SessionTokens:
    """Issue and verify signed session tokens. Built once at startup."""

    def __init__(self, *, secret: str, ttl: timedelta, clock: Clock) -> None:
        if ttl <= timedelta(0):
            raise ValueError("session ttl must be positive")
        self._secret = secret
        self._ttl = ttl
        self._clock = clock

    def issue(self, employee: Employee) -> SessionToken:
        now = self._clock.now()
        exp = int((now + self._ttl).timestamp())
        claims: dict[str, Any] = {
            "sub": str(employee.id),
            "tid": str(employee.tenant_id),
            "iat": int(now.timestamp()),
            "exp": exp,
        }
        # PyJWT's key type mentions optional ``cryptography`` classes pyright cannot see.
        token = jwt.encode(claims, self._secret, algorithm=ALGORITHM)  # pyright: ignore[reportUnknownMemberType]
        # Report the expiry the token actually carries (whole seconds).
        return SessionToken(token=token, expires_at=datetime.fromtimestamp(exp, UTC))

    def verify(self, token: str) -> SessionClaims:
        try:
            claims: dict[str, Any] = jwt.decode(  # pyright: ignore[reportUnknownMemberType]
                token,
                self._secret,
                algorithms=[ALGORITHM],
                # Expiry is checked below against our Clock, not PyJWT's.
                options={"verify_exp": False, "require": list(_REQUIRED_CLAIMS)},
            )
        except jwt.PyJWTError as exc:
            raise InvalidSession("invalid session token") from exc

        exp, sub, tid = claims["exp"], claims["sub"], claims["tid"]
        if not isinstance(exp, int) or not isinstance(sub, str) or not isinstance(tid, str):
            raise InvalidSession("invalid session token")
        if self._clock.now() >= datetime.fromtimestamp(exp, UTC):
            raise InvalidSession("session expired")
        return SessionClaims(tenant_id=TenantId(tid), employee_id=EmployeeId(sub))


async def principal_from_token(
    token: str, *, tokens: SessionTokens, employees: EmployeeRepository
) -> Principal:
    """Bearer token → verified ids → current employee record → ``Principal``."""
    claims = tokens.verify(token)
    employee = await employees.get(claims.tenant_id, claims.employee_id)
    if employee is None:
        raise InvalidSession("unknown employee")
    return principal_for(employee)
