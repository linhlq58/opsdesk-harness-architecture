"""Scripted chat model: a real ``BaseChatModel`` that replays a fixed list of replies.

Tests and the deterministic demo inject it wherever a real model would go. The agent
cannot tell the difference, which is the point: the harness (tools, wrapper, events,
policies) runs for real; only the model's choices are fixed in advance.

    model = ScriptedChatModel.from_script(
        tool_call("get_ticket", {"ticket_id": "T-0002"}),  # 1st model call: use a tool
        "T-0002 is in progress.",                           # 2nd model call: answer
    )

Each model call consumes the next message, whatever the prompt says. A script that
runs out raises ``ScriptExhausted``: the agent called the model more often than the
test expected (e.g. it looped after a tool error), and that should fail loudly.

Why a subclass: ``create_agent`` calls ``model.bind_tools(tools)``.
``GenericFakeChatModel`` raises ``NotImplementedError`` there; returning ``self``
works because the script, not the tool schema, decides what the model "says".

Streaming (M04): when the agent is streamed (``astream_events(version="v3")``), the
model is called through ``_stream`` / ``_astream`` instead of ``_generate``. The
parent's version only streams text, so a tool-call-only reply produced *no* chunk and
the agent failed with "stream finished without producing a message". Here a reply is
streamed the way a real provider streams it:

* tool-call reply → name + id, then the arguments, then an empty closing chunk (the
  v3 stream shows a ``tool-call-delta``);
* text reply → one chunk per word, whitespace kept (``"Ticket "``, ``"T-0002 "``, ...),
  each one a ``text-delta`` in the v3 stream and a ``token`` event in OpsDesk.
"""

import asyncio
import itertools
import json
import re
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from typing import Any, override

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolCallChunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from pydantic import Field, JsonValue

# Process-wide counter: tool-call ids only need to be unique within one conversation.
_call_ids = itertools.count(1)


class ScriptExhausted(AssertionError):
    """The model was called more times than the script has replies."""


class ScriptedChatModel(GenericFakeChatModel):
    # What the model was given, one list of messages per call (M04): lets a test check
    # that a second turn on a thread really sends the first turn to the model.
    received: list[list[BaseMessage]] = Field(default_factory=list[list[BaseMessage]])
    # Seconds between streamed chunks (async streaming only). A real provider waits on
    # the network between chunks; even at 0 the fake yields to the event loop after
    # each chunk, so a consumer (the SSE response) can run while the model "talks".
    chunk_delay: float = Field(default=0.0, ge=0.0)

    @classmethod
    def from_script(cls, *replies: AIMessage | str) -> "ScriptedChatModel":
        """Build from replies in call order. A ``str`` is a plain text answer."""
        return cls(messages=iter(replies))

    @override
    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        return self

    @override
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        # Without this, the parent's ``next()`` raises StopIteration, which asyncio
        # turns into a confusing RuntimeError far from the cause.
        self.received.append(list(messages))
        try:
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        except StopIteration:
            raise ScriptExhausted(
                "ScriptedChatModel ran out of replies: the agent called the model more "
                "times than the script expected"
            ) from None

    @override
    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        reply = self._next_reply(messages, stop, **kwargs)
        for chunk in _chunks_for(reply):
            if run_manager:
                run_manager.on_llm_new_token(_chunk_text(chunk), chunk=chunk)
            yield chunk

    @override
    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        # Native async (the base class would run ``_stream`` in a worker thread).
        reply = self._next_reply(messages, stop, **kwargs)
        for chunk in _chunks_for(reply):
            if run_manager:
                await run_manager.on_llm_new_token(_chunk_text(chunk), chunk=chunk)
            yield chunk
            await asyncio.sleep(self.chunk_delay)  # like waiting for the next network read

    def _next_reply(
        self, messages: list[BaseMessage], stop: list[str] | None, **kwargs: Any
    ) -> AIMessage:
        message = self._generate(messages, stop=stop, **kwargs).generations[0].message
        if not isinstance(message, AIMessage):
            raise TypeError(f"scripted replies must be AIMessage, got {type(message).__name__}")
        return message


def _chunks_for(reply: AIMessage) -> list[ChatGenerationChunk]:
    """Split one scripted reply into the chunks a real provider would stream."""
    if reply.tool_calls:
        # Like a real provider: first the call's name and id, then its arguments. A
        # single chunk would make the v3 stream skip ``tool-call-delta`` entirely.
        heads = [
            ToolCallChunk(
                name=call["name"], args="", id=call["id"], index=i, type="tool_call_chunk"
            )
            for i, call in enumerate(reply.tool_calls)
        ]
        bodies = [
            ToolCallChunk(
                name=None, args=json.dumps(call["args"]), id=None, index=i, type="tool_call_chunk"
            )
            for i, call in enumerate(reply.tool_calls)
        ]
        pieces = [
            AIMessageChunk(content=reply.text, id=reply.id, tool_call_chunks=heads),
            AIMessageChunk(content="", id=reply.id, tool_call_chunks=bodies),
            # Closing chunk, like a provider's final "finish_reason" chunk. The "last"
            # marker must not sit on the arguments chunk: LangChain would then parse
            # that chunk alone as a finished call (no name) and drop the arguments.
            AIMessageChunk(content="", id=reply.id),
        ]
    else:
        # "Ticket T-0002 is" → ["Ticket ", "T-0002 ", "is"]: words keep their trailing
        # whitespace, so the chunks concatenate back to the exact text.
        words = re.findall(r"\S+\s*|\s+", reply.text) or [""]
        pieces = [AIMessageChunk(content=word, id=reply.id) for word in words]
    pieces[-1].chunk_position = "last"
    return [ChatGenerationChunk(message=piece) for piece in pieces]


def _chunk_text(chunk: ChatGenerationChunk) -> str:
    return chunk.message.text


def tool_call(name: str, args: dict[str, JsonValue], *, call_id: str | None = None) -> AIMessage:
    """A model reply that asks for one tool call (no text)."""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id or f"call_{next(_call_ids)}"}],
    )
