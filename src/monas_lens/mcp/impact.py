"""Bounded patch-impact analysis over indexed structure and working-tree diff."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import or_, select

from monas_lens.config import Settings
from monas_lens.db.models import FileModel, RelationshipModel, SymbolModel
from monas_lens.db.session import Database
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.graph.contracts import RelationKind
from monas_lens.mcp.contracts import (
    ImpactNode,
    ImpactRisk,
    ImpactSymbol,
    PatchImpact,
)
from monas_lens.repositories import RepositoryService
from monas_lens.retrieval.compiler import ContextCompiler
from monas_lens.retrieval.retriever import (
    GitDiffAdapterProtocol,
    GitDiffHunk,
    SubprocessGitDiffAdapter,
)
from monas_lens.retrieval.validation import (
    normalize_repository_relative_path,
    suggest_repository_validation_commands,
)

_CALLER_RELATIONS = frozenset(
    {RelationKind.CALLS.value, RelationKind.INHERITS.value, RelationKind.IMPLEMENTS.value}
)


class PatchImpactAnalyzer:
    """Report direct structural impact for the bounded current Git diff."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        git_diff_adapter: GitDiffAdapterProtocol | None = None,
        compiler: ContextCompiler | None = None,
    ) -> None:
        self._database = database
        self._settings = settings
        self._repositories = RepositoryService(database, settings)
        self._git_diff_adapter = git_diff_adapter or SubprocessGitDiffAdapter(
            timeout_seconds=settings.context_git_diff_timeout_seconds,
            max_bytes=settings.context_git_diff_max_bytes,
        )
        self._compiler = compiler or ContextCompiler(database, settings)

    def analyze(
        self,
        repository: str | Path | None = None,
        *,
        task: str | None = None,
        expected_paths: Sequence[str] = (),
    ) -> PatchImpact:
        selected = (
            self._repositories.active()
            if repository is None
            else self._repositories.get(repository)
        )
        if not selected.is_git_repository:
            raise MonasLensError(
                ErrorCode.PATCH_IMPACT_FAILED,
                "Patch impact analysis requires a registered Git repository.",
            )
        try:
            diff = self._git_diff_adapter.collect(
                selected.canonical_path,
                max_hunks=self._settings.context_max_git_entries,
            )
        except (OSError, ValueError) as exc:
            raise MonasLensError(
                ErrorCode.PATCH_IMPACT_FAILED,
                "The current Git diff could not be analyzed.",
            ) from exc

        changed_paths = tuple(sorted({hunk.relative_path for hunk in diff.hunks}))
        symbols, languages = self._changed_symbols(selected.id, diff.hunks)
        callers, tests = self._related_nodes(selected.id, symbols)
        routes = self._route_symbols(selected.id, symbols)
        schemas = tuple(symbol for symbol in symbols if _is_schema(symbol))
        relevant_paths, diagnostics = self._relevant_paths(
            selected.id,
            task,
            expected_paths,
        )
        unrelated = (
            tuple(path for path in changed_paths if path not in relevant_paths)
            if relevant_paths
            else ()
        )
        risks = _impact_risks(
            symbols,
            routes,
            schemas,
            tests,
            unrelated,
            diff.truncated,
        )
        validations = suggest_repository_validation_commands(
            selected.canonical_path,
            languages,
        )
        return PatchImpact(
            repository_id=selected.id,
            changed_paths=changed_paths,
            changed_symbols=symbols,
            affected_callers=callers,
            routes=routes,
            schemas=schemas,
            tests=tests,
            risks=risks,
            validation_commands=validations,
            unrelated_changes=unrelated,
            diagnostics=diagnostics,
            truncated=diff.truncated,
        )

    def _changed_symbols(
        self,
        repository_id: str,
        hunks: Sequence[GitDiffHunk],
    ) -> tuple[tuple[ImpactSymbol, ...], tuple[str, ...]]:
        paths = sorted({hunk.relative_path for hunk in hunks})
        if not paths:
            return (), ()
        with self._database.session() as session:
            files = session.scalars(
                select(FileModel)
                .where(
                    FileModel.repository_id == repository_id,
                    FileModel.relative_path.in_(paths),
                )
                .order_by(FileModel.relative_path, FileModel.id)
            ).all()
            indexed_symbols = session.scalars(
                select(SymbolModel)
                .where(SymbolModel.file_id.in_([file.id for file in files]))
                .order_by(SymbolModel.file_id, SymbolModel.start_line, SymbolModel.id)
            ).all()
        changed_ranges: dict[str, list[tuple[int, int]]] = {}
        for hunk in hunks:
            changed_ranges.setdefault(hunk.relative_path, []).append(_hunk_range(hunk))
        file_by_id = {file.id: file for file in files}
        selected_symbols: list[ImpactSymbol] = []
        for symbol in indexed_symbols:
            file = file_by_id.get(symbol.file_id)
            if file is None or not any(
                symbol.start_line <= end and symbol.end_line >= start
                for start, end in changed_ranges.get(file.relative_path, ())
            ):
                continue
            selected_symbols.append(
                ImpactSymbol(
                    id=symbol.id,
                    qualified_name=symbol.qualified_name,
                    relative_path=file.relative_path,
                    language=symbol.language,
                    kind=symbol.kind,
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                )
            )
        languages = tuple(sorted({file.language for file in files}))
        return tuple(selected_symbols), languages

    def _route_symbols(
        self,
        repository_id: str,
        symbols: Sequence[ImpactSymbol],
    ) -> tuple[ImpactSymbol, ...]:
        if not symbols:
            return ()
        with self._database.session() as session:
            indexed = session.scalars(
                select(SymbolModel)
                .join(FileModel, FileModel.id == SymbolModel.file_id)
                .where(
                    FileModel.repository_id == repository_id,
                    SymbolModel.id.in_([symbol.id for symbol in symbols]),
                )
            ).all()
        route_ids = {
            symbol.id for symbol in indexed if symbol.metadata_json.get("is_route") is True
        }
        return tuple(symbol for symbol in symbols if symbol.id in route_ids)

    def _related_nodes(
        self,
        repository_id: str,
        symbols: Sequence[ImpactSymbol],
    ) -> tuple[tuple[ImpactNode, ...], tuple[ImpactNode, ...]]:
        symbol_ids = [symbol.id for symbol in symbols]
        if not symbol_ids:
            return (), ()
        with self._database.session() as session:
            edges = session.scalars(
                select(RelationshipModel)
                .where(
                    RelationshipModel.repository_id == repository_id,
                    or_(
                        RelationshipModel.target_symbol_id.in_(symbol_ids),
                        RelationshipModel.source_symbol_id.in_(symbol_ids),
                    ),
                )
                .order_by(RelationshipModel.kind, RelationshipModel.id)
            ).all()
            caller_ids = {
                edge.source_symbol_id
                for edge in edges
                if edge.target_symbol_id in symbol_ids
                and edge.kind in _CALLER_RELATIONS
                and edge.source_symbol_id is not None
            }
            test_symbol_ids = {
                edge.target_symbol_id
                for edge in edges
                if edge.source_symbol_id in symbol_ids
                and edge.kind == RelationKind.TESTED_BY.value
                and edge.target_symbol_id is not None
            }
            related_ids = sorted(caller_ids | test_symbol_ids)
            related_symbols = session.scalars(
                select(SymbolModel).where(SymbolModel.id.in_(related_ids)).order_by(SymbolModel.id)
            ).all()
            file_ids = sorted({symbol.file_id for symbol in related_symbols})
            files = session.scalars(
                select(FileModel).where(FileModel.id.in_(file_ids)).order_by(FileModel.id)
            ).all()
        file_by_id = {file.id: file for file in files}
        nodes = {
            symbol.id: ImpactNode(
                id=symbol.id,
                node_type="symbol",
                relative_path=file_by_id[symbol.file_id].relative_path,
                language=symbol.language,
                kind=symbol.kind,
                qualified_name=symbol.qualified_name,
                start_line=symbol.start_line,
            )
            for symbol in related_symbols
            if symbol.file_id in file_by_id
        }
        return (
            tuple(nodes[item] for item in sorted(caller_ids) if item in nodes),
            tuple(nodes[item] for item in sorted(test_symbol_ids) if item in nodes),
        )

    def _relevant_paths(
        self,
        repository_id: str,
        task: str | None,
        expected_paths: Sequence[str],
    ) -> tuple[frozenset[str], tuple[str, ...]]:
        selected = {
            normalized
            for value in expected_paths
            if (normalized := normalize_repository_relative_path(value)) is not None
        }
        diagnostics: list[str] = []
        if task and task.strip():
            try:
                bundle = self._compiler.resolve(
                    {
                        "task": task,
                        "repository": repository_id,
                        "max_tokens": min(2_000, self._settings.context_max_total_tokens),
                        "include_git_diff": False,
                    }
                )
                selected.update(snippet.relative_path for snippet in bundle.snippets)
            except MonasLensError:
                diagnostics.append("task_context_unavailable")
        return frozenset(selected), tuple(diagnostics)


