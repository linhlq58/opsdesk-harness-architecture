"""Settings for talking to the course's OpenAI-compatible LLM gateway.

Read from the environment and ``.env`` (see ``.env.example``):

=========================  ==============================  ==========================
field                      env variable                    note
=========================  ==============================  ==========================
``base_url``               ``OPENAI_BASE_URL``             the gateway URL
``api_key``                ``OPENAI_API_KEY``              ``SecretStr``: never logged
``model_router``           ``OPSDESK_MODEL_ROUTER``        model name per *role*;
``model_specialist``       ``OPSDESK_MODEL_SPECIALIST``    names depend on what the
``model_synthesizer``      ``OPSDESK_MODEL_SYNTHESIZER``   gateway exposes, so they
``model_judge``            ``OPSDESK_MODEL_JUDGE``         live in ``.env``, not code
``temperature``            ``OPSDESK_LLM_TEMPERATURE``     default unset (not sent)
``timeout_s``              ``OPSDESK_LLM_TIMEOUT_S``       default 30 s per call
=========================  ==============================  ==========================

Every field is optional *here*: tests and the fake-model demo never need a key. The
model factory (``llm.factory``) decides what a given role requires and fails at
startup, naming the missing variable. This class only loads and type-checks.

``OPENAI_*`` keep their standard names (no ``OPSDESK_`` prefix) so the same ``.env``
works with other OpenAI-compatible tools.
"""

from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LlmSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="OPSDESK_",
        extra="ignore",
        # A copied .env.example has empty lines like "OPSDESK_LLM_TIMEOUT_S=": an empty
        # value means "use the default", not "parse '' as a number".
        env_ignore_empty=True,
        # Fields named ``model_*`` would otherwise clash with pydantic's own namespace.
        protected_namespaces=(),
    )

    # validation_alias replaces the OPSDESK_ prefix for these two.
    base_url: str | None = Field(default=None, validation_alias="OPENAI_BASE_URL")
    api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")

    model_router: str | None = None
    model_specialist: str | None = None
    model_synthesizer: str | None = None
    model_judge: str | None = None

    # None = not sent: the model uses its own default. Some models (reasoning models)
    # reject any explicit temperature other than 1, so the harness sends one only
    # when configured (M03 Notes, decision on temperature).
    temperature: float | None = Field(
        default=None, ge=0.0, le=2.0, validation_alias="OPSDESK_LLM_TEMPERATURE"
    )
    timeout_s: float = Field(default=30.0, gt=0.0, validation_alias="OPSDESK_LLM_TIMEOUT_S")

    @field_validator(
        "base_url",
        "api_key",
        "model_router",
        "model_specialist",
        "model_synthesizer",
        "model_judge",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: Any) -> Any:
        # ``.env.example`` is copied with empty values (``OPENAI_API_KEY=``). An empty
        # string is "not configured", so the factory reports it as missing instead of
        # sending an empty key to the gateway and getting a 401.
        if isinstance(value, str) and not value.strip():
            return None
        return value
