"""``harness_tool``: a plain async business function → a LangChain tool with the
harness around it (M03 §7).

The business function only does business:

    @harness_tool(name="get_ticket", description="...", args_schema=GetTicketArgs,
                  scope=Scope.TICKET_READ)
    async def get_ticket(ctx: ToolContext, args: GetTicketArgs) -> ToolResult[TicketView]:
        ...

The generated tool does, in this order:

1. Read ``ToolContext`` from ``runtime.context``.
2. Emit ``tool_started`` with the arguments (``RunRecorder`` redacts them) and
   ``call_id`` = the model's tool-call id (M04), which pairs it with ``tool_finished``.
3. ``require_scope(principal, scope)``; denied → ``result_from_decision(...)`` and the
   business function is **not** called.
4. Call the business function with the validated arguments model.
5. ``DomainError`` → ``result_from_domain_error(...)``. Any other exception
   propagates (decision D1-A): no ``tool_finished``, ``run_turn`` records
   ``run_finished(failed)``; the missing ``tool_finished`` is the signal.
6. Emit ``tool_finished`` with ``status``, ``error_code``, ``duration_ms``
   (``time.perf_counter``: a duration, not a business timestamp) and a short ``summary``.
7. Return the whole ``ToolResult`` as JSON to the model (decision D2-A).

Argument *format* checks live inside the tool, not in ``args_schema`` (decision D4-B):
if ``args_schema`` rejects a value, LangChain answers the model with its own error text
before this wrapper runs, so no events and no ``ToolResult``.

``args_schema`` must declare at least one field (M05): langchain-core 1.8.4
(``BaseTool._to_args_and_kwargs``) calls a tool whose schema has no fields with no
arguments at all, dropping the injected ``runtime``, so the tool would fail on its first
call with ``TypeError: _run() missing 'runtime'``. The decorator rejects such a schema
when the tool is defined (import time), with a message that says why.

Tests: ``tests/unit/tools/test_wrapper.py`` (cases W1-W7).
Docs: https://docs.langchain.com/oss/python/langchain/tools
"""

import time
from collections.abc import Awaitable, Callable, Sized
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from opsdesk.core.result import ToolResult
from opsdesk.domain.errors import DomainError
from opsdesk.observability.events import EventKind
from opsdesk.security.authz import require_scope
from opsdesk.security.scopes import Scope
from opsdesk.tools.context import ToolContext
from opsdesk.tools.taxonomy import result_from_decision, result_from_domain_error

type ToolFn[A: BaseModel, T] = Callable[[ToolContext, A], Awaitable[ToolResult[T]]]


def harness_tool[A: BaseModel, T](
    *, name: str, description: str, args_schema: type[A], scope: Scope
) -> Callable[[ToolFn[A, T]], BaseTool]:
    """Decorator factory: see the module docstring for what the generated tool does."""

    # W7: fail fast at definition time instead of a TypeError on the first call.
    if not args_schema.model_fields:
        raise TypeError(
            f"harness_tool {name!r}: args_schema {args_schema.__name__} has no fields. "
            "langchain-core calls a tool with an empty schema without its injected "
            "runtime, so it would fail on every call. Add at least one (optional) argument."
        )

    def decorator(fn: ToolFn[A, T]) -> BaseTool:
        # ToolRuntime[context type, graph state type]. The wrapper never reads the
        # graph state, so its type stays Any. Because ``runtime`` is typed as a
        # ToolRuntime, LangChain injects it and hides it from the model (W6).
        async def _run(runtime: ToolRuntime[ToolContext, Any], **kwargs: Any) -> str:
            # Step 1: the per-turn context, passed by run_turn as ainvoke(context=...).
            ctx = runtime.context
            call_id = runtime.tool_call_id  # set by LangGraph from the model's tool call
            started = time.perf_counter()

            # Step 2: log the call. kwargs may omit fields with defaults, so rebuild
            # the model to get the complete, validated arguments.
            args = args_schema(**kwargs)
            await ctx.recorder.emit(
                EventKind.TOOL_STARTED,
                {"tool": name, "args": args.model_dump(mode="json"), "call_id": call_id},
            )

            # Steps 3-5: every branch only sets ``result``; steps 6-7 run for all.
            decision = require_scope(ctx.request.principal, scope)
            if not decision.allowed:
                result: ToolResult[T] = result_from_decision(decision)
            else:
                try:
                    result = await fn(ctx, args)
                except DomainError as exc:
                    result = result_from_domain_error(exc)
                # Any other exception propagates on purpose (D1-A).

            # Step 6: close the call in the event log.
            await ctx.recorder.emit(
                EventKind.TOOL_FINISHED,
                {
                    "tool": name,
                    "status": result.status.value,
                    "error_code": result.error_code,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "summary": _summary(result),
                    "call_id": call_id,
                },
            )

            # Step 7: the model receives the whole envelope (D2-A).
            return result.model_dump_json()

        return StructuredTool.from_function(
            coroutine=_run,
            name=name,
            description=description,
            args_schema=args_schema,
        )

    return decorator


def _summary(result: ToolResult[Any]) -> str | None:
    """A short, safe line for the event log: counts, never the data itself."""
    if result.status.is_error or result.data is None:
        return result.safe_message
    data: object = result.data
    if isinstance(data, Sized):
        return f"{len(data)} item(s)"
    return "1 item"
