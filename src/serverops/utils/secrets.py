"""Secret redaction helpers."""

from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|private[_-]?key|credential|"
    r"passphrase|authorization|cookie|app_key|database_url)",
    re.IGNORECASE,
)
URL_PASSWORD_RE = re.compile(r"(://[^:/@\s]+:)([^@\s]+)(@)")
REDACTED = "[REDACTED]"


def redact_value(value: Any) -> Any:
    """Recursively redact secret-looking fields and URL credentials."""
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if SENSITIVE_KEY_RE.search(str(key)):
                if isinstance(item, str) and item:
                    clean[key] = REDACTED
                elif item is None or item == "":
                    clean[key] = item
                else:
                    clean[key] = REDACTED
            else:
                clean[key] = redact_value(item)
        return clean
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return URL_PASSWORD_RE.sub(rf"\1{REDACTED}\3", value)
    return value


def redact_text(text: str) -> str:
    """Best-effort redaction for free-form command output."""
    text = URL_PASSWORD_RE.sub(rf"\1{REDACTED}\3", text)
    text = re.sub(
        r"(?i)(password|token|secret|api[_-]?key|passphrase)\s*[:=]\s*\S+",
        lambda match: f"{match.group(1)}={REDACTED}",
        text,
    )
    return text
