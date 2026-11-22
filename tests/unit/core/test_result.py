from typing import Any

import pytest
from pydantic import ValidationError

from opsdesk.core.result import ErrorClass, ToolResult, ToolStatus

# ------------------------------------------------------------------------- taxonomy


@pytest.mark.parametrize(
    ("status", "error_class", "retryable", "is_error"),
    [
        (ToolStatus.OK, ErrorClass.NONE, False, False),
        (ToolStatus.EMPTY, ErrorClass.NONE, False, False),
        (ToolStatus.NOT_FOUND, ErrorClass.BUSINESS, False, True),
        (ToolStatus.INVALID, ErrorClass.BUSINESS, False, True),
        (ToolStatus.DENIED, ErrorClass.POLICY, False, True),
        (ToolStatus.UNAVAILABLE, ErrorClass.TRANSIENT, True, True),
        (ToolStatus.TIMEOUT, ErrorClass.TRANSIENT, True, True),
    ],
)
def test_every_status_has_exactly_one_class(
    status: ToolStatus, error_class: ErrorClass, retryable: bool, is_error: bool
) -> None:
    assert status.error_class is error_class
    assert status.retryable is retryable
    assert status.is_error is is_error


def test_table_covers_every_status() -> None:
    # Adding a status without classifying it would make .error_class raise KeyError.
    for status in ToolStatus:
        assert isinstance(status.error_class, ErrorClass)


# ---------------------------------------------------------------------- constructors


def test_ok() -> None:
    r = ToolResult.ok({"id": "T-0001"})
    assert r.status is ToolStatus.OK
    assert r.data == {"id": "T-0001"}
    assert r.safe_message is None and r.error_code is None


def test_ok_accepts_falsy_but_present_data() -> None:
    # 0 / False / "" are real answers; only None means "no data".
    assert ToolResult.ok(0).data == 0
    assert ToolResult.ok(False).data is False


def test_empty() -> None:
    r = ToolResult.empty()
    assert r.status is ToolStatus.EMPTY
    assert r.data is None and r.error_code is None
    assert ToolResult.empty("You have no open tickets.").safe_message == (
        "You have no open tickets."
    )


@pytest.mark.parametrize(
    ("factory", "status"),
    [
        (ToolResult.not_found, ToolStatus.NOT_FOUND),
        (ToolResult.invalid, ToolStatus.INVALID),
        (ToolResult.denied, ToolStatus.DENIED),
        (ToolResult.unavailable, ToolStatus.UNAVAILABLE),
        (ToolResult.timeout, ToolStatus.TIMEOUT),
    ],
)
def test_error_constructors(factory: Any, status: ToolStatus) -> None:
    r = factory("Something safe to say.", "some_code")
    assert r.status is status
    assert r.data is None
    assert r.safe_message == "Something safe to say."
    assert r.error_code == "some_code"


# ------------------------------------------------------------------------ invariants


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "ok"},  # ok without data
        {"status": "ok", "data": None},
        {"status": "ok", "data": 1, "safe_message": "x"},
        {"status": "ok", "data": 1, "error_code": "x"},
        {"status": "empty", "data": [1]},  # empty with content
        {"status": "empty", "data": 5},
        {"status": "empty", "error_code": "x"},  # empty is not an error
        {"status": "denied", "safe_message": "x"},  # missing error_code
        {"status": "denied", "error_code": "x"},  # missing safe_message
        {"status": "denied", "safe_message": "x", "error_code": "y", "data": 1},
        {"status": "timeout", "safe_message": "", "error_code": "y"},  # empty message
        {"status": "not_found", "safe_message": "x", "error_code": ""},
        {"status": "nope", "data": 1},  # unknown status
        {"status": "ok", "data": 1, "extra": "x"},  # unknown field
    ],
)
def test_invalid_combinations_are_rejected(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ToolResult[Any].model_validate(fields)


@pytest.mark.parametrize("data", [None, [], {}, ""])
def test_empty_allows_none_or_empty_collection(data: Any) -> None:
    r = ToolResult[Any].model_validate({"status": "empty", "data": data})
    assert r.status is ToolStatus.EMPTY


def test_result_is_immutable() -> None:
    r = ToolResult.ok(1)
    with pytest.raises(ValidationError):
        r.status = ToolStatus.DENIED  # type: ignore[misc]


# ---------------------------------------------------------------------- serialisation


def test_json_round_trip() -> None:
    r = ToolResult.denied("You can only view your own tickets.", "not_owner")
    dumped = r.model_dump_json()
    assert '"status":"denied"' in dumped
    assert ToolResult[Any].model_validate_json(dumped) == r


def test_typed_data_is_validated() -> None:
    with pytest.raises(ValidationError):
        ToolResult[int].model_validate({"status": "ok", "data": "not an int"})
