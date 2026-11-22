"""Harness-level exceptions (not business rules: those are in ``domain.errors``).

Most failures are *answers*, returned as a ``ToolResult`` so the model can react to
them (``denied``, ``not_found``, ...). ``BudgetExceeded`` is different: it stops the
whole **run**, not one tool call, so it is an exception that unwinds past the agent
loop. It is never retried and never shown to the model.
"""

from typing import Literal

type BudgetScope = Literal["turn", "thread", "day"]


class BudgetExceeded(Exception):
    """Raised before a model call when it would exceed a budget (M16). Never retried.

    ``scope`` says which budget was hit, so the caller can pick the right message
    ("this question is too expensive" vs "daily limit reached") and the ``run_finished``
    event can record ``status="blocked"``.
    """

    def __init__(self, scope: BudgetScope, message: str | None = None) -> None:
        super().__init__(message or f"{scope} budget exceeded")
        self.scope: BudgetScope = scope
