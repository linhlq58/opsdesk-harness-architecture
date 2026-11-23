"""Application settings, loaded from environment variables (prefix ``OPSDESK_``) and ``.env``.

Secrets (API keys) never get a default value and are never logged.
Model settings are added in M03.
"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

type AppEnv = Literal["dev", "test", "prod"]
type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    """Process-wide settings. Construct once at startup and pass it down."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="OPSDESK_",
        extra="ignore",
        # A copied .env.example has empty lines like "OPSDESK_APP_ENV=": an empty
        # value means "use the default".
        env_ignore_empty=True,
    )

    app_env: AppEnv = "dev"
    var_dir: Path = Path("var")
    log_level: LogLevel = "INFO"
