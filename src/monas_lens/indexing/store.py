"""Atomic persistence for structural index records."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from monas_lens.db.models import (
    ChunkModel,
    FileModel,
    RepositoryModel,
    SearchDocumentModel,
    SymbolModel,
    SyntaxFactModel,
    utc_now,
)
from monas_lens.db.session import Database
from monas_lens.indexing.contracts import (
    ExtractedSymbol,
    ExtractionResult,
    FileCandidate,
    ParseStatus,
    SourceRange,
)
from monas_lens.indexing.identity import stable_id
from monas_lens.indexing.version import CURRENT_EXTRACTOR_VERSION


@dataclass(frozen=True, slots=True)
class StoredFile:
    id: str
    relative_path: str
    observed_hash: str
    indexed_hash: str | None
    indexed_extractor_version: int | None
    parse_status: ParseStatus
    symbol_count: int
    chunk_count: int
    fact_count: int


@dataclass(frozen=True, slots=True)
class IndexCounts:
    files: int
    symbols: int
    chunks: int
    facts: int
    stale_files: int


class StructuralStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    def files(self, repository_id: str) -> dict[str, StoredFile]:
        with self._database.session() as session:
            models = session.scalars(
                select(FileModel).where(FileModel.repository_id == repository_id)
            ).all()
            return {model.relative_path: _stored_file(model) for model in models}

    def replace_file(
        self,
        repository_id: str,
        candidate: FileCandidate,
        extraction: ExtractionResult,
    ) -> None:
        file_id = stable_id("file", repository_id, candidate.relative_path)
        with self._database.session() as session:
            model = session.get(FileModel, file_id)
            if model is None:
                model = FileModel(
                    id=file_id,
                    repository_id=repository_id,
                    relative_path=candidate.relative_path,
                    language=candidate.language.value,
                    size_bytes=candidate.size_bytes,
                    mtime_ns=candidate.mtime_ns,
                    observed_hash=candidate.content_hash,
                    indexed_hash=None,
                    encoding="utf-8",
                    parse_status=ParseStatus.PENDING.value,
                )
                session.add(model)
                session.flush()
            else:
                session.execute(
                    delete(SearchDocumentModel).where(SearchDocumentModel.file_id == file_id)
                )
                session.execute(delete(ChunkModel).where(ChunkModel.file_id == file_id))
                session.execute(delete(SyntaxFactModel).where(SyntaxFactModel.file_id == file_id))
                session.execute(delete(SymbolModel).where(SymbolModel.file_id == file_id))

            symbol_ids = {
                symbol.id: stable_id("db-symbol", repository_id, symbol.id)
                for symbol in extraction.symbols
            }
            session.add_all(
                [
                    _symbol_model(
                        repository_id,
                        file_id,
                        candidate,
                        symbol,
                    )
                    for symbol in extraction.symbols
                ]
            )
            session.flush()
            session.add_all(
                [
                    ChunkModel(
                        id=stable_id("db-chunk", repository_id, chunk.id),
                        local_id=chunk.id,
                        file_id=file_id,
                        symbol_id=(
                            symbol_ids.get(chunk.symbol_id) if chunk.symbol_id is not None else None
                        ),
                        kind=chunk.kind.value,
                        content_hash=chunk.content_hash,
                        source_text=chunk.source_text,
                        **_range_values(chunk.source_range),
                        metadata_json=chunk.metadata,
                    )
                    for chunk in extraction.chunks
                ]
            )
            session.add_all(
                [
                    SyntaxFactModel(
                        id=stable_id("db-fact", repository_id, fact.id),
                        local_id=fact.id,
                        file_id=file_id,
                        source_symbol_id=(
                            symbol_ids.get(fact.source_symbol_id)
                            if fact.source_symbol_id is not None
                            else None
                        ),
                        kind=fact.kind.value,
                        target_text=fact.target_text,
                        **_range_values(fact.source_range),
                        metadata_json=fact.metadata,
                    )
                    for fact in extraction.facts
                ]
            )
            session.add_all(
                _search_documents(
                    repository_id,
                    file_id,
                    candidate,
                    extraction,
                    symbol_ids,
                )
            )
            model.language = candidate.language.value
            model.size_bytes = candidate.size_bytes
            model.mtime_ns = candidate.mtime_ns
            model.observed_hash = candidate.content_hash
            model.indexed_hash = candidate.content_hash
            model.indexed_extractor_version = CURRENT_EXTRACTOR_VERSION
            model.encoding = "utf-8"
            model.parse_status = (
                ParseStatus.PARSED_WITH_ERRORS.value
                if extraction.has_errors
                else ParseStatus.PARSED.value
            )
            model.parse_error_code = "tree_sitter_error_nodes" if extraction.has_errors else None
            model.parse_error_message = (
                f"{extraction.error_node_count} syntax error node(s)"
                if extraction.has_errors
                else None
            )
            model.symbol_count = len(extraction.symbols)
            model.chunk_count = len(extraction.chunks)
            model.fact_count = len(extraction.facts)
            model.indexed_at = utc_now()
            _mark_graph_dirty(session, repository_id)
            session.commit()

    def record_failure(
        self,
        repository_id: str,
        candidate: FileCandidate,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        file_id = stable_id("file", repository_id, candidate.relative_path)
        with self._database.session() as session:
            model = session.get(FileModel, file_id)
            if model is None:
                model = FileModel(
                    id=file_id,
                    repository_id=repository_id,
                    relative_path=candidate.relative_path,
                    language=candidate.language.value,
                    size_bytes=candidate.size_bytes,
                    mtime_ns=candidate.mtime_ns,
                    observed_hash=candidate.content_hash,
                    indexed_hash=None,
                    encoding=None,
                    parse_status=ParseStatus.FAILED.value,
                )
                session.add(model)
            else:
                model.language = candidate.language.value
                model.size_bytes = candidate.size_bytes
                model.mtime_ns = candidate.mtime_ns
                model.observed_hash = candidate.content_hash
                model.parse_status = (
                    ParseStatus.STALE.value
                    if model.indexed_hash is not None
                    else ParseStatus.FAILED.value
                )
            model.parse_error_code = error_code[:64]
            model.parse_error_message = error_message[:500]
            session.commit()

    def delete_file(self, repository_id: str, relative_path: str) -> bool:
        with self._database.session() as session:
            model = session.scalar(
                select(FileModel).where(
                    FileModel.repository_id == repository_id,
                    FileModel.relative_path == relative_path,
                )
            )
            if model is None:
                return False
            session.delete(model)
            _mark_graph_dirty(session, repository_id)
            session.commit()
            return True

    def counts(self, repository_id: str) -> IndexCounts:
        with self._database.session() as session:
            file_ids = select(FileModel.id).where(FileModel.repository_id == repository_id)
            files = session.scalar(
                select(func.count())
                .select_from(FileModel)
                .where(FileModel.repository_id == repository_id)
            )
            symbols = session.scalar(
                select(func.count())
                .select_from(SymbolModel)
                .where(SymbolModel.file_id.in_(file_ids))
            )
            chunks = session.scalar(
                select(func.count()).select_from(ChunkModel).where(ChunkModel.file_id.in_(file_ids))
            )
            facts = session.scalar(
                select(func.count())
                .select_from(SyntaxFactModel)
                .where(SyntaxFactModel.file_id.in_(file_ids))
            )
            stale_files = session.scalar(
                select(func.count())
                .select_from(FileModel)
                .where(
                    FileModel.repository_id == repository_id,
                    FileModel.parse_status.in_([ParseStatus.STALE.value, ParseStatus.FAILED.value]),
                )
            )
        return IndexCounts(
            files=files or 0,
            symbols=symbols or 0,
            chunks=chunks or 0,
            facts=facts or 0,
            stale_files=stale_files or 0,
        )


def _stored_file(model: FileModel) -> StoredFile:
    return StoredFile(
        id=model.id,
        relative_path=model.relative_path,
        observed_hash=model.observed_hash,
        indexed_hash=model.indexed_hash,
        indexed_extractor_version=model.indexed_extractor_version,
        parse_status=ParseStatus(model.parse_status),
        symbol_count=model.symbol_count,
        chunk_count=model.chunk_count,
        fact_count=model.fact_count,
    )


def _symbol_model(
    repository_id: str,
    file_id: str,
    candidate: FileCandidate,
    symbol: ExtractedSymbol,
) -> SymbolModel:
    return SymbolModel(
        id=stable_id("db-symbol", repository_id, symbol.id),
        local_id=symbol.id,
        file_id=file_id,
        language=candidate.language.value,
        kind=symbol.kind.value,
        name=symbol.name,
        qualified_name=symbol.qualified_name,
        signature=symbol.signature,
        parameters_json=list(symbol.parameters),
        return_type=symbol.return_type,
        docstring=symbol.docstring,
        **_range_values(symbol.source_range),
        metadata_json=symbol.metadata,
    )


def _search_documents(
    repository_id: str,
    file_id: str,
    candidate: FileCandidate,
    extraction: ExtractionResult,
    symbol_ids: dict[str, str],
) -> list[SearchDocumentModel]:
    symbols_by_id = {symbol.id: symbol for symbol in extraction.symbols}
    end_line = max(
        (
            item.source_range.end_line
            for item in (*extraction.symbols, *extraction.chunks, *extraction.facts)
        ),
        default=1,
    )
    documents = [
        SearchDocumentModel(
            repository_id=repository_id,
            file_id=file_id,
            entity_type="file",
            entity_id=file_id,
            language=candidate.language.value,
            kind="file",
            relative_path=candidate.relative_path,
            body="",
            start_line=1,
            end_line=end_line,
        )
    ]
    documents.extend(
        SearchDocumentModel(
            repository_id=repository_id,
            file_id=file_id,
            entity_type="symbol",
            entity_id=symbol_ids[symbol.id],
            language=candidate.language.value,
            kind=symbol.kind.value,
            relative_path=candidate.relative_path,
            name=symbol.name,
            qualified_name=symbol.qualified_name,
            signature=symbol.signature,
            body=symbol.docstring or "",
            start_line=symbol.source_range.start_line,
            end_line=symbol.source_range.end_line,
        )
        for symbol in extraction.symbols
    )
    for chunk in extraction.chunks:
        owner = symbols_by_id.get(chunk.symbol_id) if chunk.symbol_id is not None else None
        documents.append(
            SearchDocumentModel(
                repository_id=repository_id,
                file_id=file_id,
                entity_type="chunk",
                entity_id=stable_id("db-chunk", repository_id, chunk.id),
                language=candidate.language.value,
                kind=chunk.kind.value,
                relative_path=candidate.relative_path,
                name=owner.name if owner is not None else None,
                qualified_name=owner.qualified_name if owner is not None else None,
                signature=owner.signature if owner is not None else None,
                body=chunk.source_text,
                start_line=chunk.source_range.start_line,
                end_line=chunk.source_range.end_line,
            )
        )
    documents.extend(
        SearchDocumentModel(
            repository_id=repository_id,
            file_id=file_id,
            entity_type="fact",
            entity_id=stable_id("db-fact", repository_id, fact.id),
            language=candidate.language.value,
            kind=fact.kind.value,
            relative_path=candidate.relative_path,
            body=fact.target_text,
            start_line=fact.source_range.start_line,
            end_line=fact.source_range.end_line,
        )
        for fact in extraction.facts
    )
    return documents


def _range_values(source_range: SourceRange) -> dict[str, int]:
    return {
        "start_byte": source_range.start_byte,
        "end_byte": source_range.end_byte,
        "start_line": source_range.start_line,
        "end_line": source_range.end_line,
        "start_column": source_range.start_column,
        "end_column": source_range.end_column,
    }


def _mark_graph_dirty(session: Session, repository_id: str) -> None:
    repository = session.get(RepositoryModel, repository_id)
    if repository is not None:
        repository.graph_dirty = True
