"""
Structured JSON logging for all agents.

Usage:
    from shared.logger import get_logger

    logger = get_logger(__name__)
    logger.info("Processing started", workflow_id="WF-123", agent="planning")
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class StructuredFormatter(logging.Formatter):
    """Formats log records as JSON for CloudWatch parsing."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include extra fields passed via logger.info("msg", extra={...})
        # or via our custom LoggerAdapter
        if hasattr(record, "extra_fields"):
            log_entry.update(record.extra_fields)

        # Include exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


class StructuredLogger(logging.LoggerAdapter):
    """Logger adapter that supports keyword arguments as structured fields."""

    def process(self, msg: str, kwargs: dict) -> tuple[str, dict]:
        # Extract our extra fields from kwargs
        extra_fields = {k: v for k, v in (self.extra or {}).items()}

        # Any kwargs not recognized by logging go into extra_fields
        extra_kw = kwargs.pop("extra_fields", {})
        extra_fields.update(extra_kw)

        kwargs.setdefault("extra", {})
        kwargs["extra"]["extra_fields"] = extra_fields

        return msg, kwargs

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        extra_fields = {
            k: v
            for k, v in kwargs.items()
            if k not in ("exc_info", "stack_info", "stacklevel", "extra")
        }
        for k in extra_fields:
            kwargs.pop(k)
        kwargs.setdefault("extra_fields", {})
        kwargs["extra_fields"].update(extra_fields)
        super().info(msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        extra_fields = {
            k: v
            for k, v in kwargs.items()
            if k not in ("exc_info", "stack_info", "stacklevel", "extra")
        }
        for k in extra_fields:
            kwargs.pop(k)
        kwargs.setdefault("extra_fields", {})
        kwargs["extra_fields"].update(extra_fields)
        super().warning(msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        extra_fields = {
            k: v
            for k, v in kwargs.items()
            if k not in ("exc_info", "stack_info", "stacklevel", "extra")
        }
        for k in extra_fields:
            kwargs.pop(k)
        kwargs.setdefault("extra_fields", {})
        kwargs["extra_fields"].update(extra_fields)
        super().error(msg, *args, **kwargs)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        extra_fields = {
            k: v
            for k, v in kwargs.items()
            if k not in ("exc_info", "stack_info", "stacklevel", "extra")
        }
        for k in extra_fields:
            kwargs.pop(k)
        kwargs.setdefault("extra_fields", {})
        kwargs["extra_fields"].update(extra_fields)
        super().debug(msg, *args, **kwargs)


def get_logger(name: str, **default_fields: Any) -> StructuredLogger:
    """
    Create a structured logger.

    Args:
        name: Logger name (typically __name__).
        **default_fields: Fields included in every log entry (e.g., agent="planning").

    Returns:
        StructuredLogger instance.
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False

    return StructuredLogger(logger, default_fields)
