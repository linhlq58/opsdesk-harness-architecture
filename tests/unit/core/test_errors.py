import pytest

from opsdesk.core.errors import BudgetExceeded


@pytest.mark.parametrize("scope", ["turn", "thread", "day"])
def test_budget_exceeded_carries_its_scope(scope: str) -> None:
    exc = BudgetExceeded(scope)  # type: ignore[arg-type]
    assert exc.scope == scope
    assert scope in str(exc)


def test_budget_exceeded_custom_message() -> None:
    exc = BudgetExceeded("day", "daily chat budget reached")
    assert str(exc) == "daily chat budget reached"


def test_budget_exceeded_is_not_a_domain_error() -> None:
    # It must not be caught by result_from_domain_error: it stops the run.
    from opsdesk.domain.errors import DomainError

    assert not issubclass(BudgetExceeded, DomainError)
