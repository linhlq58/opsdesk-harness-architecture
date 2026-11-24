"""Thread ownership (M04 §5, decision D5).

A *thread* is one conversation: the checkpointer stores its message history under
the ``thread_id``. Whoever can run a turn on a thread id gets that whole history fed
to the model, so a thread id is effectively the key to a conversation. Therefore:

* **The server creates thread ids** (``create``), random and unguessable
  (``new_thread_id``), and binds each one to its owner ``(tenant_id, user_id)``.
  A client never invents one.
* **Every chat turn checks ownership first** (``require_owner``), before a run starts
  and before the checkpointer is touched.
* "Does not exist" and "belongs to someone else" raise the **same**
  ``ThreadNotFound`` with the same message, and the API maps both to the same
  ``404``: a caller cannot tell a foreign thread from a missing one, so probing ids
  reveals nothing.

In memory for now: lost on restart, like ``InMemorySaver``; both become durable in
M14a. The owner is compared on ids from the server-built ``Principal`` only.

Tests: ``tests/unit/orchestration/test_threads.py`` (cases R1-R4).
"""

from collections.abc import Callable
from dataclasses import dataclass

from opsdesk.core.ids import ThreadId, new_thread_id
from opsdesk.domain.ids import EmployeeId, TenantId
from opsdesk.security.principal import Principal


class ThreadNotFound(Exception):
    """Unknown thread, or a thread owned by someone else (deliberately the same)."""

    def __init__(self) -> None:
        super().__init__("thread not found")  # never echoes the id or the owner


@dataclass(frozen=True, slots=True)
class _Owner:
    tenant_id: TenantId
    user_id: EmployeeId

    @classmethod
    def of(cls, principal: Principal) -> "_Owner":
        return cls(principal.tenant_id, principal.user_id)


class ThreadRegistry:
    def __init__(self, *, new_id: Callable[[], ThreadId] = new_thread_id) -> None:
        self._new_id = new_id
        self._owners: dict[ThreadId, _Owner] = {}

    def create(self, principal: Principal) -> ThreadId:
        """A new thread owned by ``principal``."""
        thread_id = self._new_id()
        if thread_id in self._owners:  # uuid4 collision, or a broken new_id in a test
            raise RuntimeError("thread id already exists")
        self._owners[thread_id] = _Owner.of(principal)
        return thread_id

    def require_owner(self, principal: Principal, thread_id: ThreadId) -> None:
        """Return if ``principal`` owns ``thread_id``; otherwise ``ThreadNotFound``."""
        if self._owners.get(thread_id) != _Owner.of(principal):
            raise ThreadNotFound()
