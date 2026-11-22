"""Money value object.

Never use ``float`` for money: ``0.1 + 0.2 != 0.3``. ``Money`` wraps a ``Decimal`` and
a currency, so adding two amounts in different currencies is an error instead of a
silently wrong number (this matters from M07, when provider prices arrive in USD).

Only VND exists for now. VND has no minor unit, so amounts are whole numbers.

Pydantic: ``Money`` owns its schema (``__get_pydantic_core_schema__``), so any model field
typed ``Money`` behaves the same everywhere. There is exactly one wire format:

* serialise → ``{"amount": "5000000", "currency": "VND"}`` (amount as a string, so JSON
  never turns it into a float; currency included, because M07 adds USD prices);
* parse ← that dict, a bare ``int`` / ``str`` / ``Decimal`` amount (VND, e.g. seed YAML
  ``annual_cost: 5000000``), or a ``Money``.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import total_ordering
from typing import Any, Literal, Self

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

type Currency = Literal["VND"]
_SUPPORTED_CURRENCIES: frozenset[str] = frozenset({"VND"})


@total_ordering
@dataclass(frozen=True, slots=True, init=False)
class Money:
    """A non-negative, whole amount of VND.

    >>> Money(1_200_000) + Money("300000")
    Money(amount=Decimal('1500000'), currency='VND')
    """

    amount: Decimal
    currency: Currency

    def __init__(self, amount: int | str | Decimal, currency: Currency = "VND") -> None:
        value = _to_decimal(amount)
        if not value.is_finite():
            raise ValueError(f"amount must be a finite number, got {amount!r}")
        if value != value.to_integral_value():
            raise ValueError(f"VND has no minor unit, amount must be whole: {amount!r}")
        if value < 0:
            raise ValueError(f"amount must not be negative: {amount!r}")
        if currency not in _SUPPORTED_CURRENCIES:
            raise ValueError(f"unsupported currency: {currency!r}")

        # The dataclass is frozen, so normal assignment raises FrozenInstanceError.
        # object.__setattr__ is the documented way to set fields during construction.
        # quantize(1) normalises Decimal("1E+3") / Decimal("1000.00") to Decimal("1000").
        object.__setattr__(self, "amount", value.quantize(Decimal(1)))
        object.__setattr__(self, "currency", currency)

    @classmethod
    def zero(cls, currency: Currency = "VND") -> Self:
        return cls(0, currency)

    def __add__(self, other: object) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return self.amount < other.amount

    def _require_same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")

    # -------------------------------------------------------------------- pydantic

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_plain_validator_function(
            _parse_money,
            # Describes the accepted input for JSON schema (tool schemas, snapshots).
            json_schema_input_schema=_MONEY_JSON_SCHEMA,
            serialization=core_schema.plain_serializer_function_ser_schema(
                _dump_money, return_schema=_MONEY_JSON_SCHEMA
            ),
        )


_MONEY_JSON_SCHEMA = core_schema.typed_dict_schema(
    {
        "amount": core_schema.typed_dict_field(core_schema.str_schema()),
        "currency": core_schema.typed_dict_field(core_schema.literal_schema(["VND"])),
    }
)


def _parse_money(value: object) -> Money:
    """Pydantic validator: accept a ``Money``, a bare VND amount or the dict form.

    Pydantic only turns ``ValueError`` into a ``ValidationError``. ``Money`` raises
    ``TypeError`` for floats and other bad types, so those are re-raised as
    ``ValueError``; otherwise a bad seed file would crash with a raw traceback instead
    of a validation report.
    """
    if isinstance(value, Money):
        return value
    try:
        if isinstance(value, dict):
            data: dict[str, Any] = value  # pyright: ignore[reportUnknownVariableType]
            return Money(data["amount"], data.get("currency", "VND"))
        return Money(value)  # pyright: ignore[reportArgumentType]  (checked at runtime)
    except (TypeError, KeyError) as exc:
        raise ValueError(str(exc)) from exc


def _dump_money(value: Money) -> dict[str, str]:
    # Amount as a string: exact in JSON (no float) and readable in SQLite / YAML.
    return {"amount": str(value.amount), "currency": value.currency}


def _to_decimal(amount: object) -> Decimal:
    """Convert a constructor argument to ``Decimal``, rejecting unsafe types.

    Takes ``object`` (not the declared union) because callers without type checking
    (YAML seed data, tests) can pass anything at runtime.
    """
    # bool is a subclass of int: without this check Money(True) would be 1 VND.
    if isinstance(amount, bool):
        raise TypeError("amount must be int, str or Decimal, not bool")
    # Reject float before converting: Decimal(0.1) == 0.1000000000000000055511151231...
    if isinstance(amount, float):
        raise TypeError("amount must be int, str or Decimal, not float")
    if isinstance(amount, Decimal):
        return amount
    if isinstance(amount, int):
        return Decimal(amount)
    if isinstance(amount, str):
        try:
            return Decimal(amount.strip())
        except InvalidOperation:
            raise ValueError(f"not a number: {amount!r}") from None
    raise TypeError(f"amount must be int, str or Decimal, not {type(amount).__name__}")
