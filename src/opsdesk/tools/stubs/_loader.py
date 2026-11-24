"""Load one stub data file (a YAML list of records) into validated models.

Fail fast and say everything at once, like the seed loader: every invalid record is
listed in one ``StubDataError``, raised at startup.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

DEFAULT_STUB_DIR = Path("data") / "stubs"


class StubDataError(Exception):
    """A stub data file is missing or invalid. ``problems`` lists every issue."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__(f"{len(problems)} stub data problem(s):\n  - " + "\n  - ".join(problems))


def load_records[M: BaseModel](path: Path, model: type[M]) -> tuple[M, ...]:
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise StubDataError([f"{path.name}: file not found"]) from None
    except yaml.YAMLError as exc:
        raise StubDataError([f"{path.name}: invalid YAML: {exc}"]) from None

    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise StubDataError([f"{path.name}: expected a list of records"])

    items: list[M] = []
    problems: list[str] = []
    for index, record in enumerate(raw):  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        try:
            items.append(model.model_validate(record))
        except ValidationError as exc:
            for err in exc.errors():
                field = ".".join(str(part) for part in err["loc"]) or "<record>"
                problems.append(f"{path.name}[{index}]: {field}: {err['msg']}")
    if problems:
        raise StubDataError(problems)
    return tuple(items)
