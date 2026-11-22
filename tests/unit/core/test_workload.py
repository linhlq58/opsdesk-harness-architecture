from opsdesk.core.workload import Workload


def test_workload_values_are_stable_strings() -> None:
    # These strings are stored in events, the cost ledger and eval datasets:
    # changing one is a breaking change.
    assert [w.value for w in Workload] == ["chat", "eval", "report"]
    assert Workload("eval") is Workload.EVAL
