"""Domain errors with stable machine-readable codes."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    CONFIGURATION_INVALID = "configuration_invalid"
    DATABASE_NOT_INITIALIZED = "database_not_initialized"
    DATABASE_UNAVAILABLE = "database_unavailable"
    INDEX_FAILED = "index_failed"
    INTERNAL_ERROR = "internal_error"
    INVALID_PATH = "invalid_path"
    PARSER_UNAVAILABLE = "parser_unavailable"
    PATH_OUTSIDE_REPOSITORY = "path_outside_repository"
    REPOSITORY_LOCKED = "repository_locked"
    REPOSITORY_NOT_FOUND = "repository_not_found"


class MonasLensError(Exception):
    """Expected application error safe to present to users."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code.value, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload
