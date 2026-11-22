import dataclasses
import json
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from opsdesk.core.money import Money

# --------------------------------------------------------------------- construction


@pytest.mark.parametrize(
    ("valid_input", "expected"),
    [
        (10000, Decimal("10000")),
        ("25000", Decimal("25000")),
        (Decimal("50000"), Decimal("50000")),
        (0, Decimal(0)),
        (" 1200000 ", Decimal("1200000")),
    ],
)
def test_money_creation_valid_types(valid_input: Any, expected: Decimal) -> None:
    m = Money(valid_input)
    # isinstance matters: 10000 == Decimal("10000") is True, so == alone would not
    # catch an implementation that forgot to convert.
    assert isinstance(m.amount, Decimal)
    assert m.amount == expected
    assert m.currency == "VND"


@pytest.mark.parametrize("value", [Decimal("1500.00"), "1E+3", Decimal("100.0")])
def test_whole_numbers_written_with_decimals_or_exponent_are_accepted(value: Any) -> None:
    m = Money(value)
    # Normalised: no trailing ".00", no exponent, so repr / storage is stable.
    assert m.amount.as_tuple().exponent == 0


@pytest.mark.parametrize("float_input", [1500.5, 1000.0, 0.0])
def test_money_creation_rejects_float(float_input: Any) -> None:
    with pytest.raises(TypeError, match="float"):
        Money(float_input)


@pytest.mark.parametrize("bad_type", [True, False, None, [1000], {"amount": 1}])
def test_money_creation_rejects_other_types(bad_type: Any) -> None:
    with pytest.raises(TypeError):
        Money(bad_type)


@pytest.mark.parametrize("fractional_input", ["1500.5", Decimal("1500.50"), "0.1"])
def test_money_rejects_fractional_vnd(fractional_input: Any) -> None:
    with pytest.raises(ValueError, match="whole"):
        Money(fractional_input)


@pytest.mark.parametrize("garbage", ["abc", "", "1,000", "10k"])
def test_money_rejects_non_numeric_strings(garbage: str) -> None:
    with pytest.raises(ValueError, match="not a number"):
        Money(garbage)


@pytest.mark.parametrize("special", ["NaN", "Infinity", "-Infinity", Decimal("sNaN")])
def test_money_rejects_non_finite(special: Any) -> None:
    with pytest.raises(ValueError, match="finite"):
        Money(special)


@pytest.mark.parametrize("negative", [-1, "-500", Decimal("-1")])
def test_money_rejects_negative(negative: Any) -> None:
    with pytest.raises(ValueError, match="negative"):
        Money(negative)


def test_money_rejects_unsupported_currency_at_runtime() -> None:
    # Literal["VND"] is only checked by pyright; this is the runtime guard.
    with pytest.raises(ValueError, match="currency"):
        Money(1, "USD")  # type: ignore[arg-type]


def test_money_is_immutable() -> None:
    m = Money(1000)
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.amount = Decimal(1)  # type: ignore[misc]


def test_zero() -> None:
    assert Money.zero() == Money(0)
    assert Money.zero().amount == Decimal(0)


# ------------------------------------------------------------------------ arithmetic


def test_addition_returns_a_new_money() -> None:
    a, b = Money(1_200_000), Money("300000")
    total = a + b
    assert total == Money(1_500_000)
    assert a == Money(1_200_000)  # operands unchanged


def test_sum_works_with_zero_as_start() -> None:
    prices = [Money(100), Money(200), Money(300)]
    assert sum(prices, Money.zero()) == Money(600)


@pytest.mark.parametrize("other", [1, Decimal(1), "1", 1.0])
def test_addition_with_non_money_is_a_type_error(other: Any) -> None:
    with pytest.raises(TypeError):
        _ = Money(1) + other
    with pytest.raises(TypeError):
        _ = other + Money(1)


def test_currency_mismatch_is_rejected() -> None:
    # Only VND exists today, so build a USD amount by bypassing the constructor.
    # This simulates M07, when a second currency is added.
    usd = object.__new__(Money)
    object.__setattr__(usd, "amount", Decimal(1))
    object.__setattr__(usd, "currency", "USD")
    with pytest.raises(ValueError, match="mismatch"):
        _ = Money(1) + usd
    with pytest.raises(ValueError, match="mismatch"):
        _ = Money(1) < usd


# ------------------------------------------------------------------------ comparison


def test_ordering() -> None:
    small, big = Money(4_999_999), Money(5_000_000)
    assert small < big
    assert small <= big
    assert big > small
    assert big >= small
    assert big <= Money(5_000_000)
    assert big >= Money(5_000_000)
    assert not big < Money(5_000_000)


def test_equality() -> None:
    assert Money(1000) == Money("1000") == Money(Decimal("1000.00"))
    assert Money(1000) != Money(1001)
    # A Money is never equal to a bare number: the currency would be lost.
    assert Money(1000) != 1000
    assert Money(1000) != Decimal(1000)


def test_equal_money_hashes_equal() -> None:
    assert hash(Money(1000)) == hash(Money("1000.0"))
    assert len({Money(1), Money("1"), Money(2)}) == 2


@pytest.mark.parametrize("other", [5, Decimal(5)])
def test_ordering_with_non_money_is_a_type_error(other: Any) -> None:
    with pytest.raises(TypeError):
        _ = Money(1) < other


# -------------------------------------------------------------------------- pydantic
# Money owns its pydantic schema, so a plain ``Money`` annotation is enough in any
# model. One wire format: {"amount": "<whole VND>", "currency": "VND"}.


class _Priced(BaseModel):
    price: Money


@pytest.mark.parametrize(
    "raw",
    [
        5_000_000,
        "5000000",
        Decimal(5_000_000),
        Money(5_000_000),
        {"amount": "5000000", "currency": "VND"},
        {"amount": 5_000_000},  # currency defaults to VND
    ],
)
def test_pydantic_accepts_every_input_shape(raw: Any) -> None:
    assert _Priced.model_validate({"price": raw}).price == Money(5_000_000)


@pytest.mark.parametrize(
    "raw",
    [1.5, 1000.0, True, None, "abc", -1, {"currency": "VND"}, {"amount": "1", "currency": "USD"}],
)
def test_pydantic_turns_every_bad_input_into_a_validation_error(raw: Any) -> None:
    # Never a raw TypeError / KeyError: seed loading reports these as validation problems.
    with pytest.raises(ValidationError):
        _Priced.model_validate({"price": raw})


def test_pydantic_dumps_the_single_dict_format() -> None:
    m = _Priced(price=Money(5_000_000))
    expected = {"amount": "5000000", "currency": "VND"}
    assert m.model_dump() == {"price": expected}
    assert json.loads(m.model_dump_json()) == {"price": expected}


def test_pydantic_json_round_trip() -> None:
    m = _Priced(price=Money(1_200_000))
    assert _Priced.model_validate_json(m.model_dump_json()) == m


def test_pydantic_json_schema_describes_the_dict_format() -> None:
    schema = TypeAdapter(Money).json_schema(mode="serialization")
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"amount", "currency"}
    assert schema["properties"]["amount"]["type"] == "string"
