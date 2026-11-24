"""``list_my_devices`` stub (M05 §5.2, decision D8): data, filtering, and the tool."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from opsdesk.domain.ids import EmployeeId, TenantId
from opsdesk.observability.events import EventKind
from opsdesk.tools.stubs._loader import StubDataError
from opsdesk.tools.stubs.devices import (
    DeviceRecord,
    DeviceView,
    devices_assigned_to,
    load_devices,
    make_list_my_devices,
)
from support import CallTool, MakeCaller

REAL_STUBS = Path(__file__).resolve().parents[3] / "data" / "stubs"
ACME, GLOBEX = TenantId("acme"), TenantId("globex")


@pytest.fixture(scope="module")
def devices() -> tuple[DeviceRecord, ...]:
    return load_devices(REAL_STUBS)


def _tags(records: list[DeviceRecord]) -> list[str]:
    return [d.asset_tag for d in records]


def test_real_device_file_loads_with_unique_tags(devices: tuple[DeviceRecord, ...]) -> None:
    tags = [d.asset_tag for d in devices]
    assert len(set(tags)) == len(tags)
    assert any(d.tenant_id == GLOBEX for d in devices)  # tenant-isolation fixture


def test_an_gets_only_her_own_devices(devices: tuple[DeviceRecord, ...]) -> None:
    assert _tags(devices_assigned_to(devices, ACME, EmployeeId("E-001"))) == [
        "LAP-1042",
        "MON-2201",
    ]


def test_employee_without_devices_gets_nothing(devices: tuple[DeviceRecord, ...]) -> None:
    assert devices_assigned_to(devices, ACME, EmployeeId("E-004")) == []


def test_same_employee_id_in_another_tenant_matches_nothing(
    devices: tuple[DeviceRecord, ...],
) -> None:
    # Tenant first: G-001's laptop is invisible from acme, and E-001 does not exist in
    # globex.
    assert devices_assigned_to(devices, ACME, EmployeeId("G-001")) == []
    assert devices_assigned_to(devices, GLOBEX, EmployeeId("E-001")) == []


def test_shared_devices_are_nobodys_own(devices: tuple[DeviceRecord, ...]) -> None:
    printer = next(d for d in devices if d.asset_tag == "PRN-0301")
    assert printer.assigned_to is None
    assert all(
        "PRN-0301" not in _tags(devices_assigned_to(devices, ACME, EmployeeId(e)))
        for e in ("E-001", "E-002", "E-003", "E-005", "E-006")
    )


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2027, 3, 30), True),
        (date(2027, 3, 31), True),  # the last day is still covered
        (date(2027, 4, 1), False),
    ],
)
def test_under_warranty_is_computed_from_the_given_date(
    devices: tuple[DeviceRecord, ...], today: date, expected: bool
) -> None:
    laptop = next(d for d in devices if d.asset_tag == "LAP-1042")  # warranty_end 2027-03-31
    view = DeviceView.of(laptop, today=today)
    assert view.under_warranty is expected
    assert "tenant_id" not in view.model_dump() and "assigned_to" not in view.model_dump()


def test_unknown_device_type_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "devices.yaml").write_text(
        "- asset_tag: X-1\n  tenant_id: acme\n  assigned_to: E-001\n  type: toaster\n"
        "  model: M\n  warranty_end: 2027-01-01\n",
        encoding="utf-8",
    )
    with pytest.raises(StubDataError, match="type"):
        load_devices(tmp_path)


# ------------------------------------------------------- the tool, through the harness


async def test_an_gets_her_devices_with_warranty_computed_from_the_clock(
    devices: tuple[DeviceRecord, ...], make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")  # plain employee: has asset:read_own (D8)
    an.clock.current = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)

    result = await call_tool(make_list_my_devices(devices), {}, an.tool_context)

    assert result["status"] == "ok"
    warranty = {d["asset_tag"]: d["under_warranty"] for d in result["data"]}
    assert warranty == {"LAP-1042": True, "MON-2201": False}
    assert [e.payload["status"] for e in an.events(EventKind.TOOL_FINISHED)] == ["ok"]


async def test_employee_without_devices_gets_empty(
    devices: tuple[DeviceRecord, ...], make_caller: MakeCaller, call_tool: CallTool
) -> None:
    dung = await make_caller("E-004")
    result = await call_tool(make_list_my_devices(devices), {}, dung.tool_context)

    assert result["status"] == "empty"


async def test_globex_user_sees_only_globex_devices(
    devices: tuple[DeviceRecord, ...], make_caller: MakeCaller, call_tool: CallTool
) -> None:
    minh = await make_caller("G-001", "globex")
    result = await call_tool(make_list_my_devices(devices), {}, minh.tool_context)

    assert [d["asset_tag"] for d in result["data"]] == ["G-LAP-0007"]


async def test_type_filter(
    devices: tuple[DeviceRecord, ...], make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    result = await call_tool(make_list_my_devices(devices), {"type": "laptop"}, an.tool_context)

    assert [d["asset_tag"] for d in result["data"]] == ["LAP-1042"]


def test_the_model_cannot_choose_whose_devices() -> None:
    tool = make_list_my_devices(())
    # Only the type filter: no employee id, no tenant (identity comes from the server).
    assert set(tool.args) == {"type"}
