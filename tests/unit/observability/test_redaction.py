import copy

import pytest
from pydantic import JsonValue

from opsdesk.observability.redaction import REDACTED, redact

# ------------------------------------------------------------------ sensitive keys


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "PASSWORD",
        "db_password",
        "client_secret",
        "access_token",
        "refreshToken",
        "api_key",
        "apiKey",
        "X-API-KEY",
        "Authorization",
        "cookie",
        "Set-Cookie",
    ],
)
def test_sensitive_keys_are_redacted(key: str) -> None:
    assert redact({key: "s3cr3t"}) == {key: REDACTED}


def test_sensitive_value_is_redacted_whatever_its_type() -> None:
    assert redact({"token": {"value": "x", "exp": 1}}) == {"token": REDACTED}
    assert redact({"password": 12345}) == {"password": REDACTED}


def test_redaction_is_recursive_through_dicts_and_lists() -> None:
    value: JsonValue = {
        "ticket_id": "T-0001",
        "auth": {"headers": [{"Authorization": "Bearer abc"}, {"Accept": "json"}]},
    }
    assert redact(value) == {
        "ticket_id": "T-0001",
        "auth": {"headers": [{"Authorization": REDACTED}, {"Accept": "json"}]},
    }


def test_ordinary_keys_are_kept() -> None:
    value: JsonValue = {"ticket_id": "T-0042", "status": "open", "count": 3, "ok": True}
    assert redact(value) == value


# ----------------------------------------------------------------------------- PII


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("an.nguyen@acme.example", "a***@acme.example"),
        ("Contact dung.pham@acme.test now", "Contact d***@acme.test now"),
        ("a@b.co and x.y@globex.example", "a***@b.co and x***@globex.example"),
    ],
)
def test_emails_are_masked(text: str, expected: str) -> None:
    assert redact(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0901234567", "***567"),
        ("Gọi 090-123-4567 nhé", "Gọi ***567 nhé"),
        ("+84 90 123 4567", "***567"),
        ("+84.901.234.567", "***567"),
    ],
)
def test_phone_numbers_are_masked(text: str, expected: str) -> None:
    assert redact(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "T-0042",  # ticket id
        "AR-0003",
        "2026-03-01",  # date
        "2026-03-01T09:00:00+00:00",
        "5000000",  # VND amount
        "150000000",  # large VND amount: does not start with 0 or +
        "req_3f2a9c0e8b7d4a1f9e6c5b4a3d2e1f00",  # correlation id
    ],
)
def test_ids_dates_and_amounts_are_not_mistaken_for_pii(text: str) -> None:
    assert redact(text) == text


# -------------------------------------------------------------------- truncation


def test_long_strings_are_truncated_with_a_count() -> None:
    assert redact("x" * 510, max_chars=500) == "x" * 500 + "…[+10 chars]"


def test_strings_at_the_limit_are_kept() -> None:
    assert redact("x" * 500, max_chars=500) == "x" * 500


def test_truncation_applies_inside_nested_values() -> None:
    assert redact({"notes": ["abcdef"]}, max_chars=3) == {"notes": ["abc…[+3 chars]"]}


def test_vietnamese_text_is_counted_in_characters() -> None:
    assert redact("Máy in tầng 3 bị kẹt giấy", max_chars=6) == "Máy in…[+19 chars]"


# ------------------------------------------------------------------------- purity


def test_input_is_not_mutated() -> None:
    value: JsonValue = {"password": "x", "items": [{"email": "an@acme.test"}], "n": 1}
    before = copy.deepcopy(value)
    result = redact(value)
    assert value == before
    assert result is not value


@pytest.mark.parametrize("scalar", [None, True, 0, 1.5])
def test_scalars_pass_through(scalar: JsonValue) -> None:
    assert redact(scalar) == scalar
