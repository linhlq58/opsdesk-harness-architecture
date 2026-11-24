"""ThreadRegistry cases R1-R4 (M04 §5, decision D5), plus patterns (M05 §10)."""

import pytest

from opsdesk.core.ids import ThreadId
from opsdesk.orchestration.threads import Pattern, ThreadNotFound, ThreadRegistry
from support import MakeCaller

TICKET = Pattern.TICKET_AGENT


async def test_r1_owner_can_use_their_thread(make_caller: MakeCaller) -> None:
    an = (await make_caller("E-001")).request.principal
    registry = ThreadRegistry()

    thread_id = registry.create(an, TICKET)

    registry.require_owner(an, thread_id, TICKET)  # does not raise
    assert thread_id.startswith("thr_")


async def test_r2_colleague_in_the_same_tenant_is_refused(make_caller: MakeCaller) -> None:
    an = (await make_caller("E-001")).request.principal
    binh = (await make_caller("E-002")).request.principal
    registry = ThreadRegistry()
    thread_id = registry.create(an, TICKET)

    with pytest.raises(ThreadNotFound):
        registry.require_owner(binh, thread_id, TICKET)


async def test_r3_user_of_another_tenant_is_refused(make_caller: MakeCaller) -> None:
    an = (await make_caller("E-001")).request.principal
    minh = (await make_caller("G-001", "globex")).request.principal
    registry = ThreadRegistry()
    thread_id = registry.create(an, TICKET)

    with pytest.raises(ThreadNotFound):
        registry.require_owner(minh, thread_id, TICKET)


async def test_r4_unknown_thread_looks_exactly_like_a_foreign_one(
    make_caller: MakeCaller,
) -> None:
    an = (await make_caller("E-001")).request.principal
    binh = (await make_caller("E-002")).request.principal
    registry = ThreadRegistry()
    ans_thread = registry.create(an, TICKET)

    with pytest.raises(ThreadNotFound) as foreign:
        registry.require_owner(binh, ans_thread, TICKET)
    with pytest.raises(ThreadNotFound) as unknown:
        registry.require_owner(binh, ThreadId("thr_does_not_exist"), TICKET)

    assert str(foreign.value) == str(unknown.value) == "thread not found"
    assert ans_thread not in str(foreign.value)


async def test_each_thread_gets_a_new_id(make_caller: MakeCaller) -> None:
    an = (await make_caller("E-001")).request.principal
    registry = ThreadRegistry()

    assert registry.create(an, TICKET) != registry.create(an, TICKET)  # Reset = a new thread


async def test_same_user_id_in_another_tenant_is_another_owner(make_caller: MakeCaller) -> None:
    # Ownership is (tenant_id, user_id), not user_id alone.
    an = (await make_caller("E-001")).request.principal
    impostor = an.model_copy(update={"tenant_id": "globex"})
    registry = ThreadRegistry()
    thread_id = registry.create(an, TICKET)

    with pytest.raises(ThreadNotFound):
        registry.require_owner(impostor, thread_id, TICKET)


# ------------------------------------------------------------- M05: one pattern per thread


async def test_owner_using_the_thread_with_another_pattern_is_refused(
    make_caller: MakeCaller,
) -> None:
    an = (await make_caller("E-001")).request.principal
    registry = ThreadRegistry()
    ticket_thread = registry.create(an, Pattern.TICKET_AGENT)
    router_thread = registry.create(an, Pattern.ROUTER)

    registry.require_owner(an, router_thread, Pattern.ROUTER)  # does not raise
    with pytest.raises(ThreadNotFound) as wrong_pattern:
        registry.require_owner(an, ticket_thread, Pattern.ROUTER)

    # Same exception, same message as a foreign or unknown thread.
    assert str(wrong_pattern.value) == "thread not found"
