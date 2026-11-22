"""Seed loader: validation, atomic rebuild, idempotency, and fitness of the real seed."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from opsdesk.core.money import Money
from opsdesk.domain.decisions import AccessOutcome, ReasonCode
from opsdesk.domain.models import AccessKind, Employee, SoftwareItem, Ticket
from opsdesk.domain.policies.access import AccessRules, evaluate_access_request
from opsdesk.domain.policies.approval import can_decide
from opsdesk.domain.policies.visibility import can_view_ticket
from opsdesk.persistence.memory import in_memory_repositories
from opsdesk.persistence.seed import SeedError, load_seed, main, seed_database, write_seed

REAL_SEED = Path(__file__).resolve().parents[2] / "data" / "seed"


@pytest.fixture
def seed_dir(tmp_path: Path) -> Path:
    """A private, editable copy of the real seed directory."""
    return Path(shutil.copytree(REAL_SEED, tmp_path / "seed"))


def _append(path: Path, text: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def _dump(db: Path) -> dict[str, list[tuple[object, ...]]]:
    """Every row of every table, sorted, to compare two databases."""
    with sqlite3.connect(db) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        result = {t: sorted(conn.execute(f"SELECT * FROM {t}").fetchall()) for t in tables}
    conn.close()  # the context manager commits but does not close; Windows needs a close
    return result


# ---------------------------------------------------------------------- real seed


def test_real_seed_is_valid_and_complete() -> None:
    data = load_seed(REAL_SEED)
    assert len(data.tenants) == 2
    assert len(data.software) == 8
    assert len(data.employees) == 8
    assert len(data.tickets) == 10
    assert len(data.access_requests) == 5
    assert {t.status.value for t in data.tickets} == {
        "open",
        "in_progress",
        "waiting_on_user",
        "resolved",
        "closed",
    }


async def test_real_seed_supports_the_policy_cases() -> None:
    """The personas exist to exercise M01 §3; prove they still do."""
    repos = in_memory_repositories()
    await write_seed(repos, load_seed(REAL_SEED))

    async def emp(tenant: str, emp_id: str) -> Employee:
        found = await repos.employees.get(tenant, emp_id)  # type: ignore[arg-type]
        assert found is not None
        return found

    async def ticket(tenant: str, ticket_id: str) -> Ticket:
        found = await repos.tickets.get(tenant, ticket_id)  # type: ignore[arg-type]
        assert found is not None
        return found

    async def sw(sw_id: str) -> SoftwareItem:
        found = await repos.software.get(sw_id)  # type: ignore[arg-type]
        assert found is not None
        return found

    an, chi, minh = (
        await emp("acme", "E-001"),
        await emp("acme", "E-003"),
        await emp("globex", "G-001"),
    )
    khanh, lan = await emp("acme", "E-006"), await emp("acme", "E-007")
    t1 = await ticket("acme", "T-0001")

    assert can_view_ticket(minh, t1).reason is ReasonCode.CROSS_TENANT  # V1
    assert can_view_ticket(an, t1).allowed  # V2
    assert can_view_ticket(chi, t1).reason is ReasonCode.NOT_OWNER  # V6

    rules = AccessRules(licence_review_threshold=Money(5_000_000))
    figma = evaluate_access_request(an, AccessKind.SOFTWARE_LICENCE, await sw("SW-FIGMA"), rules)
    assert figma.reasons == (ReasonCode.HIGH_COST,)  # A2
    powerbi = evaluate_access_request(
        an, AccessKind.SOFTWARE_LICENCE, await sw("SW-POWERBI"), rules
    )
    assert powerbi.outcome is AccessOutcome.REJECT  # A6

    khanhs_request = await repos.access_requests.get("acme", "AR-003")  # type: ignore[arg-type]
    assert khanhs_request is not None
    assert can_decide(khanh, khanhs_request).reason is ReasonCode.SELF_APPROVAL  # P4
    assert can_decide(lan, khanhs_request).allowed
    assert len(await repos.access_requests.list_pending("acme")) == 3  # type: ignore[arg-type]


# --------------------------------------------------------------------- validation


def test_invalid_record_is_reported_with_file_index_and_field(seed_dir: Path) -> None:
    _append(seed_dir / "software.yaml", "\n- id: SW-BAD\n  name: Bad\n  annual_cost: 1.5\n")
    with pytest.raises(SeedError) as exc_info:
        load_seed(seed_dir)
    (problem,) = exc_info.value.problems
    assert "software.yaml[8] (id=SW-BAD)" in problem
    assert "annual_cost" in problem
    assert "float" in problem


def test_all_problems_are_reported_at_once(seed_dir: Path) -> None:
    _append(seed_dir / "tenants.yaml", "\n- id: acme\n  name: Acme again\n")  # duplicate
    _append(
        seed_dir / "employees.yaml",
        "\n- id: E-999\n  tenant_id: acme\n  full_name: No Role\n  email: x@acme.example\n"
        "  department: it\n  roles: [it_staff]\n",  # missing 'employee' role
    )
    with pytest.raises(SeedError) as exc_info:
        load_seed(seed_dir)
    problems = exc_info.value.problems
    assert any("duplicate id acme" in p for p in problems)
    assert any("E-999" in p and "employee" in p for p in problems)


@pytest.mark.parametrize(
    ("file", "find", "replace", "expected"),
    [
        ("tickets.yaml", "reporter_id: E-002", "reporter_id: E-404", "reporter E-404"),
        # G-001 exists, but in Globex: an Acme ticket must not point to them.
        ("tickets.yaml", "assignee_id: E-005", "assignee_id: G-001", "assignee G-001"),
        ("employees.yaml", "tenant_id: globex", "tenant_id: initech", "unknown tenant initech"),
        ("employees.yaml", "[SW-VSCODE, SW-SLACK]", "[SW-VSCODE, SW-NOPE]", "SW-NOPE"),
        ("access_requests.yaml", "software_id: SW-FIGMA", "software_id: SW-NOPE", "SW-NOPE"),
        ("access_requests.yaml", "decided_by: E-006", "decided_by: E-404", "decided_by E-404"),
    ],
)
def test_broken_references_are_reported(
    seed_dir: Path, file: str, find: str, replace: str, expected: str
) -> None:
    path = seed_dir / file
    text = path.read_text(encoding="utf-8")
    assert find in text, "test setup: pattern not found in seed file"
    path.write_text(text.replace(find, replace, 1), encoding="utf-8")
    with pytest.raises(SeedError, match=expected):
        load_seed(seed_dir)


def test_missing_file_and_wrong_shape_are_reported(seed_dir: Path) -> None:
    (seed_dir / "tickets.yaml").unlink()
    (seed_dir / "tenants.yaml").write_text("id: acme\n", encoding="utf-8")
    with pytest.raises(SeedError) as exc_info:
        load_seed(seed_dir)
    problems = exc_info.value.problems
    assert "tickets.yaml: file not found" in problems
    assert "tenants.yaml: expected a list of records" in problems


# ---------------------------------------------------------------- seed_database


async def test_seeding_twice_gives_identical_database(tmp_path: Path) -> None:
    db = tmp_path / "var" / "opsdesk.db"
    await seed_database(REAL_SEED, db)
    first = _dump(db)
    await seed_database(REAL_SEED, db)
    assert _dump(db) == first
    assert len(first["tickets"]) == 10


async def test_records_removed_from_yaml_disappear(seed_dir: Path, tmp_path: Path) -> None:
    db = tmp_path / "opsdesk.db"
    await seed_database(seed_dir, db)
    # Drop the last ticket (T-0010, the Globex one) from the YAML and reseed.
    path = seed_dir / "tickets.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text[: text.index("- id: T-0010")], encoding="utf-8")
    await seed_database(seed_dir, db)
    assert len(_dump(db)["tickets"]) == 9


async def test_invalid_seed_leaves_existing_database_untouched(
    seed_dir: Path, tmp_path: Path
) -> None:
    db = tmp_path / "opsdesk.db"
    await seed_database(seed_dir, db)
    before = _dump(db)
    _append(seed_dir / "software.yaml", "\n- id: SW-BAD\n  name: Bad\n  annual_cost: -1\n")
    with pytest.raises(SeedError):
        await seed_database(seed_dir, db)
    assert _dump(db) == before
    assert not (tmp_path / "opsdesk.db.tmp").exists()


async def test_invalid_seed_creates_no_database(seed_dir: Path, tmp_path: Path) -> None:
    (seed_dir / "tenants.yaml").write_text("- {}\n", encoding="utf-8")
    db = tmp_path / "opsdesk.db"
    with pytest.raises(SeedError):
        await seed_database(seed_dir, db)
    assert not db.exists()


# ---------------------------------------------------------------------------- CLI


def test_cli_success_and_failure_exit_codes(seed_dir: Path, tmp_path: Path) -> None:
    db = tmp_path / "cli.db"
    assert main(["--seed-dir", str(seed_dir), "--db", str(db)]) == 0
    assert db.exists()

    (seed_dir / "tenants.yaml").write_text("- {}\n", encoding="utf-8")
    assert main(["--seed-dir", str(seed_dir), "--db", str(db)]) == 1
