"""Domain errors with stable machine-readable codes."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    CONFIGURATION_INVALID = "configuration_invalid"
    CONTEXT_BUDGET_INVALID = "context_budget_invalid"
    CONTEXT_REQUEST_INVALID = "context_request_invalid"
    CONTEXT_RETRIEVAL_FAILED = "context_retrieval_failed"
    DATABASE_NOT_INITIALIZED = "database_not_initialized"
    DATABASE_UNAVAILABLE = "database_unavailable"
    GRAPH_QUERY_INVALID = "graph_query_invalid"
    INDEX_FAILED = "index_failed"
    INTERNAL_ERROR = "internal_error"
    INVALID_PATH = "invalid_path"
    MCP_REQUEST_INVALID = "mcp_request_invalid"
    PARSER_UNAVAILABLE = "parser_unavailable"
    PATCH_IMPACT_FAILED = "patch_impact_failed"
    PATH_OUTSIDE_REPOSITORY = "path_outside_repository"
    REPOSITORY_LOCKED = "repository_locked"
    REPOSITORY_NOT_FOUND = "repository_not_found"
    SEARCH_QUERY_INVALID = "search_query_invalid"


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
