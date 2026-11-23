import pytest
from pydantic import ValidationError

from opsdesk.llm.settings import LlmSettings

_LLM_VARS = (
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "OPSDESK_MODEL_ROUTER",
    "OPSDESK_MODEL_SPECIALIST",
    "OPSDESK_MODEL_SYNTHESIZER",
    "OPSDESK_MODEL_JUDGE",
    "OPSDESK_LLM_TEMPERATURE",
    "OPSDESK_LLM_TIMEOUT_S",
)


@pytest.fixture
def env(clean_env: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for key in _LLM_VARS:
        clean_env.delenv(key, raising=False)
    return clean_env


def test_everything_is_optional(env: pytest.MonkeyPatch) -> None:
    s = LlmSettings()
    assert s.base_url is None
    assert s.api_key is None
    assert s.model_specialist is None
    assert s.temperature == 0.0
    assert s.timeout_s == 30.0


def test_reads_standard_openai_names_and_prefixed_models(env: pytest.MonkeyPatch) -> None:
    env.setenv("OPENAI_BASE_URL", "https://gateway.test/v1")
    env.setenv("OPENAI_API_KEY", "sk-secret")
    env.setenv("OPSDESK_MODEL_SPECIALIST", "some-model")
    env.setenv("OPSDESK_LLM_TIMEOUT_S", "12.5")
    s = LlmSettings()
    assert s.base_url == "https://gateway.test/v1"
    assert s.api_key is not None
    assert s.api_key.get_secret_value() == "sk-secret"
    assert s.model_specialist == "some-model"
    assert s.timeout_s == 12.5


def test_reads_dotenv_file(env: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    Path(".env").write_text("OPSDESK_MODEL_ROUTER=router-model\n", encoding="utf-8")
    assert LlmSettings().model_router == "router-model"


def test_blank_values_count_as_not_configured(env: pytest.MonkeyPatch) -> None:
    # A copied .env.example has "OPENAI_API_KEY=" lines.
    env.setenv("OPENAI_API_KEY", "")
    env.setenv("OPSDESK_MODEL_JUDGE", "   ")
    s = LlmSettings()
    assert s.api_key is None
    assert s.model_judge is None


def test_api_key_is_not_revealed_by_repr(env: pytest.MonkeyPatch) -> None:
    env.setenv("OPENAI_API_KEY", "sk-secret")
    s = LlmSettings()
    assert "sk-secret" not in repr(s)
    assert "sk-secret" not in str(s.model_dump())


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("OPSDESK_LLM_TEMPERATURE", "-0.1"),
        ("OPSDESK_LLM_TEMPERATURE", "2.5"),
        ("OPSDESK_LLM_TIMEOUT_S", "0"),
    ],
)
def test_out_of_range_tunables_are_rejected(env: pytest.MonkeyPatch, var: str, value: str) -> None:
    env.setenv(var, value)
    with pytest.raises(ValidationError):
        LlmSettings()
