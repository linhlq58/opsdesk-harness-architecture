"""Domain exceptions.

Two ways a policy can say "no":

* **Query policies** (``can_view_ticket``, ``can_decide``) return a ``Decision`` with a
  reason code. Saying "no" is a normal answer, not an error.
* **Command policies** (``transition``, ``approve``, ``reject``) either return the new
  entity or raise one of the exceptions below.

These exceptions never reach the model. Later layers (tools, M03+) catch them and map
them to a ``ToolResult`` status from the shared error taxonomy.
"""

from opsdesk.domain.decisions import ReasonCode


class DomainError(Exception):
    """Base class for every business-rule violation."""


class InvalidTransition(DomainError):
    """The requested state change does not exist in the state machine.

    Examples: ``closed`` -> anything, ``open`` -> ``resolved``, ``open`` -> ``open``.
    """


class NotPermitted(DomainError):
    """The state change exists, but this actor may not perform it.

    Examples: a regular employee moving ``open`` -> ``in_progress``, an actor from
    another tenant, a manager approving their own request.

    ``reason`` carries the policy's reason code when one exists (e.g. from
    ``can_decide``), so callers can map it without parsing the message.
    """

    def __init__(self, message: str, reason: ReasonCode | None = None) -> None:
        super().__init__(message)
        self.reason = reason


class InvalidIdentifier(DomainError):
    """A string does not have the format of the id it claims to be.

    Example: ``parse_ticket_id("abc")``. Ids reach the harness from model tool
    arguments and user text, so a malformed one is an ordinary business error (the
    model should ask again), not a bug.

    ``kind`` names the id type (``"ticket"``) so callers can map it without parsing
    the message. The message quotes the bad value: fine for logs, never for the model.
    """

    def __init__(self, kind: str, value: str) -> None:
        super().__init__(f"not a valid {kind} id: {value!r}")
        self.kind = kind
