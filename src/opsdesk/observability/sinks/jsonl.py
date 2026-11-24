"""Append every event as one JSON line to ``<directory>/<YYYY-MM-DD>.jsonl``.

The "local event log, always on" (architecture §8): if LangSmith/Langfuse are down or
not configured, this file is still the evidence of what ran. Production wiring passes
``settings.var_dir / "events"``.

* The date in the file name is the UTC date of the event's ``ts`` (not "today"), so a
  run crossing midnight is split by when each event happened, and tests are
  deterministic.
* ``encoding="utf-8"`` and ``newline="\\n"``: identical bytes on Windows and Linux,
  Vietnamese text intact.
* The blocking file write runs in ``asyncio.to_thread`` so the event loop never stalls
  on disk I/O, and an ``asyncio.Lock`` keeps concurrent writes from interleaving lines.
* The file is opened and closed for every event: nothing stays open (Windows cannot
  delete an open file), and a crash loses at most the event being written.
* ``exclude_kinds`` (M04, decision D4): kinds this sink drops. The API passes
  ``{EventKind.TOKEN}``: the log records *what happened*, not the text of answers.
"""

import asyncio
from collections.abc import Iterable
from pathlib import Path

from opsdesk.observability.events import Event, EventKind


class JsonlSink:
    def __init__(
        self, directory: Path, name: str = "jsonl", *, exclude_kinds: Iterable[EventKind] = ()
    ) -> None:
        self._directory = directory
        self._name = name
        self._exclude = frozenset(exclude_kinds)
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return self._name

    def path_for(self, event: Event) -> Path:
        return self._directory / f"{event.ts.date().isoformat()}.jsonl"

    async def handle(self, event: Event) -> None:
        if event.kind in self._exclude:
            return
        line = event.model_dump_json() + "\n"
        path = self.path_for(event)
        async with self._lock:
            await asyncio.to_thread(_append_line, path, line)


def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(line)
