"""Which kind of work a request belongs to.

Lives in ``core`` because four layers use it: ``security`` (``RequestContext``),
``observability`` (``run_started`` payload), ``cost`` (separate daily budgets for chat
and evaluation, M16) and ``evaluation`` (the eval suite filters its own runs, M17).
"""

from enum import StrEnum


class Workload(StrEnum):
    CHAT = "chat"  # a user talking to the helpdesk
    EVAL = "eval"  # the evaluation suite replaying a dataset
    REPORT = "report"  # the weekly report Deep Agent (M20)
