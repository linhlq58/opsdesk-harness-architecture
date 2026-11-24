"""A tiny in-process HTTP client that can **hang up mid-stream** (M04 demo and tests).

``httpx.ASGITransport`` buffers the whole response before returning it, so it cannot
show frames as they arrive or disconnect after the first token. This client speaks
ASGI directly to the app, the way uvicorn does:

* ``receive()`` hands over the request body once, then waits; when ``stop(frame)``
  returns ``True`` it answers ``http.disconnect``, exactly what uvicorn sends when the
  browser tab closes.
* ``send()`` collects the status code and parses SSE frames as they are written.

Run the app's lifespan around it (``app.router.lifespan_context(app)``).
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import anyio
from starlette.types import ASGIApp, Message


@dataclass
class SseFrame:
    event: str | None
    id: str | None
    data: dict[str, Any]


@dataclass
class StreamResult:
    status: int = 0
    frames: list[SseFrame] = field(default_factory=list[SseFrame])
    body: bytes = b""  # the raw body when the response is not a stream (errors)
    disconnected: bool = False


def parse_sse(text: str) -> list[SseFrame]:
    """Parse complete SSE frames (separated by a blank line); comments are skipped."""
    frames: list[SseFrame] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        event = frame_id = None
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("id:"):
                frame_id = line.removeprefix("id:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").lstrip())
        if data_lines:
            frames.append(SseFrame(event, frame_id, json.loads("\n".join(data_lines))))
    return frames


async def stream_post(
    app: ASGIApp,
    path: str,
    payload: Mapping[str, Any],
    *,
    token: str | None = None,
    stop: Callable[[SseFrame], bool] | None = None,
) -> StreamResult:
    """POST ``payload`` as JSON; collect frames; hang up once ``stop(frame)`` is true."""
    body = json.dumps(payload).encode("utf-8")
    headers = [(b"content-type", b"application/json")]
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode("ascii")))
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},  # like uvicorn
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    result = StreamResult()
    hang_up = anyio.Event()
    body_sent = False
    buffer = ""

    async def receive() -> Message:
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await hang_up.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        nonlocal buffer
        if message["type"] == "http.response.start":
            result.status = message["status"]
        elif message["type"] == "http.response.body":
            chunk: bytes = message.get("body", b"")
            result.body += chunk
            if result.disconnected:
                return
            buffer += chunk.decode("utf-8")
            complete, _, buffer = buffer.rpartition("\n\n")
            for frame in parse_sse(complete):
                result.frames.append(frame)
                if stop is not None and stop(frame):
                    result.disconnected = True
                    hang_up.set()
                    return

    await app(scope, receive, send)
    return result
