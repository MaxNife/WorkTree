"""Structured JSON logging with correlation ids and secret masking."""

from __future__ import annotations

import logging
import logging.handlers
import sys
import uuid
from typing import Any

import structlog

from app.config import Settings
from app.domain.masking import SecretMasker, get_masker

_configured = False


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def bind_correlation_id(correlation_id: str) -> None:
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)


def clear_correlation_id() -> None:
    structlog.contextvars.unbind_contextvars("correlation_id")


def add_correlation_id(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    if not event_dict.get("correlation_id"):
        context = structlog.contextvars.get_contextvars()
        event_dict["correlation_id"] = context.get("correlation_id", "-")
    return event_dict


def mask_event(
    _logger: Any, _method: str, event_dict: dict[str, Any], masker: SecretMasker | None = None
) -> dict[str, Any]:
    active = masker or get_masker()
    for key, value in list(event_dict.items()):
        event_dict[key] = active.mask_obj(value)
    return event_dict


def configure_logging(
    settings: Settings,
    *,
    masker: SecretMasker | None = None,
    console: bool = True,
) -> None:
    """Configure structlog and the stdlib logging handlers. Idempotent per process."""
    global _configured
    active_masker = masker or get_masker()
    log_dir = settings.logging.directory
    log_dir.mkdir(parents=True, exist_ok=True)

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        add_correlation_id,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        lambda _l, _m, ed: mask_event(_l, _m, ed, active_masker),
    ]
    renderer: Any = structlog.processors.JSONRenderer()
    formatter = structlog.stdlib.ProcessorFormatter(processor=renderer, foreign_pre_chain=shared)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(settings.logging.level.upper())

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "uaf.log",
        maxBytes=settings.logging.max_bytes,
        backupCount=settings.logging.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str = "uaf") -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)


def is_configured() -> bool:
    return _configured
