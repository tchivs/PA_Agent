"""Centralised logging configuration for PA Agent.

Public API
----------
configure_logging(api_key: str = "") -> None
update_api_key(new_key: str) -> None
verify_logging_handlers() -> bool
"""
from __future__ import annotations

import copy
import logging
import logging.handlers
from pathlib import Path
from types import TracebackType
from typing import Any

from pa_agent.config.paths import LOG_FILE_PATH
from pa_agent.trading.security.redaction import output_redactor

# ── Module-level state ────────────────────────────────────────────────────────

_active_formatters: list[MaskingFormatter] = []
_configured: bool = False
_LOGGING_EXCEPTION_REASON = "logging_exception_redacted"

# ── MaskingFormatter ──────────────────────────────────────────────────────────


class MaskingFormatter(logging.Formatter):
    """Logging formatter that replaces the plaintext API key with its masked form."""

    def __init__(self, fmt: str, api_key: str = "") -> None:
        super().__init__(fmt)
        self._api_key = api_key
        if api_key:
            output_redactor().register(api_key)

    def format(self, record: logging.LogRecord) -> str:
        safe_record = copy.copy(record)
        redactor = output_redactor()
        safe_record.msg = redactor.redact(record.msg)
        safe_record.args = redactor.redact(record.args)
        safe_record.__dict__.pop("message", None)
        safe_record.exc_text = None
        safe_record.exc_info = _safe_exc_info(record.exc_info)
        message = super().format(safe_record)
        return output_redactor().redact(message)

    def set_api_key(self, new_key: str) -> None:
        self._api_key = new_key
        if new_key:
            output_redactor().register(new_key)


def _safe_exc_info(exc_info: Any) -> tuple[type[BaseException], BaseException, TracebackType | None] | None:
    """Detach untrusted exceptions while retaining a controlled standard traceback shape."""
    if not exc_info:
        return None

    exception_type: type[BaseException] = Exception
    traceback: TracebackType | None = None
    if isinstance(exc_info, tuple) and len(exc_info) == 3:
        candidate_type, _candidate_value, candidate_traceback = exc_info
        if isinstance(candidate_type, type) and issubclass(candidate_type, BaseException):
            exception_type = candidate_type
        if isinstance(candidate_traceback, TracebackType):
            traceback = candidate_traceback
    elif isinstance(exc_info, BaseException):
        exception_type = type(exc_info)
        traceback = exc_info.__traceback__

    safe_type = type(exception_type.__name__, (Exception,), {})
    safe_exception = safe_type(f"{_LOGGING_EXCEPTION_REASON} {output_redactor().redact('[REDACTED]')}")
    return safe_type, safe_exception, traceback


# ── Public functions ──────────────────────────────────────────────────────────

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

_THIRD_PARTY_LOGGERS = ("urllib3", "openai", "httpx")

# tvdatafeed opens a websocket every refresh tick and logs at DEBUG — keep quiet
_QUIET_LOGGER_NAMES = (
    "urllib3",
    "openai",
    "httpx",
    "tvDatafeed",
    "tvDatafeed.main",
    "root",  # tvdatafeed uses logging.getLogger("root") for websocket
    "websocket",
)


def verify_logging_handlers() -> bool:
    """Return True when the expected rotating file handler is attached to root."""
    expected = str(LOG_FILE_PATH.resolve())
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            base = getattr(handler, "baseFilename", "")
            if str(Path(base).resolve()) == expected:
                return True
    return False


def configure_logging(api_key: str = "") -> None:
    """Configure the root logger with rotating file handler and console handler.

    Both handlers use MaskingFormatter that replaces api_key with mask_secret(api_key).
    Third-party loggers (urllib3, openai, httpx) are also attached to the same handlers.

    If handlers were removed after a prior configure_logging call, re-attaches them.
    """
    global _configured

    if _configured:
        if api_key:
            update_api_key(api_key)
        if verify_logging_handlers():
            return
        # Handlers missing (e.g. external code cleared root.handlers) — re-install.
        _configured = False

    # Build formatters
    file_formatter = MaskingFormatter(_LOG_FORMAT, api_key=api_key)
    console_formatter = MaskingFormatter(_LOG_FORMAT, api_key=api_key)

    # Track all active formatters so update_api_key can reach them
    _active_formatters.clear()
    _active_formatters.append(file_formatter)
    _active_formatters.append(console_formatter)

    # Rotating file handler
    LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE_PATH,
        maxBytes=5 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setFormatter(file_formatter)

    # Console (stream) handler — INFO+ only; file keeps DEBUG for troubleshooting
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)

    handlers: list[logging.Handler] = [file_handler, console_handler]

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    # Remove any previously installed handlers to avoid duplicates on re-call
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)
    for h in handlers:
        root_logger.addHandler(h)

    # Attach the same handlers to third-party loggers
    for name in _THIRD_PARTY_LOGGERS:
        tp_logger = logging.getLogger(name)
        for h in list(tp_logger.handlers):
            tp_logger.removeHandler(h)
        for h in handlers:
            tp_logger.addHandler(h)
        # Prevent double-logging via root propagation
        tp_logger.propagate = False

    _silence_noisy_libraries()

    _configured = True
    logging.getLogger("pa_agent.diagnostics").info(
        "configure_logging: handlers attached (log_file=%s)", LOG_FILE_PATH
    )


def _silence_noisy_libraries() -> None:
    """Turn down chatty third-party DEBUG loggers (tvdatafeed websocket spam)."""
    for name in _QUIET_LOGGER_NAMES:
        logging.getLogger(name).setLevel(logging.WARNING)


def update_api_key(new_key: str) -> None:
    """Update the masking key in all active MaskingFormatter instances."""
    for formatter in _active_formatters:
        formatter.set_api_key(new_key)
