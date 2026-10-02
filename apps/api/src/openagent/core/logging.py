import logging
import sys
from typing import Any, Dict

import structlog

from openagent.core.config import get_settings

# Keys whose values must never reach logs/traces in any environment.
# Matching is case-insensitive and substring-based ("api_key" redacts
# "openai_api_key" too). Keep values as the fixed token "[REDACTED]" so
# log shape stays stable for parsers.
_SENSITIVE_KEY_MARKERS = (
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "oauth",
    "authorization",
    "cookie",
    "session",
    "private_key",
    "client_secret",
    "webhook_secret",
    "encryption_key",
    "bearer",
    "set-cookie",
)

_REDACTED = "[REDACTED]"


def _redact_value(key: str, value: Any) -> Any:
    lowered = str(key).lower()
    if any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS):
        return _REDACTED
    if isinstance(value, dict):
        return {k: _redact_value(k, v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(key, item) for item in value]
    return value


def redact_sensitive(_logger: Any, _method: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """structlog processor: strip credentials from every log record.

    Runs in ALL environments (dev included) so a debug session can never
    leak secrets into terminal scrollback or collected logs.
    """
    for key in list(event_dict.keys()):
        if key in ("event", "level", "timestamp", "logger"):
            continue
        try:
            event_dict[key] = _redact_value(key, event_dict[key])
        except Exception:
            event_dict[key] = _REDACTED
    return event_dict


def configure_logging() -> None:
    settings = get_settings()

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        redact_sensitive,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.is_development:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.LOG_LEVEL.upper()),
    )

    for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"]:
        logging.getLogger(logger_name).handlers = []
        logging.getLogger(logger_name).propagate = True


def get_logger(name: str = "openagent") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
