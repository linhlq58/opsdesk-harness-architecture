"""Money value object.

Never use ``float`` for money: ``0.1 + 0.2 != 0.3``. ``Money`` wraps a ``Decimal`` and
a currency, so adding two amounts in different currencies is an error instead of a
silently wrong number (this matters from M07, when provider prices arrive in USD).

Only VND exists for now. VND has no minor unit, so amounts are whole numbers.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import total_ordering
from typing import Literal, Self

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
