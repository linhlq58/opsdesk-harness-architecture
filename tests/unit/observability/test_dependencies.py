"""``opsdesk.observability`` depends only on ``opsdesk.core`` (M02 §6.1).

``.importlinter`` would allow observability → security (they share a ``:`` layer).
This is a design decision, not an architecture rule: events need correlation ids, not
identity, so the event system stays reusable by ingestion, MCP and eval without the
security model. Changing it into a lint rule would need an ADR.
"""

import ast
from pathlib import Path

import opsdesk.observability

PACKAGE_DIR = Path(opsdesk.observability.__file__).parent
ALLOWED_PREFIXES = ("opsdesk.core", "opsdesk.observability")


def _opsdesk_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return {name for name in found if name.split(".")[0] == "opsdesk"}


def test_observability_imports_only_core() -> None:
    files = sorted(PACKAGE_DIR.rglob("*.py"))
    assert files, "no source files found"
    violations = {
        f"{path.relative_to(PACKAGE_DIR)}: {name}"
        for path in files
        for name in _opsdesk_imports(path)
        if not name.startswith(ALLOWED_PREFIXES)
    }
    assert not violations, sorted(violations)
