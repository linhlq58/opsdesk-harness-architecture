"""Demo session tokens (M04 §8, ``POST /api/session`` and the Bearer check)."""

from datetime import timedelta

import jwt
import pytest

from opsdesk.api.auth import InvalidSession, SessionTokens, principal_from_token
from opsdesk.core.clock import FixedClock
from opsdesk.domain.ids import EmployeeId, TenantId
from opsdesk.domain.models import Employee
from opsdesk.domain.ports import Repositories
from opsdesk.security.principal import principal_for

SECRET = "s" * 32


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def tokens(clock: FixedClock) -> SessionTokens:
    return SessionTokens(secret=SECRET, ttl=timedelta(minutes=60), clock=clock)


async def _employee(repos: Repositories, employee_id: str, tenant: str = "acme") -> Employee:
    employee = await repos.employees.get(TenantId(tenant), EmployeeId(employee_id))
    assert employee is not None
    return employee


async def test_issued_token_resolves_to_the_employees_principal(
    tokens: SessionTokens, seed_repos: Repositories
) -> None:
    an = await _employee(seed_repos, "E-001")

    session = tokens.issue(an)
    principal = await principal_from_token(
        session.token, tokens=tokens, employees=seed_repos.employees
    )

    assert principal == principal_for(an)


async def test_token_carries_ids_only_never_roles_or_scopes(
    tokens: SessionTokens, seed_repos: Repositories
) -> None:
    session = tokens.issue(await _employee(seed_repos, "E-001"))

    claims = jwt.decode(session.token, options={"verify_signature": False})

    assert set(claims) == {"sub", "tid", "iat", "exp"}
    assert (claims["sub"], claims["tid"]) == ("E-001", "acme")


async def test_expires_after_the_ttl(
    tokens: SessionTokens, clock: FixedClock, seed_repos: Repositories
) -> None:
    session = tokens.issue(await _employee(seed_repos, "E-001"))
    assert session.expires_at == clock.now() + timedelta(minutes=60)

    clock.advance(timedelta(minutes=59))
    tokens.verify(session.token)  # still valid

    clock.advance(timedelta(minutes=1))
    with pytest.raises(InvalidSession):
        tokens.verify(session.token)


async def test_token_signed_with_another_secret_is_rejected(
    clock: FixedClock, tokens: SessionTokens, seed_repos: Repositories
) -> None:
    forger = SessionTokens(secret="f" * 32, ttl=timedelta(minutes=60), clock=clock)
    forged = forger.issue(await _employee(seed_repos, "E-005"))

    with pytest.raises(InvalidSession):
        tokens.verify(forged.token)


def test_unsigned_token_is_rejected(tokens: SessionTokens) -> None:
    # alg "none": the classic JWT attack. Only HS256 is accepted.
    unsigned = jwt.encode(
        {"sub": "E-005", "tid": "acme", "iat": 0, "exp": 2_000_000_000}, key=None, algorithm="none"
    )

    with pytest.raises(InvalidSession):
        tokens.verify(unsigned)


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.b.c"])
def test_garbage_is_rejected(tokens: SessionTokens, token: str) -> None:
    with pytest.raises(InvalidSession):
        tokens.verify(token)


def test_missing_claims_are_rejected(tokens: SessionTokens) -> None:
    no_tenant = jwt.encode({"sub": "E-001", "iat": 0, "exp": 2_000_000_000}, SECRET, "HS256")

    with pytest.raises(InvalidSession):
        tokens.verify(no_tenant)


async def test_valid_token_for_an_unknown_employee_is_rejected(
    tokens: SessionTokens, seed_repos: Repositories, clock: FixedClock
) -> None:
    ghost = jwt.encode(
        {"sub": "E-999", "tid": "acme", "iat": 0, "exp": int(clock.now().timestamp()) + 60},
        SECRET,
        "HS256",
    )

    with pytest.raises(InvalidSession):
        await principal_from_token(ghost, tokens=tokens, employees=seed_repos.employees)


def test_ttl_must_be_positive(clock: FixedClock) -> None:
    with pytest.raises(ValueError, match="ttl"):
        SessionTokens(secret=SECRET, ttl=timedelta(0), clock=clock)
