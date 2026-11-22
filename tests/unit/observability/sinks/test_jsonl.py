import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from opsdesk.core.ids import EventId, RequestId, ThreadId
from opsdesk.observability.events import Event, EventKind
from opsdesk.observability.sinks.jsonl import JsonlSink


def _event(seq: int, ts: datetime, text: str = "Xin chào, máy in bị kẹt giấy") -> Event:
    return Event(
        seq=seq,
        event_id=EventId(f"evt_{seq}"),
        ts=ts,
        request_id=RequestId("req_1"),
        thread_id=ThreadId("thr_1"),
        kind=EventKind.TOKEN,
        payload={"text": text, "agent": "helpdesk"},
    )


T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


async def test_writes_one_valid_json_line_per_event(tmp_path: Path) -> None:
    sink = JsonlSink(tmp_path / "events")  # directory does not exist yet
    events = [_event(i, T0) for i in range(3)]
    for e in events:
        await sink.handle(e)

    path = tmp_path / "events" / "2026-03-01.jsonl"
    raw = path.read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r\n" not in raw  # LF on Windows too
    lines = raw.decode("utf-8").splitlines()
    assert [Event.model_validate_json(line) for line in lines] == events


async def test_vietnamese_text_is_stored_as_utf8(tmp_path: Path) -> None:
    sink = JsonlSink(tmp_path)
    await sink.handle(_event(0, T0, "Tiếng Việt có dấu: ắ ổ ữ đ"))
    line = (tmp_path / "2026-03-01.jsonl").read_text(encoding="utf-8")
    assert json.loads(line)["payload"]["text"] == "Tiếng Việt có dấu: ắ ổ ữ đ"


async def test_file_is_chosen_by_the_events_utc_date(tmp_path: Path) -> None:
    sink = JsonlSink(tmp_path)
    await sink.handle(_event(0, datetime(2026, 3, 1, 23, 59, 59, tzinfo=UTC)))
    await sink.handle(_event(1, datetime(2026, 3, 2, 0, 0, 1, tzinfo=UTC)))
    files = await asyncio.to_thread(lambda: sorted(p.name for p in tmp_path.iterdir()))
    assert files == ["2026-03-01.jsonl", "2026-03-02.jsonl"]


async def test_appends_across_sink_instances(tmp_path: Path) -> None:
    await JsonlSink(tmp_path).handle(_event(0, T0))
    await JsonlSink(tmp_path).handle(_event(1, T0))
    assert len((tmp_path / "2026-03-01.jsonl").read_text(encoding="utf-8").splitlines()) == 2


async def test_concurrent_writes_do_not_interleave(tmp_path: Path) -> None:
    sink = JsonlSink(tmp_path)
    long_text = "x" * 20_000  # big lines make interleaving visible if the lock is missing
    await asyncio.gather(*(sink.handle(_event(i, T0, long_text)) for i in range(30)))
    lines = (tmp_path / "2026-03-01.jsonl").read_text(encoding="utf-8").splitlines()
    assert sorted(Event.model_validate_json(line).seq for line in lines) == list(range(30))


async def test_file_is_closed_after_each_write(tmp_path: Path) -> None:
    # On Windows an open file cannot be deleted; this fails there if a handle leaks.
    sink = JsonlSink(tmp_path)
    await sink.handle(_event(0, T0))
    path = tmp_path / "2026-03-01.jsonl"
    path.unlink()
    assert not path.exists()
