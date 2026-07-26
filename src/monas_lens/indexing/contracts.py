"""Typed contracts shared by scanning, parsing, and persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


def _empty_counts() -> dict[str, int]:
    return {}


def _empty_metadata() -> dict[str, Any]:
    return {}


class Language(StrEnum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    TSX = "tsx"
    DART = "dart"
    GO = "go"


class SymbolKind(StrEnum):
    MODULE = "module"
    CLASS = "class"
    INTERFACE = "interface"
    TYPE_ALIAS = "type_alias"
    ENUM = "enum"
    MIXIN = "mixin"
    EXTENSION = "extension"
    FUNCTION = "function"
    METHOD = "method"
    CONSTRUCTOR = "constructor"
    CONSTANT = "constant"
    TEST = "test"


class FactKind(StrEnum):
    IMPORT = "import"
    EXPORT = "export"
    CALL = "call"
    INHERITS = "inherits"
    IMPLEMENTS = "implements"
    DECORATOR = "decorator"
    ROUTE = "route"
    TESTS = "tests"
    CONFIGURATION = "configuration"


class ChunkKind(StrEnum):
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    TEST = "test"
    MODULE_SUMMARY = "module_summary"


class ParseStatus(StrEnum):
    PENDING = "pending"
    PARSED = "parsed"
    PARSED_WITH_ERRORS = "parsed_with_errors"
    STALE = "stale"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SourceRange:
    start_byte: int
    end_byte: int
    start_line: int
    end_line: int
    start_column: int
    end_column: int


@dataclass(frozen=True, slots=True)
class FileCandidate:
    absolute_path: Path
    relative_path: str
    language: Language
    size_bytes: int
    mtime_ns: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class ScanIssue:
    relative_path: str
    code: str


@dataclass(frozen=True, slots=True)
class ScanResult:
    files: tuple[FileCandidate, ...]
    visited_files: int
    skip_counts: dict[str, int] = field(default_factory=_empty_counts)
    issues: tuple[ScanIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class ExtractedSymbol:
    id: str
    kind: SymbolKind
    name: str
    qualified_name: str
    signature: str
    parameters: tuple[str, ...]
    return_type: str | None
    docstring: str | None
    source_range: SourceRange
    metadata: dict[str, Any] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class SyntaxFact:
    id: str
    kind: FactKind
    target_text: str
    source_range: SourceRange
    source_symbol_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class ExtractedChunk:
    id: str
    kind: ChunkKind
    content_hash: str
    source_text: str
    source_range: SourceRange
    symbol_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    relative_path: str
    language: Language
    symbols: tuple[ExtractedSymbol, ...]
    facts: tuple[SyntaxFact, ...]
    chunks: tuple[ExtractedChunk, ...]
    has_errors: bool
    error_node_count: int
