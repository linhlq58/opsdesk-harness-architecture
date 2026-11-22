"""Who is asking: the server-side identity of the caller.

A ``Principal`` is built by the **server** (M04: from a verified token; tests and the
CLI: from a seed employee). It is never built from user text ("I am the IT manager"),
model output or retrieved documents.

It carries ids and permissions only: no name, no email. It is safe to log, to put in
traces and events, and to hand to any layer.

``principal_for`` is the **only** place scopes and groups are derived. The model
validator enforces it: a ``Principal`` whose scopes or groups do not match its roles
is rejected, so nobody can hand-craft one with extra permissions.
"""

from typing import Self

from pydantic import BaseModel, model_validator

from opsdesk.domain.ids import EmployeeId, TenantId
from opsdesk.domain.models import Department, Employee, Role
from opsdesk.security.scopes import Scope, scopes_for


def groups_for(roles: frozenset[Role], department: Department) -> frozenset[str]:
    """RAG ACL groups (M09 tags chunks with them, M10 filters on them).

    Role names plus ``dept:<department>``. Dung (finance) → ``{"employee", "finance",
    "dept:finance"}``.
    """
    return frozenset(role.value for role in roles) | {f"dept:{department.value}"}


class Principal(BaseModel, frozen=True, extra="forbid"):
    tenant_id: TenantId
    user_id: EmployeeId
    department: Department
    roles: frozenset[Role]
    scopes: frozenset[Scope]
    groups: frozenset[str]

    @model_validator(mode="after")
    def _derived_fields_match_roles(self) -> Self:
        if self.scopes != scopes_for(self.roles):
            raise ValueError("scopes must be derived from roles (use principal_for)")
        if self.groups != groups_for(self.roles, self.department):
            raise ValueError("groups must be derived from roles and department")
        return self

    def has_scope(self, scope: Scope) -> bool:
        return scope in self.scopes


def principal_for(employee: Employee) -> Principal:
    return Principal(
        tenant_id=employee.tenant_id,
        user_id=employee.id,
        department=employee.department,
        roles=employee.roles,
        scopes=scopes_for(employee.roles),
        groups=groups_for(employee.roles, employee.department),
    )
