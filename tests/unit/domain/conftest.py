"""Factories for domain tests.

Each factory returns a valid entity and accepts keyword overrides, so a test only
spells out the fields that matter for the case it checks.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from opsdesk.domain.models import AccessRequest, Employee, SoftwareItem, Ticket

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

type Factory[T] = Callable[..., T]


@pytest.fixture
def make_employee() -> Factory[Employee]:
    def make(**overrides: Any) -> Employee:
        data: dict[str, Any] = {
            "id": "E-001",
            "tenant_id": "acme",
            "full_name": "An Nguyen",
            "email": "an@acme.test",
            "department": "engineering",
            "roles": ["employee"],
        }
        return Employee.model_validate(data | overrides)

    return make


@pytest.fixture
def make_ticket() -> Factory[Ticket]:
    def make(**overrides: Any) -> Ticket:
        data: dict[str, Any] = {
            "id": "T-0001",
            "tenant_id": "acme",
            "reporter_id": "E-001",
            "assignee_id": None,
            "title": "Laptop will not boot",
            "description": "Black screen after update",
            "category": "hardware",
            "priority": "high",
            "created_at": T0,
            "updated_at": T0,
        }
        return Ticket.model_validate(data | overrides)

    return make


@pytest.fixture
def make_software() -> Factory[SoftwareItem]:
    def make(**overrides: Any) -> SoftwareItem:
        data: dict[str, Any] = {"id": "SW-SLACK", "name": "Slack", "annual_cost": 1_200_000}
        return SoftwareItem.model_validate(data | overrides)

    return make


@pytest.fixture
def make_access_request() -> Factory[AccessRequest]:
    def make(**overrides: Any) -> AccessRequest:
        data: dict[str, Any] = {
            "id": "AR-001",
            "tenant_id": "acme",
            "requester_id": "E-001",
            "kind": "software_licence",
            "software_id": "SW-FIGMA",
            "justification": "Design reviews",
            "created_at": T0,
        }
        return AccessRequest.model_validate(data | overrides)

    return make
