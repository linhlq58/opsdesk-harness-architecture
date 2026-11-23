"""Role-based chat model factory (M03 §5.2).

One function decides which model serves which **role**. Agents never name a model;
they ask for a role, and the composition root (CLI, API, demo) calls this factory and
passes the model to the agent. Tests pass a ``ScriptedChatModel`` instead.

Rules (tests: ``tests/unit/llm/test_factory.py``):

* The model name for a role comes from ``LlmSettings`` (``model_<role>``).
* Missing ``OPENAI_API_KEY``, ``OPENAI_BASE_URL`` or the role's model name →
  ``LlmConfigError`` at startup, naming the env variable. Not a 401 from the gateway
  on the first question, and never a silent fallback to api.openai.com.
* Settings come in as a parameter: the factory does not read the environment itself.
  Careful: ``ChatOpenAI`` *does* read ``OPENAI_API_KEY`` / ``OPENAI_BASE_URL`` from the
  environment when you leave them out, so pass both explicitly.
* ``temperature`` and ``timeout_s`` come from the settings too. An unset temperature
  is **not sent** (``ChatOpenAI`` omits ``None``), so models that reject it, such as
  reasoning models, still work.
* Callbacks (tracing, usage) get attached here in M07: keep one place for that.

Docs: https://docs.langchain.com/oss/python/integrations/chat/openai
"""

from enum import StrEnum

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from opsdesk.llm.settings import LlmSettings


class ModelRole(StrEnum):
    ROUTER = "router"
    SPECIALIST = "specialist"
    SYNTHESIZER = "synthesizer"
    JUDGE = "judge"


class LlmConfigError(RuntimeError):
    """The LLM settings are incomplete for what was asked. The message names the
    missing environment variable (e.g. ``OPSDESK_MODEL_SPECIALIST``) and never
    contains the API key."""


def build_chat_model(role: ModelRole, settings: LlmSettings) -> BaseChatModel:
    """Return the chat model configured for ``role``.

    Raises ``LlmConfigError`` if the key, the base URL or the role's model name is
    missing.
    """
    # Fail at startup, naming the variable, instead of a 401 on the first question.
    if settings.api_key is None:
        raise LlmConfigError("OPENAI_API_KEY is not set")
    if settings.base_url is None:
        raise LlmConfigError("OPENAI_BASE_URL is not set")
    model_name = _model_name(role, settings)
    if model_name is None:
        raise LlmConfigError(f"OPSDESK_MODEL_{role.value.upper()} is not set")

    # Everything passed explicitly: ChatOpenAI would otherwise read OPENAI_* from
    # the environment behind our back. M07: callbacks (tracing, usage) go here.
    return ChatOpenAI(
        model=model_name,
        api_key=settings.api_key,
        base_url=settings.base_url,
        temperature=settings.temperature,  # None → omitted from the request
        timeout=settings.timeout_s,
    )


def _model_name(role: ModelRole, settings: LlmSettings) -> str | None:
    match role:
        case ModelRole.ROUTER:
            return settings.model_router
        case ModelRole.SPECIALIST:
            return settings.model_specialist
        case ModelRole.SYNTHESIZER:
            return settings.model_synthesizer
        case ModelRole.JUDGE:
            return settings.model_judge