def _hunk_range(hunk: GitDiffHunk) -> tuple[int, int]:
    new_lines = sum(
        1
        for line in hunk.content.splitlines()[1:]
        if not line.startswith("-") and not line.startswith("\\")
    )
    return hunk.new_start_line, hunk.new_start_line + max(new_lines - 1, 0)


def _is_schema(symbol: ImpactSymbol) -> bool:
    name = symbol.qualified_name.rsplit(".", 1)[-1].lower()
    return symbol.kind in {"class", "interface"} and name.endswith(
        ("schema", "request", "response", "model", "dto")
    )


def _impact_risks(
    symbols: Sequence[ImpactSymbol],
    routes: Sequence[ImpactSymbol],
    schemas: Sequence[ImpactSymbol],
    tests: Sequence[ImpactNode],
    unrelated: Sequence[str],
    truncated: bool,
) -> tuple[ImpactRisk, ...]:
    risks: list[ImpactRisk] = []
    if symbols and not tests:
        risks.append(
            ImpactRisk(
                code="missing_regression_test",
                severity="warning",
                message="Changed indexed symbols have no directly related indexed test.",
            )
        )
    if routes:
        risks.append(
            ImpactRisk(
                code="route_contract_changed",
                severity="warning",
                message="A changed symbol is marked as an application route.",
                relative_path=routes[0].relative_path,
            )
        )
    if schemas:
        risks.append(
            ImpactRisk(
                code="schema_contract_changed",
                severity="warning",
                message="A changed symbol appears to define a serialized schema contract.",
                relative_path=schemas[0].relative_path,
            )
        )
    for path in unrelated:
        risks.append(
            ImpactRisk(
                code="unrelated_change",
                severity="warning",
                message="A changed path was outside the supplied task context.",
                relative_path=path,
            )
        )
    if truncated:
        risks.append(
            ImpactRisk(
                code="analysis_truncated",
                severity="warning",
                message="The bounded Git diff was truncated before all hunks were analyzed.",
            )
        )
    return tuple(sorted(risks, key=lambda item: (item.code, item.relative_path or "")))
