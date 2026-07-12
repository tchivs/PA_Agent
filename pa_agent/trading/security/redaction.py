"""Centralized recursive redaction for trading-facing output payloads."""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

REDACTION_TOKEN = "[REDACTED]"
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "passphrase",
    "password",
    "secret",
    "signature",
    "token",
)
_SENSITIVE_QUERY_PATTERN = re.compile(
    r"([?&](?:api[_-]?key|authorization|credential|passphrase|password|secret|signature|token)=)[^&#\s]+",
    re.IGNORECASE,
)


class SecretRedactor:
    """Redacts registered values and sensitive shapes from nested output data."""

    def __init__(self, values: Sequence[str] = ()) -> None:
        self._values = tuple(sorted((value for value in values if value), key=len, reverse=True))

    def register(self, value: str) -> None:
        """Register another in-memory value for subsequent output redaction."""
        if value and value not in self._values:
            self._values = tuple(sorted((*self._values, value), key=len, reverse=True))

    def redact(self, value: Any) -> Any:
        """Return an equivalent safe shape without raw secret-bearing values."""
        if isinstance(value, Exception):
            return {"type": type(value).__name__, "message": self._redact_string(str(value))}
        if isinstance(value, Mapping):
            return {
                str(key): REDACTION_TOKEN if self._is_sensitive_key(key) else self.redact(item)
                for key, item in value.items()
            }
        if isinstance(value, str):
            return self._redact_string(value)
        if isinstance(value, tuple):
            return tuple(self.redact(item) for item in value)
        if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            return [self.redact(item) for item in value]
        return value

    @staticmethod
    def _is_sensitive_key(key: object) -> bool:
        normalized = str(key).lower().replace("-", "_")
        return any(part in normalized for part in _SENSITIVE_KEY_PARTS)

    def _redact_string(self, value: str) -> str:
        redacted = value
        for secret in self._values:
            redacted = redacted.replace(secret, REDACTION_TOKEN)
        return _SENSITIVE_QUERY_PATTERN.sub(r"\1" + REDACTION_TOKEN, redacted)
