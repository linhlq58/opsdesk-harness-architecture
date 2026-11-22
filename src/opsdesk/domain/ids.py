"""Typed identifiers for domain entities.

At runtime each id is a plain ``str`` (zero cost, serialises naturally). For the type
checker they are distinct types, so passing an ``EmployeeId`` where a ``TicketId`` is
expected is a pyright error instead of a silent bug.

    ticket_id = TicketId("T-0001")
    repo.get(tenant_id, ticket_id)       # ok
    repo.get(tenant_id, employee.id)     # pyright: EmployeeId is not TicketId
"""

from typing import NewType

TenantId = NewType("TenantId", str)
EmployeeId = NewType("EmployeeId", str)
TicketId = NewType("TicketId", str)
SoftwareId = NewType("SoftwareId", str)
AccessRequestId = NewType("AccessRequestId", str)
