import pytest

from opsdesk.domain.errors import DomainError, InvalidIdentifier
from opsdesk.domain.ids import TicketId, parse_ticket_id


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("T-0002", "T-0002"), ("t-0002", "T-0002"), ("  T-0010\n", "T-0010")],
)
def test_valid_ticket_ids_are_normalised(raw: str, expected: str) -> None:
    assert parse_ticket_id(raw) == TicketId(expected)


@pytest.mark.parametrize(
    "raw",
    [
        "abc",
        "",
        "T-2",
        "T-00002",
        "T0002",
        "X-0002",
        "T-000a",
        "T-0002; DROP TABLE",
        "T-٠٠٠٢",  # Arabic-Indic digits: \d would accept them
    ],
)
def test_malformed_ticket_ids_raise_invalid_identifier(raw: str) -> None:
    with pytest.raises(InvalidIdentifier) as info:
        parse_ticket_id(raw)
    assert info.value.kind == "ticket"


def test_invalid_identifier_is_a_domain_error() -> None:
    # So the tool wrapper maps it to ``invalid`` instead of letting it crash the run.
    assert issubclass(InvalidIdentifier, DomainError)
