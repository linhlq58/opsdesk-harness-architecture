import re

import pytest

from opsdesk.core.ids import new_event_id, new_request_id, new_thread_id


@pytest.mark.parametrize(
    ("factory", "prefix"),
    [(new_request_id, "req"), (new_thread_id, "thr"), (new_event_id, "evt")],
)
def test_ids_are_prefixed_uuid_hex(factory: object, prefix: str) -> None:
    value = factory()  # type: ignore[operator]
    assert re.fullmatch(rf"{prefix}_[0-9a-f]{{32}}", value)


def test_ids_are_unique() -> None:
    assert len({new_event_id() for _ in range(1000)}) == 1000
