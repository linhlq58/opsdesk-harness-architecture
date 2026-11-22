"""The one shape every tool answers with, and the shared error taxonomy.

Every tool returns a ``ToolResult``: never a bare value, an ad-hoc dict or a raised
exception. Its ``status`` belongs to exactly one ``ErrorClass``, and that class alone
decides what the rest of the harness does:

=============  =======================  =========  ===========================================
ErrorClass     statuses                 retry?     meaning
=============  =======================  =========  ===========================================
``none``       ``ok``, ``empty``        —          success (``empty`` = "nothing to show")
``business``   ``not_found``,           no         the request is wrong; the model should
               ``invalid``                         rephrase or ask the user
``policy``     ``denied``               no         not allowed; never retry, never work around
``transient``  ``unavailable``,         yes        infrastructure failed; retrying may help
               ``timeout``
=============  =======================  =========  ===========================================

The mapping is data (``_ERROR_CLASS``), so retries (M13), gates, the UI and evaluation
all read the same table instead of each guessing from a status name.

``safe_message`` is written *for the model* (and the UI): it never contains exception
text, stack traces, SQL, file paths or another tenant's data. ``error_code`` is for
machines: logs, evals, metrics (usually a ``ReasonCode`` value).
"""

from collections.abc import Sized
from enum import StrEnum
from typing import Generic, Never, Self, TypeVar

from pydantic import BaseModel, Field, model_validator


class ErrorClass(StrEnum):
    NONE = "none"
    BUSINESS = "business"
    POLICY = "policy"
    TRANSIENT = "transient"


class ToolStatus(StrEnum):
    OK = "ok"
    EMPTY = "empty"
    NOT_FOUND = "not_found"
    INVALID = "invalid"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"

    @property
    def error_class(self) -> ErrorClass:
        return _ERROR_CLASS[self]

    @property
    def is_error(self) -> bool:
        return self.error_class is not ErrorClass.NONE

    @property
    def retryable(self) -> bool:
        return self.error_class is ErrorClass.TRANSIENT


_ERROR_CLASS: dict[ToolStatus, ErrorClass] = {
    ToolStatus.OK: ErrorClass.NONE,
    ToolStatus.EMPTY: ErrorClass.NONE,
    ToolStatus.NOT_FOUND: ErrorClass.BUSINESS,
    ToolStatus.INVALID: ErrorClass.BUSINESS,
    ToolStatus.DENIED: ErrorClass.POLICY,
    ToolStatus.UNAVAILABLE: ErrorClass.TRANSIENT,
    ToolStatus.TIMEOUT: ErrorClass.TRANSIENT,
}


# Covariant: ToolResult[Never] (an error) is usable wherever ToolResult[Ticket] is expected.
# PEP 695 syntax cannot declare variance, and pyright infers pydantic fields as invariant.
T_co = TypeVar("T_co", covariant=True)


class ToolResult(BaseModel, Generic[T_co], frozen=True, extra="forbid"):  # noqa: UP046
    """What a tool returns. Build it with the constructors, not ``ToolResult(...)``.

    >>> ToolResult.ok(ticket)
    >>> ToolResult.empty()
    >>> ToolResult.denied("You can only view your own tickets.", "not_owner")

    Invariants (checked on every construction, including ``model_validate``):

    * ``ok``    → ``data`` is set; no ``safe_message``, no ``error_code``.
    * ``empty`` → ``data`` is ``None`` or an empty collection; no ``error_code``.
    * errors    → ``data`` is ``None``; ``safe_message`` and ``error_code`` both set.
    """

    status: ToolStatus
    data: T_co | None = None
    safe_message: str | None = Field(default=None, min_length=1)
    error_code: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        match self.status:
            case ToolStatus.OK:
                if self.data is None:
                    raise ValueError("ok requires data (use empty() for 'nothing found')")
                if self.safe_message is not None or self.error_code is not None:
                    raise ValueError("ok must not carry safe_message or error_code")
            case ToolStatus.EMPTY:
                if self.data is not None and not (isinstance(self.data, Sized) and not self.data):
                    raise ValueError("empty allows only data=None or an empty collection")
                if self.error_code is not None:
                    raise ValueError("empty is a success and must not carry an error_code")
            case _:
                if self.data is not None:
                    raise ValueError(f"{self.status} must not carry data")
                if self.safe_message is None or self.error_code is None:
                    raise ValueError(f"{self.status} requires safe_message and error_code")
        return self

    # ---------------------------------------------------------------- constructors
    # Error constructors return ``ToolResult[Never]``: an error has no data, and
    # ``Never`` is assignable to every ``T``, so ``return ToolResult.denied(...)``
    # type-checks inside a function declared to return ``ToolResult[Ticket]``.

    @classmethod
    def ok[U](cls, data: U) -> "ToolResult[U]":
        return ToolResult[U](status=ToolStatus.OK, data=data)

    @classmethod
    def empty(cls, safe_message: str | None = None) -> "ToolResult[Never]":
        return _error_free(ToolStatus.EMPTY, safe_message)

    @classmethod
    def not_found(cls, safe_message: str, error_code: str) -> "ToolResult[Never]":
        return _failure(ToolStatus.NOT_FOUND, safe_message, error_code)

    @classmethod
    def invalid(cls, safe_message: str, error_code: str) -> "ToolResult[Never]":
        return _failure(ToolStatus.INVALID, safe_message, error_code)

    @classmethod
    def denied(cls, safe_message: str, error_code: str) -> "ToolResult[Never]":
        return _failure(ToolStatus.DENIED, safe_message, error_code)

    @classmethod
    def unavailable(cls, safe_message: str, error_code: str) -> "ToolResult[Never]":
        return _failure(ToolStatus.UNAVAILABLE, safe_message, error_code)

    @classmethod
    def timeout(cls, safe_message: str, error_code: str) -> "ToolResult[Never]":
        return _failure(ToolStatus.TIMEOUT, safe_message, error_code)


def _error_free(status: ToolStatus, safe_message: str | None) -> ToolResult[Never]:
    return ToolResult[Never](status=status, safe_message=safe_message)


def _failure(status: ToolStatus, safe_message: str, error_code: str) -> ToolResult[Never]:
    return ToolResult[Never](status=status, safe_message=safe_message, error_code=error_code)
