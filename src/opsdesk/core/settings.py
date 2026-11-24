"""Application settings, loaded from environment variables (prefix ``OPSDESK_``) and ``.env``.

Secrets never get a usable default value and are never logged.
Model settings live in ``llm.settings`` (M03).

API settings (M04):

* ``api_host`` / ``api_port``: where ``poe dev`` binds. ``127.0.0.1`` by default, so
  the demo server is not reachable from the network.
* ``session_secret``: HS256 key that signs demo session tokens. Required in ``prod``.
  In ``dev``/``test`` it may be unset: the app then generates a random key per process,
  so tokens simply stop working after a restart (in-memory threads are lost on restart
  anyway). There is deliberately no fixed fallback string that could end up in prod.
* ``session_ttl_minutes``: lifetime of a session token.
"""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

type AppEnv = Literal["dev", "test", "prod"]
type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

# HS256 keys shorter than the hash output (32 bytes) are weak; PyJWT warns about them.
MIN_SECRET_LENGTH = 32


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

    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    session_secret: SecretStr | None = Field(default=None, min_length=MIN_SECRET_LENGTH)
    session_ttl_minutes: int = Field(default=60, ge=1)

    @model_validator(mode="after")
    def _prod_needs_a_session_secret(self) -> Self:
        if self.app_env == "prod" and self.session_secret is None:
            raise ValueError("OPSDESK_SESSION_SECRET is required when OPSDESK_APP_ENV=prod")
        return self
