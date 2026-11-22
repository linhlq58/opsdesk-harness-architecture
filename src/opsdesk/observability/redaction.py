"""Remove secrets and PII from data before it becomes an event.

``RunRecorder`` applies ``redact`` to ``tool_started.args`` and ``tool_finished.summary``
*before* the event is created, so no sink (JSONL, SSE, eval, later remote tracers) ever
receives unredacted tool data. Redacting once, at the source, means a new sink cannot
forget to do it.

Rules:

* **Sensitive keys**: a dict key whose name contains ``password``, ``secret``,
  ``token``, ``api_key``, ``authorization`` or ``cookie`` (case-insensitive; ``-``/``_``
  ignored, so ``apiKey`` and ``API-KEY`` match) has its value replaced by
  ``"[REDACTED]"``, whatever the value is. Applied recursively through dicts and lists.
  "token" here means a credential key name; it has nothing to do with the ``token``
  event kind (streamed text), which the recorder does not pass through ``redact``.
* **PII in strings**: email addresses → ``a***@acme.test``; phone-number-like strings
  → ``***567`` (last three digits kept, for debugging).
* **Length**: strings longer than ``max_chars`` are cut, with a ``…[+N chars]`` suffix.

Pure function: returns a new value and never mutates its input.

Limits (deliberate, documented): the phone pattern only matches numbers starting with
``+`` or ``0`` (Vietnamese and international formats) so that VND amounts such as
``150000000`` are not mistaken for phone numbers. Redaction is a safety net, not a
licence to pass secrets to tools.
"""

import re

from pydantic import JsonValue

REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = ("password", "secret", "token", "apikey", "authorization", "cookie")

# local part, then @domain. Keep the first character of the local part.
_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
# +84 90 123 4567 / 0901234567 / 090-123-4567: starts with + or 0, 9 to 15 digits in
# total, single space / dot / dash allowed between digits.
_PHONE = re.compile(r"(?<![\w+])(?:\+\d|0)(?:[ .-]?\d){8,14}(?!\w)")


def redact(value: JsonValue, *, max_chars: int = 500) -> JsonValue:
    if isinstance(value, dict):
        return {
            key: REDACTED if _is_sensitive(key) else redact(item, max_chars=max_chars)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, max_chars=max_chars) for item in value]
    if isinstance(value, str):
        return _truncate(_mask_pii(value), max_chars)
    return value  # int, float, bool, None: nothing to hide


def _is_sensitive(key: str) -> bool:
    normalised = key.lower().replace("_", "").replace("-", "")
    return any(part in normalised for part in _SENSITIVE_KEY_PARTS)


def _mask_pii(text: str) -> str:
    text = _EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", text)
    return _PHONE.sub(lambda m: "***" + re.sub(r"\D", "", m.group(0))[-3:], text)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}…[+{len(text) - max_chars} chars]"
