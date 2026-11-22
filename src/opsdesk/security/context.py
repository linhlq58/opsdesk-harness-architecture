"""Everything the server knows about the current request, besides the conversation.

Rules:

* Built **once per request** by the server: M04 from the verified token; tests and the
  CLI from ``principal_for(seed_employee)``.
* Passed to graphs and tools through **LangGraph runtime context** (M03), beside the
  conversation, **never inside it**: it is not put in messages sent to the model, and
  it is never filled from a model's tool arguments. A tool reads the caller's identity
  from here, so "I am the IT manager" in the chat changes nothing.
* ``request_id`` / ``thread_id`` correlate events, traces, audit and the cost ledger.
  The event recorder takes just those two ids, not this object (observability knows
  nothing about principals).
* ``workload`` separates chat spending from evaluation spending (M16) and lets the eval
  suite filter its own runs (M17).
"""

from pydantic import BaseModel

from opsdesk.core.ids import RequestId, ThreadId
from opsdesk.core.workload import Workload
from opsdesk.security.principal import Principal


class RequestContext(BaseModel, frozen=True, extra="forbid"):
    principal: Principal
    request_id: RequestId  # one user turn
    thread_id: ThreadId  # one conversation (LangGraph thread)
    workload: Workload
