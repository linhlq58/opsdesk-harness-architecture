"""Map domain answers to ``ToolResult`` (the tool layer's job; M03's wrapper calls it).

A domain policy says "no" in one of two ways (see ``domain.errors``):

* a **query policy** (``can_view_ticket``, ``can_decide``, ``require_scope``) returns a
  denied ``Decision``            → ``result_from_decision``;
* a **command policy** (``transition``, ``approve``, ``reject``) raises a
  ``DomainError``                → ``result_from_domain_error``.

=========================  ===========  ==================================
input                      status       error_code
=========================  ===========  ==================================
``InvalidTransition``      ``invalid``  ``"invalid_transition"``
``NotPermitted(reason=r)`` ``denied``   ``r.value``, or ``"not_permitted"``
``Decision.deny(r)``       ``denied``   ``r.value``
any other ``DomainError``  ``invalid``  ``"domain_error"``
=========================  ===========  ==================================

Only ``DomainError`` is mapped. Bugs (``KeyError``, ``AttributeError``, ...) are **not**
caught here: they must surface, be logged and get fixed. Wrapping everything in
``except Exception`` would disguise bugs as "the tool said no" and make evals blame the
agent for broken code.

``safe_message`` comes from a fixed table, never from ``str(exc)``: domain exception
messages contain ids and tenant names (``"E-006 is not in tenant acme"``), which the
model must not see. Tools that know a better wording can pass ``safe_message=``.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Never

from opsdesk.core.result import ToolResult
from opsdesk.domain.decisions import Decision, ReasonCode
from opsdesk.domain.errors import DomainError, InvalidTransition, NotPermitted

# Written for the model to read and relay. No ids, no tenant names, and CROSS_TENANT
# deliberately does not confirm that the item exists somewhere else.
_SAFE_MESSAGES: Mapping[ReasonCode, str] = MappingProxyType(
    {
        ReasonCode.MISSING_SCOPE: "You are not allowed to use this function.",
        ReasonCode.CROSS_TENANT: "You do not have access to this item.",
        ReasonCode.NOT_OWNER: "You can only access items you reported or are assigned to.",
        ReasonCode.NOT_APPROVER: "Only an IT manager can approve or reject access requests.",
        ReasonCode.SELF_APPROVAL: "You cannot approve or reject your own request.",
        ReasonCode.NOT_PENDING: "This request has already been decided.",
        ReasonCode.INVALID_REQUEST: "This access request is not valid.",
        ReasonCode.DEPARTMENT_RESTRICTED: "This software is not available to your department.",
        ReasonCode.ALREADY_OWNED: "You already have this software.",
        ReasonCode.ADMIN_RIGHTS: "This request needs admin rights and must be reviewed.",
        ReasonCode.HIGH_COST: "This software is above the cost limit and must be reviewed.",
    }
)
_NOT_PERMITTED = "You are not allowed to perform this action."
_INVALID_TRANSITION = "That status change is not possible for this ticket."
_DOMAIN_ERROR = "This request cannot be completed."


def result_from_decision(
    decision: Decision, *, safe_message: str | None = None
) -> ToolResult[Never]:
    """``Decision.deny(r)`` → ``denied`` with ``error_code=r.value``.

    Only for denied decisions: passing an allowed one is a caller bug, so it raises
    ``ValueError`` instead of inventing a result.
    """
    if decision.allowed:
        raise ValueError("result_from_decision only maps denied decisions")
    return ToolResult.denied(safe_message or _SAFE_MESSAGES[decision.reason], decision.reason.value)


def result_from_domain_error(
    exc: DomainError, *, safe_message: str | None = None
) -> ToolResult[Never]:
    """Map a business-rule violation; see the table in the module docstring."""
    match exc:
        case InvalidTransition():
            return ToolResult.invalid(safe_message or _INVALID_TRANSITION, "invalid_transition")
        case NotPermitted(reason=ReasonCode() as reason):
            return ToolResult.denied(safe_message or _SAFE_MESSAGES[reason], reason.value)
        case NotPermitted():
            return ToolResult.denied(safe_message or _NOT_PERMITTED, "not_permitted")
        case DomainError():
            return ToolResult.invalid(safe_message or _DOMAIN_ERROR, "domain_error")
        case _:  # pyright: ignore[reportUnnecessaryComparison]
            # Unreachable for type-checked callers. At runtime it stops a bug (or a
            # BudgetExceeded) from being quietly turned into "invalid".
            raise TypeError(f"not a DomainError: {type(exc).__name__}") from exc
