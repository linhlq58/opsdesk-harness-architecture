"""``list_my_devices``: the caller's devices from a fake inventory (M05 §5.2).
TEMPORARY until M08 replaces it with the asset system behind MCP.

Scope ``asset:read_own`` (decision D8): every employee may ask about *their own*
devices; ``asset:read`` (any device) stays IT-only. The scope is the coarse gate; the
tool limits the answer to the caller's devices:

* identity comes from the server-built ``Principal`` only: there is no employee
  argument, the devices are always the caller's (like ``list_my_tickets``);
* tenant first: a device of another tenant never matches, even with the same
  employee id;
* a shared device (``assigned_to: null``, e.g. a printer) is nobody's own device;
* ``under_warranty`` is computed from the injected clock's date, never ``date.today()``.

Tests: ``tests/unit/tools/test_stub_devices.py``.
"""

from collections.abc import Sequence
from datetime import date
from enum import StrEnum
from pathlib import Path

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from opsdesk.core.result import ToolResult
from opsdesk.domain.ids import EmployeeId, TenantId
from opsdesk.security.scopes import Scope
from opsdesk.tools.context import ToolContext
from opsdesk.tools.stubs._loader import DEFAULT_STUB_DIR, load_records
from opsdesk.tools.wrapper import harness_tool

TOOL_NAME = "list_my_devices"
_NO_DEVICES = "No device is assigned to you."


class DeviceType(StrEnum):
    LAPTOP = "laptop"
    MONITOR = "monitor"
    PHONE = "phone"
    PRINTER = "printer"


class DeviceRecord(BaseModel):
    """One record of ``data/stubs/devices.yaml``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    asset_tag: str = Field(min_length=1)
    tenant_id: TenantId
    assigned_to: EmployeeId | None
    type: DeviceType
    model: str = Field(min_length=1)
    warranty_end: date


class DeviceView(BaseModel):
    """What the model sees: no ``tenant_id`` / ``assigned_to`` (always the caller)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    asset_tag: str
    type: DeviceType
    model: str
    warranty_end: date
    under_warranty: bool  # computed here so the model does not do date arithmetic

    @classmethod
    def of(cls, device: DeviceRecord, *, today: date) -> "DeviceView":
        return cls(
            asset_tag=device.asset_tag,
            type=device.type,
            model=device.model,
            warranty_end=device.warranty_end,
            under_warranty=device.warranty_end >= today,
        )


def load_devices(stub_dir: Path = DEFAULT_STUB_DIR) -> tuple[DeviceRecord, ...]:
    return load_records(stub_dir / "devices.yaml", DeviceRecord)


def devices_assigned_to(
    devices: Sequence[DeviceRecord], tenant_id: TenantId, employee_id: EmployeeId
) -> list[DeviceRecord]:
    """The devices assigned to this employee in this tenant, in file order."""
    return [d for d in devices if d.tenant_id == tenant_id and d.assigned_to == employee_id]


class ListMyDevicesArgs(BaseModel):
    """No employee/tenant argument: whose devices is never the model's choice.

    The optional ``type`` filter is useful ("my laptop") and also keeps the schema
    non-empty, which ``harness_tool`` requires (case W7: langchain-core drops the
    injected ``runtime`` for a schema without fields).
    """

    type: DeviceType | None = Field(
        default=None, description="Only devices of this type. Omit for all devices."
    )


def make_list_my_devices(devices: Sequence[DeviceRecord]) -> BaseTool:
    """The ``list_my_devices`` tool over ``devices`` (loaded once at startup)."""
    frozen = tuple(devices)

    @harness_tool(
        name=TOOL_NAME,
        description=(
            "List the devices assigned to the current user (laptops, monitors, phones) "
            "with model, asset tag, warranty end date and whether the warranty is still "
            "valid. Use it for questions about 'my laptop', 'my devices' or warranty."
        ),
        args_schema=ListMyDevicesArgs,
        scope=Scope.ASSET_READ_OWN,
    )
    async def list_my_devices(
        ctx: ToolContext, args: ListMyDevicesArgs
    ) -> ToolResult[list[DeviceView]]:
        principal = ctx.request.principal
        mine = devices_assigned_to(frozen, principal.tenant_id, principal.user_id)
        if args.type is not None:
            mine = [d for d in mine if d.type == args.type]
        if not mine:
            return ToolResult.empty(_NO_DEVICES)
        today = ctx.clock.now().date()  # injected clock, never date.today()
        return ToolResult.ok([DeviceView.of(d, today=today) for d in mine])

    return list_my_devices
