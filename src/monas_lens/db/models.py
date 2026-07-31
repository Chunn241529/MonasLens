"""Foundation database models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from monas_lens.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class IndexState(StrEnum):
    PENDING = "pending"
    SCANNING = "scanning"
    PARSING = "parsing"
    BUILDING_GRAPH = "building_graph"
    READY = "ready"
    FAILED = "failed"


class RepositoryModel(Base):
    __tablename__ = "repositories"
    __table_args__ = (
        Index(
            "ux_repositories_one_active",
            "is_active",
            unique=True,
            sqlite_where=text("is_active = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    canonical_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_git_repository: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    index_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=IndexState.PENDING.value
    )
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    graph_dirty: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    graph_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class IndexRunModel(Base):
    __tablename__ = "index_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    full_rebuild: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float | None] = mapped_column(Float)
    scanned_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parsed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))


class FileModel(Base):
    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint(
            "repository_id",
            "relative_path",
            name="ux_files_repository_path",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mtime_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    observed_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    indexed_hash: Mapped[str | None] = mapped_column(String(64))
    indexed_extractor_version: Mapped[int | None] = mapped_column(Integer)
    encoding: Mapped[str | None] = mapped_column(String(32))
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False)
    parse_error_code: Mapped[str | None] = mapped_column(String(64))
    parse_error_message: Mapped[str | None] = mapped_column(String(500))
    symbol_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class SymbolModel(Base):
    __tablename__ = "symbols"
    __table_args__ = (
        UniqueConstraint(
            "file_id",
            "local_id",
            name="ux_symbols_file_local_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    local_id: Mapped[str] = mapped_column(String(64), nullable=False)
    file_id: Mapped[str] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    qualified_name: Mapped[str] = mapped_column(Text, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    parameters_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    return_type: Mapped[str | None] = mapped_column(Text)
    docstring: Mapped[str | None] = mapped_column(Text)
    start_byte: Mapped[int] = mapped_column(Integer, nullable=False)
    end_byte: Mapped[int] = mapped_column(Integer, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    start_column: Mapped[int] = mapped_column(Integer, nullable=False)
    end_column: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class ChunkModel(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint(
            "file_id",
            "local_id",
            name="ux_chunks_file_local_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    local_id: Mapped[str] = mapped_column(String(64), nullable=False)
    file_id: Mapped[str] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol_id: Mapped[str | None] = mapped_column(
        ForeignKey("symbols.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    start_byte: Mapped[int] = mapped_column(Integer, nullable=False)
    end_byte: Mapped[int] = mapped_column(Integer, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    start_column: Mapped[int] = mapped_column(Integer, nullable=False)
    end_column: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class SyntaxFactModel(Base):
    __tablename__ = "syntax_facts"
    __table_args__ = (
        UniqueConstraint(
            "file_id",
            "local_id",
            name="ux_syntax_facts_file_local_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    local_id: Mapped[str] = mapped_column(String(64), nullable=False)
    file_id: Mapped[str] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_symbol_id: Mapped[str | None] = mapped_column(
        ForeignKey("symbols.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target_text: Mapped[str] = mapped_column(Text, nullable=False)
    start_byte: Mapped[int] = mapped_column(Integer, nullable=False)
    end_byte: Mapped[int] = mapped_column(Integer, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    start_column: Mapped[int] = mapped_column(Integer, nullable=False)
    end_column: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class SearchDocumentModel(Base):
    __tablename__ = "search_documents"
    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "entity_id",
            name="ux_search_documents_entity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_id: Mapped[str] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    qualified_name: Mapped[str | None] = mapped_column(Text)
    signature: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)


class RelationshipModel(Base):
    __tablename__ = "relationships"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fact_id: Mapped[str] = mapped_column(
        ForeignKey("syntax_facts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_file_id: Mapped[str] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_symbol_id: Mapped[str | None] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), index=True
    )
    target_file_id: Mapped[str] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_symbol_id: Mapped[str | None] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    resolution_strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_target: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_target: Mapped[str] = mapped_column(String(500), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class ResolutionDiagnosticModel(Base):
    __tablename__ = "resolution_diagnostics"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_id: Mapped[str] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fact_id: Mapped[str] = mapped_column(
        ForeignKey("syntax_facts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    fact_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_target: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_target: Mapped[str] = mapped_column(String(500), nullable=False)
    details_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
