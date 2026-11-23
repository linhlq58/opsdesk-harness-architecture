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
"""

import itertools
from collections.abc import Callable, Sequence
from typing import Any, override

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from pydantic import JsonValue

# Process-wide counter: tool-call ids only need to be unique within one conversation.
_call_ids = itertools.count(1)


class ScriptExhausted(AssertionError):
    """The model was called more times than the script has replies."""


class ScriptedChatModel(GenericFakeChatModel):
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
        try:
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        except StopIteration:
            raise ScriptExhausted(
                "ScriptedChatModel ran out of replies: the agent called the model more "
                "times than the script expected"
            ) from None


def tool_call(name: str, args: dict[str, JsonValue], *, call_id: str | None = None) -> AIMessage:
    """A model reply that asks for one tool call (no text)."""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id or f"call_{next(_call_ids)}"}],
    )
