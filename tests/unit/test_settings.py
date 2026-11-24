from pathlib import Path

import pytest
from pydantic import ValidationError

from opsdesk.core.settings import Settings


def test_defaults(clean_env: pytest.MonkeyPatch) -> None:
    settings = Settings()

    assert settings.app_env == "dev"
    assert settings.var_dir == Path("var")
    assert settings.log_level == "INFO"


def test_blank_values_use_defaults(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # A copied .env.example has empty lines: they must mean "default", not "invalid".
    (tmp_path / ".env").write_text(
        "OPSDESK_APP_ENV=\nOPSDESK_VAR_DIR=\nOPSDESK_LOG_LEVEL=\n", encoding="utf-8"
    )
    settings = Settings()

    assert (settings.app_env, settings.var_dir, settings.log_level) == ("dev", Path("var"), "INFO")


def test_loads_from_environment(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clean_env.setenv("OPSDESK_APP_ENV", "test")
    clean_env.setenv("OPSDESK_VAR_DIR", str(tmp_path / "data"))
    clean_env.setenv("OPSDESK_LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.app_env == "test"
    assert settings.var_dir == tmp_path / "data"
    assert settings.log_level == "DEBUG"


def test_loads_from_dotenv_file(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # prod needs a session secret (M04)
    (tmp_path / ".env").write_text(
        f"OPSDESK_APP_ENV=prod\nOPSDESK_SESSION_SECRET={'s' * 32}\n", encoding="utf-8"
    )

    assert Settings().app_env == "prod"


def test_environment_overrides_dotenv(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("OPSDESK_APP_ENV=prod\n", encoding="utf-8")
    clean_env.setenv("OPSDESK_APP_ENV", "test")

    assert Settings().app_env == "test"


def test_invalid_app_env_is_rejected(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("OPSDESK_APP_ENV", "staging")

    with pytest.raises(ValidationError):
        Settings()


def test_invalid_log_level_is_rejected(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("OPSDESK_LOG_LEVEL", "VERBOSE")

    with pytest.raises(ValidationError):
        Settings()


def test_var_dir_is_a_path(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("OPSDESK_VAR_DIR", "some/where")

    settings = Settings()

    assert isinstance(settings.var_dir, Path)
    assert settings.var_dir == Path("some") / "where"


def test_unknown_opsdesk_variables_are_ignored(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("OPSDESK_NOT_A_SETTING", "x")

    Settings()  # must not raise


# ----------------------------------------------------------------- API settings (M04)


def test_api_defaults(clean_env: pytest.MonkeyPatch) -> None:
    settings = Settings()

    assert (settings.api_host, settings.api_port) == ("127.0.0.1", 8000)
    assert settings.session_secret is None
    assert settings.session_ttl_minutes == 60


def test_prod_requires_a_session_secret(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("OPSDESK_APP_ENV", "prod")

    with pytest.raises(ValidationError, match="OPSDESK_SESSION_SECRET"):
        Settings()


def test_prod_accepts_a_long_enough_secret(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("OPSDESK_APP_ENV", "prod")
    clean_env.setenv("OPSDESK_SESSION_SECRET", "x" * 32)

    settings = Settings()

    assert settings.session_secret is not None
    assert "x" * 32 not in repr(settings)  # SecretStr: never printed


def test_short_session_secret_is_rejected(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("OPSDESK_SESSION_SECRET", "too-short")

    with pytest.raises(ValidationError):
        Settings()
