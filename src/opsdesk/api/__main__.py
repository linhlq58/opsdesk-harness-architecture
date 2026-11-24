"""``uv run poe dev``: serve the API and the web UI with auto-reload.

Host and port come from settings (``127.0.0.1:8000`` by default). Uvicorn imports the
app factory by name in a worker process, which ``--reload`` needs to restart it on
code changes.
"""

import logging
from pathlib import Path

import uvicorn

from opsdesk.core.settings import Settings


def main() -> None:
    settings = Settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
    uvicorn.run(
        "opsdesk.api.app:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        reload_dirs=[d for d in ("src", "web") if Path(d).is_dir()],
    )


if __name__ == "__main__":
    main()
