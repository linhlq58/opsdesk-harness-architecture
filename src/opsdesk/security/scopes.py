"""Scopes and the role → scope table.

Two layers of authorization, two questions:

* **Scope** (here, coarse): "may this *kind* of user call this *kind* of tool at all?"
  Checked once, before a tool runs (``security.authz.require_scope``).
* **Domain policy** (M01, fine-grained): "may this user act on *this* entity?"
  e.g. ``can_view_ticket``. Checked inside the tool, per entity.

A tool call needs both. An employee has ``ticket:read`` (they may open the ticket tool),
but ``can_view_ticket`` still hides other people's tickets.

The table is **code, not configuration**, permanently. Who may do what is part of the
security model: a change goes through code review and tests. ``config/policy.yaml``
(M14) holds tunables only (thresholds, budgets, retry/timeout); a YAML typo there must
never be able to grant ``access:approve`` to everyone.
"""

from collections.abc import Iterable, Mapping
from enum import StrEnum
from types import MappingProxyType

from opsdesk.domain.models import Role


class Scope(StrEnum):
    TICKET_READ = "ticket:read"
    TICKET_CREATE = "ticket:create"
    TICKET_UPDATE = "ticket:update"
    ACCESS_REQUEST = "access:request"
    KB_READ = "kb:read"
    ASSET_READ = "asset:read"  # any device in the tenant (IT)
    ASSET_READ_OWN = "asset:read_own"  # M05 D8: only the devices assigned to the caller
    ACCESS_APPROVE = "access:approve"
    REPORT_READ = "report:read"


_EMPLOYEE = frozenset(
    {
        Scope.TICKET_READ,
        Scope.TICKET_CREATE,
        Scope.TICKET_UPDATE,
        Scope.ACCESS_REQUEST,
        Scope.KB_READ,
        # M05 D8: employees may ask about their own devices. The tool, not the scope,
        # limits the answer to the caller's devices (scope = coarse, tool = per entity).
        Scope.ASSET_READ_OWN,
    }
)
_IT_STAFF = _EMPLOYEE | {Scope.ASSET_READ}
_IT_MANAGER = _IT_STAFF | {Scope.ACCESS_APPROVE, Scope.REPORT_READ}

# Read-only view: nothing can add a role or a scope at runtime.
ROLE_SCOPES: Mapping[Role, frozenset[Scope]] = MappingProxyType(
    {
        Role.EMPLOYEE: _EMPLOYEE,
        Role.IT_STAFF: _IT_STAFF,
        Role.IT_MANAGER: _IT_MANAGER,
        # hr / finance add no scopes, only RAG ACL groups (see principal.py).
        Role.HR: frozenset(),
        Role.FINANCE: frozenset(),
    }
)


def scopes_for(roles: Iterable[Role]) -> frozenset[Scope]:
    """Union of the scopes of every role. A role missing from the table is a bug."""
    result: frozenset[Scope] = frozenset()
    for role in roles:
        result |= ROLE_SCOPES[role]
    return result
