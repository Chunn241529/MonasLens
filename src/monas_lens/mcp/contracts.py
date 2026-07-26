"""Immutable contracts returned by the Community MCP tools."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from monas_lens.retrieval.contracts import (
    ConfidenceResult,
    ContextSnippet,
    RetrievalDiagnostic,
    ValidationCommand,
)

MCP_SCHEMA_VERSION = "1.0"


class McpContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CommandKind(StrEnum):
    AUTO = "auto"
    TEST = "test"
    BUILD = "build"
    COMPILER = "compiler"
    LINTER = "linter"
    STACK_TRACE = "stack_trace"
    GIT_DIFF = "git_diff"


class ContextExpansion(McpContract):
    schema_version: Literal["1.0"] = MCP_SCHEMA_VERSION
    repository_id: str
    focus_target: str
    confidence: ConfidenceResult
    snippets: tuple[ContextSnippet, ...]
    diagnostics: tuple[RetrievalDiagnostic, ...] = ()
    omitted_known_snippets: Annotated[int, Field(ge=0)] = 0
    truncated: bool = False


class ImpactSymbol(McpContract):
    id: str
    qualified_name: str
    relative_path: str
    language: str
    kind: str
    start_line: Annotated[int, Field(ge=1)]
    end_line: Annotated[int, Field(ge=1)]


class ImpactNode(McpContract):
    id: str
    node_type: Literal["file", "symbol"]
    relative_path: str
    language: str
    kind: str
    qualified_name: str | None = None
    start_line: Annotated[int | None, Field(ge=1)] = None


class ImpactRisk(McpContract):
    code: str
    severity: Literal["info", "warning"]
    message: str
    relative_path: str | None = None


class PatchImpact(McpContract):
    schema_version: Literal["1.0"] = MCP_SCHEMA_VERSION
    repository_id: str
    changed_paths: tuple[str, ...]
    changed_symbols: tuple[ImpactSymbol, ...]
    affected_callers: tuple[ImpactNode, ...]
    routes: tuple[ImpactSymbol, ...]
    schemas: tuple[ImpactSymbol, ...]
    tests: tuple[ImpactNode, ...]
    risks: tuple[ImpactRisk, ...]
    validation_commands: tuple[ValidationCommand, ...]
    unrelated_changes: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    truncated: bool = False


class CommandOutputSummary(McpContract):
    schema_version: Literal["1.0"] = MCP_SCHEMA_VERSION
    command_kind: CommandKind
    content: str
    original_lines: Annotated[int, Field(ge=0)]
    selected_lines: Annotated[int, Field(ge=0)]
    omitted_lines: Annotated[int, Field(ge=0)]
    repeated_lines_collapsed: Annotated[int, Field(ge=0)]
    truncated: bool = False
