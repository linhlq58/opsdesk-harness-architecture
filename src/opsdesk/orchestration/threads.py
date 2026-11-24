"""Thread ownership (M04 §5, decision D5).

A *thread* is one conversation: the checkpointer stores its message history under
the ``thread_id``. Whoever can run a turn on a thread id gets that whole history fed
to the model, so a thread id is effectively the key to a conversation. Therefore:

* **The server creates thread ids** (``create``), random and unguessable
  (``new_thread_id``), and binds each one to its owner ``(tenant_id, user_id)``.
  A client never invents one.
* **Every chat turn checks ownership first** (``require_owner``), before a run starts
  and before the checkpointer is touched.
* **A thread belongs to one pattern** (M05 §10): ``create`` records the pattern the
  thread was made for (ticket agent, router, ...), and ``require_owner`` also checks
  it. The checkpointer stores each pattern's state in a different shape (the router
  has ``routes``/``results``, the ticket agent does not), so one thread id must never
  be fed to two graphs.
* "Does not exist", "belongs to someone else" and "made for another pattern" raise the
  **same**
  ``ThreadNotFound`` with the same message, and the API maps both to the same
  ``404``: a caller cannot tell a foreign thread from a missing one, so probing ids
  reveals nothing.

In memory for now: lost on restart, like ``InMemorySaver``; both become durable in
M14a. The owner is compared on ids from the server-built ``Principal`` only.

Tests: ``tests/unit/orchestration/test_threads.py`` (cases R1-R4, plus patterns).
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from opsdesk.core.ids import ThreadId, new_thread_id
from opsdesk.domain.ids import EmployeeId, TenantId
from opsdesk.security.principal import Principal


class Pattern(StrEnum):
    """The orchestration patterns a thread can be created for (one UI tab each)."""

    TICKET_AGENT = "ticket_agent"  # M03/M04: one agent with the ticket tools
    ROUTER = "router"  # M05: router → parallel specialists → synthesis


class ThreadNotFound(Exception):
    """Unknown thread, someone else's, or another pattern's (deliberately the same)."""

    def __init__(self) -> None:
        super().__init__("thread not found")  # never echoes the id or the owner


@dataclass(frozen=True, slots=True)
class _Binding:
    """Who may use a thread, and with which pattern."""

    tenant_id: TenantId
    user_id: EmployeeId
    pattern: Pattern

    @classmethod
    def of(cls, principal: Principal, pattern: Pattern) -> "_Binding":
        return cls(principal.tenant_id, principal.user_id, pattern)


class ThreadRegistry:
    def __init__(self, *, new_id: Callable[[], ThreadId] = new_thread_id) -> None:
        self._new_id = new_id
        self._bindings: dict[ThreadId, _Binding] = {}

    def create(self, principal: Principal, pattern: Pattern) -> ThreadId:
        """A new thread owned by ``principal``, usable with ``pattern`` only."""
        thread_id = self._new_id()
        if thread_id in self._bindings:  # uuid4 collision, or a broken new_id in a test
            raise RuntimeError("thread id already exists")
        self._bindings[thread_id] = _Binding.of(principal, pattern)
        return thread_id

    def require_owner(self, principal: Principal, thread_id: ThreadId, pattern: Pattern) -> None:
        """Return if ``principal`` owns ``thread_id`` and it was made for ``pattern``;
        otherwise ``ThreadNotFound`` (one comparison, so all three cases look alike)."""
        if self._bindings.get(thread_id) != _Binding.of(principal, pattern):
            raise ThreadNotFound()
