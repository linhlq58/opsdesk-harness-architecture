"""Coarse authorization: does the principal hold a scope?

Returns a ``Decision`` (same shape as the M01 domain policies), not a ``bool``, so the
caller can map a denial straight to ``ToolResult.denied(..., "missing_scope")`` with
``tools.taxonomy.result_from_decision`` and the reason shows up in events and evals.
"""

from opsdesk.domain.decisions import Decision, ReasonCode
from opsdesk.security.principal import Principal
from opsdesk.security.scopes import Scope


def require_scope(principal: Principal, scope: Scope) -> Decision:
    if principal.has_scope(scope):
        return Decision.allow()
    return Decision.deny(ReasonCode.MISSING_SCOPE)
