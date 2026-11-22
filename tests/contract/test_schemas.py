"""JSON-schema snapshots of the public contracts (M02 §8).

The UI, stored JSONL files and eval datasets depend on the exact shape of ``Event``,
its payloads and ``ToolResult``. This test compares the current JSON schema of each
against a committed file in ``tests/contract/snapshots/``. Any change fails until the
snapshots are regenerated **deliberately**:

    uv run poe snapshots

and the diff is reviewed in the commit. Pair it with the versioning rule in
``observability/events.py``: adding a kind or an optional field is a v1 change;
renaming/removing a field or changing a type needs ``opsdesk.event.v2``.

Schemas are taken in ``serialization`` mode: they describe the JSON that consumers
actually receive. A pydantic upgrade can also change the generated schema; then the
diff shows it and you regenerate after checking nothing meaningful moved.
"""

import json
import os
from pathlib import Path

import pytest
from pydantic import BaseModel, JsonValue

from opsdesk.core.result import ToolResult
from opsdesk.observability.events import PAYLOAD_MODELS, Event

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
UPDATE = os.environ.get("OPSDESK_UPDATE_SNAPSHOTS") == "1"

CONTRACTS: dict[str, type[BaseModel]] = {
    "event": Event,
    "tool_result": ToolResult[dict[str, JsonValue]],
    **{f"payload.{kind.value}": model for kind, model in PAYLOAD_MODELS.items()},
}


def _render(model: type[BaseModel]) -> str:
    schema = model.model_json_schema(mode="serialization")
    # sort_keys + fixed indent: the file only changes when the schema does.
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_schema_matches_snapshot(name: str) -> None:
    path = SNAPSHOT_DIR / f"{name}.json"
    current = _render(CONTRACTS[name])

    if UPDATE:
        SNAPSHOT_DIR.mkdir(exist_ok=True)
        path.write_text(current, encoding="utf-8", newline="\n")
        return

    assert path.exists(), f"missing snapshot {path.name}: run `uv run poe snapshots`"
    expected = path.read_text(encoding="utf-8")
    assert current == expected, (
        f"the JSON schema of {name!r} changed. If intended, check the versioning rule "
        "(events.py), run `uv run poe snapshots` and review the diff in the commit."
    )


def test_no_stale_snapshots() -> None:
    # A removed contract (e.g. a payload model deleted) must not leave a file behind.
    if UPDATE:
        for path in SNAPSHOT_DIR.glob("*.json"):
            if path.stem not in CONTRACTS:
                path.unlink()
    on_disk = {path.stem for path in SNAPSHOT_DIR.glob("*.json")}
    assert on_disk == set(CONTRACTS)
