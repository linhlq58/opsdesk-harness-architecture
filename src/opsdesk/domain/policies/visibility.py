"""Who may see a ticket (M01 §3.1).

Rules, checked in this order; the first that matches wins:

1. Different tenant          -> deny CROSS_TENANT   (nothing can override this)
2. Reporter or assignee       -> allow
3. IT staff or IT manager     -> allow
4. Anyone else                -> deny NOT_OWNER

Business roles such as ``hr`` or ``finance`` grant nothing here: being HR does not
mean you may read an employee's laptop ticket.
"""

from opsdesk.domain.decisions import Decision, ReasonCode
from opsdesk.domain.models import Employee, Ticket


def can_view_ticket(actor: Employee, ticket: Ticket) -> Decision:
    # 1. Tenant isolation first. Ids are only unique *within* a tenant, so comparing
    #    ids before tenants could let Globex's "E-001" read Acme's "E-001" tickets.
    if actor.tenant_id != ticket.tenant_id:
        return Decision.deny(ReasonCode.CROSS_TENANT)

    # 2. Ownership: the people directly involved in the ticket.
    if actor.id in (ticket.reporter_id, ticket.assignee_id):
        return Decision.allow()

    # 3. IT can see every ticket in their own tenant (they triage the queue).
    if actor.is_it:
        return Decision.allow()

    # 4. Default deny: anything not explicitly allowed above is refused.
    return Decision.deny(ReasonCode.NOT_OWNER)
