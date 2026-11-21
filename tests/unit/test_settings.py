from pathlib import Path

import pytest
from pydantic import ValidationError

from opsdesk.core.settings import Settings


def test_defaults(clean_env: pytest.MonkeyPatch) -> None:
    settings = Settings()

    assert settings.app_env == "dev"
    assert settings.var_dir == Path("var")
    assert settings.log_level == "INFO"


def test_loads_from_environment(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clean_env.setenv("OPSDESK_APP_ENV", "test")
    clean_env.setenv("OPSDESK_VAR_DIR", str(tmp_path / "data"))
    clean_env.setenv("OPSDESK_LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.app_env == "test"
    assert settings.var_dir == tmp_path / "data"
    assert settings.log_level == "DEBUG"


def test_loads_from_dotenv_file(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("OPSDESK_APP_ENV=prod\n", encoding="utf-8")

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
