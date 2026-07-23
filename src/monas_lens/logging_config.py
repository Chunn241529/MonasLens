"""Logging configuration with operation correlation."""

from __future__ import annotations

import json
import logging
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from uuid import uuid4

from monas_lens.config import Settings

_operation_id: ContextVar[str | None] = ContextVar("operation_id", default=None)


class OperationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.operation_id = _operation_id.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """Serialize safe standard log fields as one JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "operation_id": _operation_id.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(settings: Settings, *, debug: bool = False) -> None:
    level = logging.DEBUG if debug else getattr(logging, settings.log_level.value)
    handler = logging.StreamHandler()
    handler.addFilter(OperationFilter())
    if settings.log_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(levelname)s %(name)s [%(operation_id)s]: %(message)s")
        )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    third_party_level = logging.DEBUG if debug else logging.WARNING
    logging.getLogger("alembic").setLevel(third_party_level)
    logging.getLogger("sqlalchemy").setLevel(third_party_level)


@contextmanager
def operation_context(operation_id: str | None = None) -> Generator[str]:
    selected_id = operation_id or str(uuid4())
    token: Token[str | None] = _operation_id.set(selected_id)
    try:
        yield selected_id
    finally:
        _operation_id.reset(token)
