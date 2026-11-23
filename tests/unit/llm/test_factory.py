"""``build_chat_model`` rules (M03 §4.2).

Settings are built with ``model_construct`` (no environment reading at all), and the
environment is filled with *decoy* values: if the factory, or ``ChatOpenAI`` behind
its back, reads the environment, the decoys show up and the test fails.
No network: constructing ``ChatOpenAI`` sends no request.
"""

import pytest
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from opsdesk.llm.factory import LlmConfigError, ModelRole, build_chat_model
from opsdesk.llm.settings import LlmSettings

MODELS = {
    ModelRole.ROUTER: "router-model",
    ModelRole.SPECIALIST: "specialist-model",
    ModelRole.SYNTHESIZER: "synth-model",
    ModelRole.JUDGE: "judge-model",
}


@pytest.fixture(autouse=True)
def decoy_env(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("OPENAI_API_KEY", "decoy-key")
    clean_env.setenv("OPENAI_BASE_URL", "https://decoy.invalid/v1")
    for role in ModelRole:
        clean_env.setenv(f"OPSDESK_MODEL_{role.upper()}", "decoy-model")


def settings(**overrides: object) -> LlmSettings:
    values: dict[str, object] = {
        "base_url": "https://gateway.test/v1",
        "api_key": SecretStr("param-key"),
        "model_router": MODELS[ModelRole.ROUTER],
        "model_specialist": MODELS[ModelRole.SPECIALIST],
        "model_synthesizer": MODELS[ModelRole.SYNTHESIZER],
        "model_judge": MODELS[ModelRole.JUDGE],
        "temperature": 0.0,
        "timeout_s": 30.0,
    }
    return LlmSettings.model_construct(**(values | overrides))  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize("role", list(ModelRole))
def test_each_role_gets_its_own_model_from_settings(role: ModelRole) -> None:
    model = build_chat_model(role, settings())

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == MODELS[role]


def test_connection_and_tunables_come_from_settings() -> None:
    model = build_chat_model(ModelRole.SPECIALIST, settings(temperature=0.3, timeout_s=12.0))

    assert isinstance(model, ChatOpenAI)
    assert model.openai_api_base == "https://gateway.test/v1"
    assert isinstance(model.openai_api_key, SecretStr)
    assert model.openai_api_key.get_secret_value() == "param-key"
    assert model.temperature == 0.3
    assert model.request_timeout == 12.0


def test_missing_api_key_is_a_startup_error_naming_the_variable() -> None:
    # The decoy OPENAI_API_KEY in the environment must not rescue it.
    with pytest.raises(LlmConfigError, match="OPENAI_API_KEY"):
        build_chat_model(ModelRole.SPECIALIST, settings(api_key=None))


def test_missing_base_url_is_a_startup_error_naming_the_variable() -> None:
    # No silent fallback to api.openai.com (or to the decoy URL in the environment).
    with pytest.raises(LlmConfigError, match="OPENAI_BASE_URL"):
        build_chat_model(ModelRole.SPECIALIST, settings(base_url=None))


@pytest.mark.parametrize("role", list(ModelRole))
def test_missing_model_for_the_role_names_its_variable(role: ModelRole) -> None:
    with pytest.raises(LlmConfigError, match=f"OPSDESK_MODEL_{role.upper()}"):
        build_chat_model(role, settings(**{f"model_{role.value}": None}))


def test_other_roles_are_unaffected_by_one_missing_model() -> None:
    s = settings(model_judge=None)
    assert isinstance(build_chat_model(ModelRole.SPECIALIST, s), ChatOpenAI)
    with pytest.raises(LlmConfigError):
        build_chat_model(ModelRole.JUDGE, s)


def test_error_messages_never_contain_the_key() -> None:
    with pytest.raises(LlmConfigError) as info:
        build_chat_model(ModelRole.JUDGE, settings(model_judge=None))
    assert "param-key" not in str(info.value)
