"""Typed identifiers for domain entities.

At runtime each id is a plain ``str`` (zero cost, serialises naturally). For the type
checker they are distinct types, so passing an ``EmployeeId`` where a ``TicketId`` is
expected is a pyright error instead of a silent bug.

    ticket_id = TicketId("T-0001")
    repo.get(tenant_id, ticket_id)       # ok
    repo.get(tenant_id, employee.id)     # pyright: EmployeeId is not TicketId

``TicketId("abc")`` checks nothing: ``NewType`` is for the type checker only. Text that
comes from outside (a model's tool argument, the user) goes through ``parse_ticket_id``,
which checks the format and raises ``InvalidIdentifier`` otherwise.
"""

import re
from typing import NewType

from opsdesk.domain.errors import InvalidIdentifier

TenantId = NewType("TenantId", str)
EmployeeId = NewType("EmployeeId", str)
TicketId = NewType("TicketId", str)
SoftwareId = NewType("SoftwareId", str)
AccessRequestId = NewType("AccessRequestId", str)

# [0-9], not \d: in Python \d also matches Arabic-Indic and other Unicode digits.
_TICKET_ID = re.compile(r"T-[0-9]{4}")


def parse_ticket_id(raw: str) -> TicketId:
    """``"T-0002"`` → ``TicketId("T-0002")``; anything else raises ``InvalidIdentifier``.

    Surrounding whitespace and letter case are forgiven (``" t-0002 "`` is accepted):
    a model or a user typing in lower case is not an attack, and refusing it would
    only cost a round trip. Nothing else is: no other prefix, no missing digits.
    """
    candidate = raw.strip().upper()
    if not _TICKET_ID.fullmatch(candidate):
        raise InvalidIdentifier("ticket", raw)
    return TicketId(candidate)
