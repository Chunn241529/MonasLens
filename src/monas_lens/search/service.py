"""Typed exact-symbol and SQLite FTS5 repository search."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select, text
from sqlalchemy.engine import RowMapping

from monas_lens.config import Settings
from monas_lens.db.models import SearchDocumentModel
from monas_lens.db.session import Database
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.repositories import RepositoryRecord, RepositoryService

_MAX_QUERY_LENGTH = 500
_MAX_QUERY_TERMS = 20
_MAX_RESULTS = 100
_TERM_PATTERN = re.compile(r"\w+", flags=re.UNICODE)
_EXACT_SINGLE_WORD_DISCOUNT = 0.50


class SearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity_type: str
    entity_id: str
    relative_path: str
    language: str
    kind: str
    name: str | None
    qualified_name: str | None
    signature: str | None
    snippet: str
    start_line: int
    end_line: int
    match_type: Literal["exact", "fts"]
    score: float


class SearchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository_id: str
    query: str
    total: int
    results: tuple[SearchResult, ...]


class SearchService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self._database = database
        self._repositories = RepositoryService(database, settings)

    def search(
        self,
        query: str,
        identifier: str | Path | None = None,
        *,
        limit: int = 20,
    ) -> SearchResponse:
        normalized_query = query.strip()
        expression = _fts_expression(normalized_query)
        query_terms = _TERM_PATTERN.findall(normalized_query)[:_MAX_QUERY_TERMS]
        if not 1 <= limit <= _MAX_RESULTS:
            raise MonasLensError(
                ErrorCode.SEARCH_QUERY_INVALID,
                f"Search limit must be between 1 and {_MAX_RESULTS}.",
            )
        repository = self._resolve_repository(identifier)
        exact_results = self._exact_symbol_results(repository.id, normalized_query, limit)
        selected = list(exact_results)
        seen = {(result.entity_type, result.entity_id) for result in selected}
        if len(selected) < limit:
            for result in self._fts_results(repository.id, expression, query_terms, limit * 2):
                key = (result.entity_type, result.entity_id)
                if key in seen:
                    continue
                selected.append(result)
                seen.add(key)
                if len(selected) == limit:
                    break
        return SearchResponse(
            repository_id=repository.id,
            query=normalized_query,
            total=len(selected),
            results=tuple(selected),
        )

    def _resolve_repository(self, identifier: str | Path | None) -> RepositoryRecord:
        return (
            self._repositories.active()
            if identifier is None
            else self._repositories.get(identifier)
        )

    def _exact_symbol_results(
        self,
        repository_id: str,
        query: str,
        limit: int,
    ) -> tuple[SearchResult, ...]:
        is_single_word = "." not in query and " " not in query
        with self._database.session() as session:
            documents = session.scalars(
                select(SearchDocumentModel)
                .where(
                    SearchDocumentModel.repository_id == repository_id,
                    SearchDocumentModel.entity_type == "symbol",
                    or_(
                        SearchDocumentModel.name == query,
                        SearchDocumentModel.qualified_name == query,
                    ),
                )
                .order_by(
                    SearchDocumentModel.qualified_name,
                    SearchDocumentModel.relative_path,
                    SearchDocumentModel.start_line,
                )
                .limit(limit)
            ).all()
        results: list[SearchResult] = []
        for document in documents:
            base_score = 1.0 if document.qualified_name == query else 0.98
            # ponytail: single-word discount prevents generic identifiers (model, name) from
            # outranking path-concordant FTS hits. Upgrade path: per-language stopword list or
            # IDF-based term rarity scoring.
            if is_single_word:
                base_score *= _EXACT_SINGLE_WORD_DISCOUNT
            results.append(_model_result(document, match_type="exact", score=base_score))
        return tuple(results)

    def _fts_results(
        self,
        repository_id: str,
        expression: str,
        query_terms: Sequence[str],
        limit: int,
    ) -> tuple[SearchResult, ...]:
        statement = text(
            """
            SELECT
                d.entity_type,
                d.entity_id,
                d.relative_path,
                d.language,
                d.kind,
                d.name,
                d.qualified_name,
                d.signature,
                d.start_line,
                d.end_line,
                bm25(search_documents_fts, 2.0, 8.0, 6.0, 4.0, 1.0) AS rank,
                snippet(search_documents_fts, 4, '[', ']', ' … ', 18) AS snippet
            FROM search_documents_fts
            JOIN search_documents AS d
                ON d.id = search_documents_fts.rowid
            WHERE search_documents_fts MATCH :expression
                AND d.repository_id = :repository_id
            ORDER BY
                rank,
                d.relative_path,
                d.start_line,
                d.entity_type,
                d.entity_id
            LIMIT :limit
            """
        )
        with self._database.session() as session:
            rows = (
                session.execute(
                    statement,
                    {
                        "expression": expression,
                        "repository_id": repository_id,
                        "limit": limit,
                    },
                )
                .mappings()
                .all()
            )
        return tuple(_row_result(row, query_terms) for row in rows)


def _fts_expression(query: str) -> str:
    if not query:
        raise MonasLensError(
            ErrorCode.SEARCH_QUERY_INVALID,
            "Search query must not be empty.",
        )
    if len(query) > _MAX_QUERY_LENGTH:
        raise MonasLensError(
            ErrorCode.SEARCH_QUERY_INVALID,
            f"Search query must not exceed {_MAX_QUERY_LENGTH} characters.",
        )
    terms = _TERM_PATTERN.findall(query)[:_MAX_QUERY_TERMS]
    if not terms:
        raise MonasLensError(
            ErrorCode.SEARCH_QUERY_INVALID,
            "Search query must contain at least one letter or number.",
        )
    return " AND ".join(f'"{term}"*' for term in terms)


def _model_result(
    document: SearchDocumentModel,
    *,
    match_type: Literal["exact", "fts"],
    score: float,
) -> SearchResult:
    return SearchResult(
        entity_type=document.entity_type,
        entity_id=document.entity_id,
        relative_path=document.relative_path,
        language=document.language,
        kind=document.kind,
        name=document.name,
        qualified_name=document.qualified_name,
        signature=document.signature,
        snippet=_fallback_snippet(
            document.body,
            document.signature,
            document.qualified_name,
            document.name,
            document.relative_path,
        ),
        start_line=document.start_line,
        end_line=document.end_line,
        match_type=match_type,
        score=score,
    )


def _row_result(row: RowMapping, query_terms: Sequence[str] = ()) -> SearchResult:
    rank = float(row["rank"])
    relevance = max(-rank, 0.0)
    snippet = _string_or_none(row["snippet"])
    relative_path = str(row["relative_path"])
    base_score = round(0.75 + (0.2 * relevance / (1.0 + relevance)), 6)
    return SearchResult(
        entity_type=str(row["entity_type"]),
        entity_id=str(row["entity_id"]),
        relative_path=relative_path,
        language=str(row["language"]),
        kind=str(row["kind"]),
        name=_string_or_none(row["name"]),
        qualified_name=_string_or_none(row["qualified_name"]),
        signature=_string_or_none(row["signature"]),
        snippet=_fallback_snippet(
            snippet,
            _string_or_none(row["signature"]),
            _string_or_none(row["qualified_name"]),
            _string_or_none(row["name"]),
            relative_path,
        ),
        start_line=int(row["start_line"]),
        end_line=int(row["end_line"]),
        match_type="fts",
        score=base_score,
    )


def _string_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _fallback_snippet(*values: str | None) -> str:
    selected = next((value for value in values if value), "")
    compact = " ".join(selected.split())
    return compact if len(compact) <= 300 else f"{compact[:297]}..."
