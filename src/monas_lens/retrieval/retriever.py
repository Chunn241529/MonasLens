"""Bounded, deterministic two-stage context retrieval."""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, runtime_checkable

from sqlalchemy import or_, select

from monas_lens.config import Settings
from monas_lens.db.models import ChunkModel, FileModel
from monas_lens.db.session import Database
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.graph.contracts import GraphDirection, RelationKind
from monas_lens.graph.service import GraphEdge, GraphNode, GraphResponse, GraphService
from monas_lens.repositories import RepositoryService
from monas_lens.retrieval.contracts import (
    CandidateRole,
    DiagnosticSeverity,
    EntityType,
    EvidenceKind,
    RetrievalCandidate,
    RetrievalDiagnostic,
    RetrievalDiagnosticCode,
    RetrievalEvidence,
    TaskResolution,
)
from monas_lens.search.service import SearchResponse, SearchResult, SearchService

type CandidateIdentity = tuple[str, EntityType, str]

_SEARCH_QUERY_MAX_CHARS = 500
_SEARCH_RESULT_LIMIT = 20
_MAX_EVIDENCE_PER_CANDIDATE = 32
_GRAPH_ORDINAL_STRIDE = 100
_GIT_DIFF_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_ROLE_PRIORITY = {
    CandidateRole.PRIMARY: 0,
    CandidateRole.INTERFACE: 1,
    CandidateRole.SCHEMA: 2,
    CandidateRole.CONFIGURATION: 3,
    CandidateRole.DEPENDENCY: 4,
    CandidateRole.CALLER: 5,
    CandidateRole.TEST: 6,
    CandidateRole.GIT_DIFF: 7,
}


@runtime_checkable
class SearchAdapterProtocol(Protocol):
    """Detached search results produced inside one retrieval worker."""

    def search(self, query: str, repository_id: str, *, limit: int) -> SearchResponse: ...


@runtime_checkable
class GraphAdapterProtocol(Protocol):
    """Detached graph results produced inside one retrieval worker."""

    def expand(
        self,
        target: str,
        repository_id: str,
        *,
        direction: GraphDirection,
        relation_kinds: frozenset[RelationKind],
        depth: int,
        limit: int,
    ) -> GraphResponse: ...


@runtime_checkable
class IndexedChunkLookupProtocol(Protocol):
    """Repository-scoped lookup for narrow indexed chunks."""

    def lookup(
        self,
        repository_id: str,
        candidates: Sequence[RetrievalCandidate],
    ) -> tuple[IndexedChunk, ...]: ...


@runtime_checkable
class GitDiffAdapterProtocol(Protocol):
    """Optional bounded current-working-tree diff lookup."""

    def collect(self, repository_root: Path, *, max_hunks: int) -> GitDiffResult: ...


@dataclass(frozen=True, slots=True)
class IndexedChunk:
    candidate_identity: CandidateIdentity
    chunk_id: str
    file_id: str
    relative_path: str
    language: str
    kind: str
    content_hash: str
    source_text: str
    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class GitDiffHunk:
    relative_path: str
    old_start_line: int
    new_start_line: int
    content: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class GitDiffResult:
    hunks: tuple[GitDiffHunk, ...] = ()
    truncated: bool = False
    invalid_paths: int = 0


@dataclass(frozen=True, slots=True)
class RetrievalBatch:
    repository_id: str
    candidates: tuple[RetrievalCandidate, ...]
    primary_seeds: tuple[RetrievalCandidate, ...]
    diagnostics: tuple[RetrievalDiagnostic, ...]
    git_diff_hunks: tuple[GitDiffHunk, ...] = ()
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class RetrievalExpansion:
    candidates: tuple[RetrievalCandidate, ...]
    diagnostics: tuple[RetrievalDiagnostic, ...] = ()
    truncated: bool = False


class SearchServiceAdapter:
    """Adapter that constructs a session-owning search service per worker."""

    def __init__(self, database: Database, settings: Settings) -> None:
        self._database = database
        self._settings = settings

    def search(self, query: str, repository_id: str, *, limit: int) -> SearchResponse:
        return SearchService(self._database, self._settings).search(
            query,
            repository_id,
            limit=limit,
        )


class GraphServiceAdapter:
    """Adapter that constructs a session-owning graph service per worker."""

    def __init__(self, database: Database, settings: Settings) -> None:
        self._database = database
        self._settings = settings

    def expand(
        self,
        target: str,
        repository_id: str,
        *,
        direction: GraphDirection,
        relation_kinds: frozenset[RelationKind],
        depth: int,
        limit: int,
    ) -> GraphResponse:
        service = GraphService(self._database, self._settings)
        if depth == 1:
            return service.neighbors(
                target,
                repository_id,
                direction=direction,
                relation_kinds=relation_kinds,
                limit=limit,
            )
        return service.traverse(
            target,
            repository_id,
            direction=direction,
            relation_kinds=relation_kinds,
            depth=depth,
            limit=limit,
        )


class IndexedChunkLookupAdapter:
    """Resolve each candidate to its narrowest repository-scoped indexed chunk."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def lookup(
        self,
        repository_id: str,
        candidates: Sequence[RetrievalCandidate],
    ) -> tuple[IndexedChunk, ...]:
        if any(candidate.repository_id != repository_id for candidate in candidates):
            raise MonasLensError(
                ErrorCode.CONTEXT_RETRIEVAL_FAILED,
                "Chunk lookup candidates must belong to the selected repository.",
            )
        if not candidates:
            return ()

        relative_paths = sorted({candidate.relative_path for candidate in candidates})
        file_ids = sorted(
            {
                candidate.entity_id
                for candidate in candidates
                if candidate.entity_type is EntityType.FILE
            }
        )
        with self._database.session() as session:
            files = session.scalars(
                select(FileModel)
                .where(
                    FileModel.repository_id == repository_id,
                    or_(
                        FileModel.relative_path.in_(relative_paths),
                        FileModel.id.in_(file_ids),
                    ),
                )
                .order_by(FileModel.relative_path, FileModel.id)
            ).all()
            selected_file_ids = [file.id for file in files]
            if not selected_file_ids:
                return ()
            chunks = session.scalars(
                select(ChunkModel)
                .where(ChunkModel.file_id.in_(selected_file_ids))
                .order_by(
                    ChunkModel.file_id,
                    ChunkModel.start_line,
                    ChunkModel.end_line,
                    ChunkModel.id,
                )
            ).all()

        file_by_id = {file.id: file for file in files}
        files_by_path = {file.relative_path: file for file in files}
        chunks_by_file: dict[str, list[ChunkModel]] = {}
        for chunk in chunks:
            chunks_by_file.setdefault(chunk.file_id, []).append(chunk)

        selected: list[IndexedChunk] = []
        for candidate in candidates:
            file = (
                file_by_id.get(candidate.entity_id)
                if candidate.entity_type is EntityType.FILE
                else files_by_path.get(candidate.relative_path)
            )
            if file is None:
                continue
            chunk = _select_chunk(candidate, chunks_by_file.get(file.id, []))
            if chunk is None:
                continue
            selected.append(
                IndexedChunk(
                    candidate_identity=candidate.identity,
                    chunk_id=chunk.id,
                    file_id=file.id,
                    relative_path=file.relative_path,
                    language=file.language,
                    kind=chunk.kind,
                    content_hash=chunk.content_hash,
                    source_text=chunk.source_text,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                )
            )
        return tuple(selected)


class SubprocessGitDiffAdapter:
    """Collect a fixed-argument, repository-rooted and bounded Git diff."""

    def __init__(self, *, timeout_seconds: float, max_bytes: int) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes

    def collect(self, repository_root: Path, *, max_hunks: int) -> GitDiffResult:
        if max_hunks <= 0:
            return GitDiffResult()
        selected_root = repository_root.resolve(strict=True)
        if not selected_root.is_dir():
            raise OSError("Git diff root is not a directory.")
        completed = subprocess.run(
            (
                "git",
                "diff",
                "--no-ext-diff",
                "--no-color",
                "--unified=3",
                "HEAD",
                "--",
            ),
            cwd=selected_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=self._timeout_seconds,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            raise OSError("Git diff exited unsuccessfully.")
        output = completed.stdout
        output_truncated = len(output) > self._max_bytes
        bounded_output = output[: self._max_bytes]
        parsed = _parse_git_diff(bounded_output.decode("utf-8", errors="replace"), max_hunks)
        return GitDiffResult(
            hunks=parsed.hunks,
            truncated=output_truncated or parsed.truncated,
            invalid_paths=parsed.invalid_paths,
        )


@dataclass(frozen=True, slots=True)
class _GraphBranch:
    role: CandidateRole
    direction: GraphDirection
    relation_kinds: frozenset[RelationKind]
    limit_setting: str


@dataclass(frozen=True, slots=True)
class _GraphJob:
    ordinal: int
    seed: RetrievalCandidate
    branch: _GraphBranch
    limit: int


_GRAPH_BRANCHES = (
    _GraphBranch(
        CandidateRole.CALLER,
        GraphDirection.INCOMING,
        frozenset({RelationKind.CALLS}),
        "context_max_caller_snippets",
    ),
    _GraphBranch(
        CandidateRole.DEPENDENCY,
        GraphDirection.OUTGOING,
        frozenset({RelationKind.CALLS, RelationKind.IMPORTS}),
        "context_max_dependency_snippets",
    ),
    _GraphBranch(
        CandidateRole.INTERFACE,
        GraphDirection.OUTGOING,
        frozenset({RelationKind.INHERITS, RelationKind.IMPLEMENTS}),
        "context_max_dependency_snippets",
    ),
    _GraphBranch(
        CandidateRole.TEST,
        GraphDirection.OUTGOING,
        frozenset({RelationKind.TESTED_BY}),
        "context_max_test_snippets",
    ),
    _GraphBranch(
        CandidateRole.CONFIGURATION,
        GraphDirection.OUTGOING,
        frozenset({RelationKind.CONFIGURED_BY}),
        "context_max_dependency_snippets",
    ),
)


class ParallelRetriever:
    """Run bounded lexical discovery and graph fan-out with stable merging."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        search_adapter_factory: Callable[[], SearchAdapterProtocol] | None = None,
        graph_adapter_factory: Callable[[], GraphAdapterProtocol] | None = None,
        git_diff_adapter: GitDiffAdapterProtocol | None = None,
    ) -> None:
        self._settings = settings
        self._repositories = RepositoryService(database, settings)
        self._search_adapter_factory = search_adapter_factory or (
            lambda: SearchServiceAdapter(database, settings)
        )
        self._graph_adapter_factory = graph_adapter_factory or (
            lambda: GraphServiceAdapter(database, settings)
        )
        self._git_diff_adapter = git_diff_adapter or SubprocessGitDiffAdapter(
            timeout_seconds=settings.context_git_diff_timeout_seconds,
            max_bytes=settings.context_git_diff_max_bytes,
        )

    def retrieve(
        self,
        resolution: TaskResolution,
        identifier: str | Path | None = None,
        *,
        graph_depth: int | None = None,
        include_git_diff: bool = True,
    ) -> RetrievalBatch:
        repository = (
            self._repositories.active()
            if identifier is None
            else self._repositories.get(identifier)
        )
        depth = graph_depth or self._settings.context_initial_graph_depth
        if not 1 <= depth <= self._settings.context_expanded_graph_depth:
            raise MonasLensError(
                ErrorCode.CONTEXT_RETRIEVAL_FAILED,
                "Graph retrieval depth is outside the configured bounds.",
            )

        queries, query_diagnostics, query_truncated = _plan_queries(
            resolution,
            self._settings.context_max_retrieval_queries,
        )
        stage_one = self._run_search_stage(repository.id, queries)
        merged_stage_one, stage_one_truncated = _merge_candidates(
            stage_one,
            self._settings.context_max_candidates,
        )
        primary_seeds = _select_primary_seeds(
            merged_stage_one,
            self._settings.context_max_primary_targets,
            frozenset(resolution.explicit_focus_targets),
        )
        graph_jobs = _plan_graph_jobs(primary_seeds, self._settings)
        graph_candidates, graph_diagnostics, graph_truncated, git_result = self._run_optional_stage(
            repository.id,
            repository.canonical_path,
            graph_jobs,
            graph_depth=depth,
            include_git_diff=include_git_diff and repository.is_git_repository,
        )
        repository_diagnostics: tuple[RetrievalDiagnostic, ...] = ()
        if include_git_diff and not repository.is_git_repository:
            repository_diagnostics = (
                RetrievalDiagnostic(
                    code=RetrievalDiagnosticCode.GIT_UNAVAILABLE,
                    severity=DiagnosticSeverity.WARNING,
                    message="The selected repository does not provide a Git working-tree diff.",
                    role=CandidateRole.GIT_DIFF,
                ),
            )

        all_candidates, candidate_truncated = _merge_candidates(
            (*merged_stage_one, *graph_candidates),
            self._settings.context_max_candidates,
        )
        by_identity = {candidate.identity: candidate for candidate in all_candidates}
        final_seeds = tuple(
            by_identity[seed.identity] for seed in primary_seeds if seed.identity in by_identity
        )
        diagnostics = _bounded_diagnostics(
            (
                *resolution.diagnostics,
                *query_diagnostics,
                *repository_diagnostics,
                *graph_diagnostics,
            ),
            self._settings.context_max_retrieval_diagnostics,
        )
        truncated = (
            query_truncated
            or stage_one_truncated
            or graph_truncated
            or candidate_truncated
            or git_result.truncated
        )
        return RetrievalBatch(
            repository_id=repository.id,
            candidates=all_candidates,
            primary_seeds=final_seeds,
            diagnostics=diagnostics,
            git_diff_hunks=git_result.hunks,
            truncated=truncated,
        )

    def widen(
        self,
        repository_id: str,
        seeds: Sequence[RetrievalCandidate],
        roles: frozenset[CandidateRole],
        existing_identities: frozenset[CandidateIdentity],
    ) -> RetrievalExpansion:
        """Run one targeted depth-two graph pass and return only unseen identities."""

        repository = self._repositories.get(repository_id)
        if any(seed.repository_id != repository.id for seed in seeds):
            raise MonasLensError(
                ErrorCode.CONTEXT_RETRIEVAL_FAILED,
                "Confidence widening seeds must belong to the selected repository.",
            )

        selected_seeds = _bounded_unique_seeds(
            seeds,
            self._settings.context_max_primary_targets,
        )
        graph_jobs = _plan_graph_jobs(selected_seeds, self._settings, roles=roles)
        candidates, diagnostics, graph_truncated, _ = self._run_optional_stage(
            repository.id,
            repository.canonical_path,
            graph_jobs,
            graph_depth=self._settings.context_expanded_graph_depth,
            include_git_diff=False,
        )
        unseen = tuple(
            candidate for candidate in candidates if candidate.identity not in existing_identities
        )
        remaining_capacity = max(
            self._settings.context_max_candidates - len(existing_identities),
            0,
        )
        merged, candidate_truncated = _merge_candidates(unseen, remaining_capacity)
        return RetrievalExpansion(
            candidates=merged,
            diagnostics=_bounded_diagnostics(
                diagnostics,
                self._settings.context_max_retrieval_diagnostics,
            ),
            truncated=graph_truncated or candidate_truncated,
        )

    def _run_search_stage(
        self,
        repository_id: str,
        queries: tuple[str, ...],
    ) -> tuple[RetrievalCandidate, ...]:
        if not queries:
            return ()
        per_query_limit = min(_SEARCH_RESULT_LIMIT, self._settings.context_max_candidates)
        with ThreadPoolExecutor(
            max_workers=min(self._settings.context_parallel_workers, len(queries)),
            thread_name_prefix="monas-lens-search",
        ) as executor:
            futures = tuple(
                executor.submit(
                    self._search_adapter_factory().search,
                    query,
                    repository_id,
                    limit=per_query_limit,
                )
                for query in queries
            )
            responses: list[SearchResponse] = []
            for ordinal, future in enumerate(futures):
                try:
                    response = future.result()
                    if response.repository_id != repository_id:
                        raise ValueError("Search result crossed a repository boundary.")
                    responses.append(response)
                except Exception as exc:
                    for pending in futures:
                        pending.cancel()
                    raise MonasLensError(
                        ErrorCode.CONTEXT_RETRIEVAL_FAILED,
                        "Required lexical context retrieval failed.",
                        details={"stage": "lexical", "worker_ordinal": ordinal},
                    ) from exc

        candidates: list[RetrievalCandidate] = []
        for query_ordinal, response in enumerate(responses):
            for result_ordinal, result in enumerate(response.results):
                candidates.append(
                    _search_candidate(
                        repository_id,
                        response.query,
                        result,
                        retrieval_ordinal=(query_ordinal * per_query_limit) + result_ordinal,
                    )
                )
        return tuple(candidates)

    def _run_optional_stage(
        self,
        repository_id: str,
        repository_root: Path,
        graph_jobs: tuple[_GraphJob, ...],
        *,
        graph_depth: int,
        include_git_diff: bool,
    ) -> tuple[
        tuple[RetrievalCandidate, ...],
        tuple[RetrievalDiagnostic, ...],
        bool,
        GitDiffResult,
    ]:
        total_jobs = len(graph_jobs) + int(include_git_diff)
        if total_jobs == 0:
            return (), (), False, GitDiffResult()

        graph_futures: list[tuple[_GraphJob, Future[GraphResponse]]] = []
        git_future: Future[GitDiffResult] | None = None
        with ThreadPoolExecutor(
            max_workers=min(self._settings.context_parallel_workers, total_jobs),
            thread_name_prefix="monas-lens-context",
        ) as executor:
            for job in graph_jobs:
                graph_futures.append(
                    (
                        job,
                        executor.submit(
                            self._graph_adapter_factory().expand,
                            _graph_target(job.seed),
                            repository_id,
                            direction=job.branch.direction,
                            relation_kinds=job.branch.relation_kinds,
                            depth=graph_depth,
                            limit=job.limit,
                        ),
                    )
                )
            if include_git_diff:
                git_future = executor.submit(
                    self._git_diff_adapter.collect,
                    repository_root,
                    max_hunks=self._settings.context_max_git_entries,
                )

            candidates: list[RetrievalCandidate] = []
            diagnostics: list[RetrievalDiagnostic] = []
            truncated = False
            for job, future in graph_futures:
                try:
                    response = future.result()
                    if response.repository_id != repository_id:
                        raise ValueError("Graph result crossed a repository boundary.")
                    branch_candidates = _graph_candidates(response, job)
                    candidates.extend(branch_candidates)
                    truncated = truncated or response.truncated
                except Exception:
                    diagnostics.append(
                        RetrievalDiagnostic(
                            code=RetrievalDiagnosticCode.GRAPH_UNAVAILABLE,
                            severity=DiagnosticSeverity.WARNING,
                            message="An optional graph retrieval branch was unavailable.",
                            role=job.branch.role,
                        )
                    )

            git_result = GitDiffResult()
            if git_future is not None:
                try:
                    git_result = git_future.result()
                    if git_result.truncated:
                        diagnostics.append(
                            RetrievalDiagnostic(
                                code=RetrievalDiagnosticCode.GIT_TRUNCATED,
                                severity=DiagnosticSeverity.WARNING,
                                message="The optional Git diff reached a configured limit.",
                                role=CandidateRole.GIT_DIFF,
                            )
                        )
                    if git_result.invalid_paths:
                        diagnostics.append(
                            RetrievalDiagnostic(
                                code=RetrievalDiagnosticCode.GIT_UNAVAILABLE,
                                severity=DiagnosticSeverity.WARNING,
                                message=(
                                    "An optional Git diff entry had an invalid "
                                    "repository-relative path."
                                ),
                                role=CandidateRole.GIT_DIFF,
                            )
                        )
                except Exception:
                    diagnostics.append(
                        RetrievalDiagnostic(
                            code=RetrievalDiagnosticCode.GIT_UNAVAILABLE,
                            severity=DiagnosticSeverity.WARNING,
                            message="The optional Git diff was unavailable.",
                            role=CandidateRole.GIT_DIFF,
                        )
                    )

        return tuple(candidates), tuple(diagnostics), truncated, git_result


def _plan_queries(
    resolution: TaskResolution,
    limit: int,
) -> tuple[tuple[str, ...], tuple[RetrievalDiagnostic, ...], bool]:
    values = (
        *resolution.explicit_focus_targets,
        *resolution.qualified_identifiers,
        *resolution.path_candidates,
        *resolution.quoted_phrases,
        *resolution.lexical_queries,
    )
    selected: list[str] = []
    discarded = 0
    seen: set[str] = set()
    for value in values:
        query = value.strip()
        if (
            not query
            or len(query) > _SEARCH_QUERY_MAX_CHARS
            or not any(character.isalnum() for character in query)
        ):
            discarded += 1
            continue
        if query in seen:
            continue
        seen.add(query)
        if len(selected) == limit:
            discarded += 1
            continue
        selected.append(query)

    if not selected:
        fallback = " ".join(re.findall(r"\w+", resolution.normalized_task, flags=re.UNICODE)[:20])
        if fallback:
            selected.append(fallback[:_SEARCH_QUERY_MAX_CHARS].rstrip())

    diagnostics: tuple[RetrievalDiagnostic, ...] = ()
    if discarded:
        diagnostics = (
            RetrievalDiagnostic(
                code=RetrievalDiagnosticCode.INPUT_DISCARDED,
                severity=DiagnosticSeverity.INFO,
                message="Some retrieval queries were discarded by configured bounds.",
            ),
        )
    return tuple(selected), diagnostics, bool(discarded)


def _search_candidate(
    repository_id: str,
    query: str,
    result: SearchResult,
    *,
    retrieval_ordinal: int,
) -> RetrievalCandidate:
    try:
        entity_type = EntityType(result.entity_type)
    except ValueError as exc:
        raise MonasLensError(
            ErrorCode.CONTEXT_RETRIEVAL_FAILED,
            "Search returned an unsupported entity type.",
        ) from exc
    evidence_kind = EvidenceKind.EXACT if result.match_type == "exact" else EvidenceKind.LEXICAL
    return RetrievalCandidate(
        repository_id=repository_id,
        entity_type=entity_type,
        entity_id=result.entity_id,
        relative_path=result.relative_path,
        language=result.language,
        kind=result.kind,
        name=result.name,
        qualified_name=result.qualified_name,
        start_line=result.start_line,
        end_line=result.end_line,
        role_hints=(CandidateRole.PRIMARY,),
        evidence=(
            RetrievalEvidence(
                kind=evidence_kind,
                query=query,
                source_score=result.score,
                explanation=(
                    "Exact indexed symbol match."
                    if evidence_kind is EvidenceKind.EXACT
                    else "Lexical indexed-content match."
                ),
            ),
        ),
        retrieval_ordinal=retrieval_ordinal,
    )


def _select_primary_seeds(
    candidates: tuple[RetrievalCandidate, ...],
    limit: int,
    explicit_focus_targets: frozenset[str],
) -> tuple[RetrievalCandidate, ...]:
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            not _matches_explicit_focus(candidate, explicit_focus_targets),
            not any(item.kind is EvidenceKind.EXACT for item in candidate.evidence),
            -max(item.source_score for item in candidate.evidence),
            candidate.entity_type is not EntityType.SYMBOL,
            candidate.retrieval_ordinal,
            candidate.relative_path,
            candidate.start_line,
            candidate.entity_type.value,
            candidate.entity_id,
        ),
    )
    return tuple(ordered[:limit])


def _matches_explicit_focus(
    candidate: RetrievalCandidate,
    focus_targets: frozenset[str],
) -> bool:
    return any(
        value is not None and value in focus_targets
        for value in (
            candidate.entity_id,
            candidate.relative_path,
            candidate.name,
            candidate.qualified_name,
        )
    )


def _plan_graph_jobs(
    seeds: tuple[RetrievalCandidate, ...],
    settings: Settings,
    *,
    roles: frozenset[CandidateRole] | None = None,
) -> tuple[_GraphJob, ...]:
    jobs: list[_GraphJob] = []
    for seed_ordinal, seed in enumerate(seeds):
        for branch_ordinal, branch in enumerate(_GRAPH_BRANCHES):
            if roles is not None and branch.role not in roles:
                continue
            limit = int(getattr(settings, branch.limit_setting))
            if limit <= 0:
                continue
            jobs.append(
                _GraphJob(
                    ordinal=(seed_ordinal * len(_GRAPH_BRANCHES)) + branch_ordinal,
                    seed=seed,
                    branch=branch,
                    limit=limit,
                )
            )
    return tuple(jobs)


def _bounded_unique_seeds(
    seeds: Sequence[RetrievalCandidate],
    limit: int,
) -> tuple[RetrievalCandidate, ...]:
    selected: list[RetrievalCandidate] = []
    seen: set[CandidateIdentity] = set()
    for seed in seeds:
        if seed.identity in seen:
            continue
        seen.add(seed.identity)
        selected.append(seed)
        if len(selected) == limit:
            break
    return tuple(selected)


def _graph_candidates(
    response: GraphResponse,
    job: _GraphJob,
) -> tuple[RetrievalCandidate, ...]:
    distances = _graph_distances(response, job.branch.direction)
    nodes = {node.id: node for node in response.nodes}
    candidates: list[RetrievalCandidate] = []
    ordinal_base = 10_000 + (job.ordinal * _GRAPH_ORDINAL_STRIDE)
    for node_id, distance in sorted(
        distances.items(),
        key=lambda item: _graph_node_sort_key(nodes[item[0]], item[1]),
    ):
        if node_id == response.root.id or distance < 1:
            continue
        node = nodes[node_id]
        supporting_edges = _supporting_edges(
            response.edges,
            distances,
            node_id,
            distance,
            job.branch.direction,
        )
        if not supporting_edges:
            continue
        evidence = tuple(
            RetrievalEvidence(
                kind=(
                    EvidenceKind.TEST if edge.kind is RelationKind.TESTED_BY else EvidenceKind.GRAPH
                ),
                query=job.seed.entity_id,
                seed_id=job.seed.entity_id,
                relation_kind=edge.kind,
                distance=distance,
                source_score=edge.confidence,
                explanation="Repository graph relationship from a primary seed.",
            )
            for edge in supporting_edges
        )
        candidates.append(
            RetrievalCandidate(
                repository_id=response.repository_id,
                entity_type=(EntityType.SYMBOL if node.node_type == "symbol" else EntityType.FILE),
                entity_id=node.id,
                relative_path=node.relative_path,
                language=node.language,
                kind=node.kind,
                name=node.name,
                qualified_name=node.qualified_name,
                start_line=node.start_line or 1,
                end_line=node.end_line or node.start_line or 1,
                role_hints=(job.branch.role,),
                evidence=evidence,
                retrieval_ordinal=ordinal_base + len(candidates),
            )
        )
    return tuple(candidates[: job.limit])


def _graph_distances(
    response: GraphResponse,
    direction: GraphDirection,
) -> dict[str, int]:
    adjacency: dict[str, set[str]] = {}
    for edge in response.edges:
        if direction in {GraphDirection.OUTGOING, GraphDirection.BOTH}:
            adjacency.setdefault(edge.source_id, set()).add(edge.target_id)
        if direction in {GraphDirection.INCOMING, GraphDirection.BOTH}:
            adjacency.setdefault(edge.target_id, set()).add(edge.source_id)

    distances = {response.root.id: 0}
    frontier = deque((response.root.id,))
    while frontier:
        current = frontier.popleft()
        if distances[current] >= response.depth:
            continue
        for neighbor in sorted(adjacency.get(current, ())):
            if neighbor in distances:
                continue
            distances[neighbor] = distances[current] + 1
            frontier.append(neighbor)
    return distances


def _supporting_edges(
    edges: tuple[GraphEdge, ...],
    distances: dict[str, int],
    node_id: str,
    distance: int,
    direction: GraphDirection,
) -> tuple[GraphEdge, ...]:
    selected: list[GraphEdge] = []
    for edge in edges:
        outgoing_match = (
            direction in {GraphDirection.OUTGOING, GraphDirection.BOTH}
            and edge.target_id == node_id
            and distances.get(edge.source_id) == distance - 1
        )
        incoming_match = (
            direction in {GraphDirection.INCOMING, GraphDirection.BOTH}
            and edge.source_id == node_id
            and distances.get(edge.target_id) == distance - 1
        )
        if outgoing_match or incoming_match:
            selected.append(edge)
    return tuple(sorted(selected, key=_graph_edge_sort_key))


def _merge_candidates(
    candidates: Sequence[RetrievalCandidate],
    limit: int,
) -> tuple[tuple[RetrievalCandidate, ...], bool]:
    grouped: dict[CandidateIdentity, list[RetrievalCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.identity, []).append(candidate)

    merged: list[RetrievalCandidate] = []
    for identity in sorted(grouped, key=_identity_sort_key):
        occurrences = sorted(grouped[identity], key=_candidate_source_sort_key)
        base = occurrences[0]
        roles = tuple(
            sorted(
                {role for candidate in occurrences for role in candidate.role_hints},
                key=lambda role: (_ROLE_PRIORITY[role], role.value),
            )
        )
        evidence_by_key = {
            _evidence_sort_key(item): item
            for candidate in occurrences
            for item in candidate.evidence
        }
        evidence = tuple(
            evidence_by_key[key] for key in sorted(evidence_by_key)[:_MAX_EVIDENCE_PER_CANDIDATE]
        )
        merged.append(
            base.model_copy(
                update={
                    "role_hints": roles,
                    "evidence": evidence,
                    "retrieval_ordinal": min(
                        candidate.retrieval_ordinal for candidate in occurrences
                    ),
                }
            )
        )

    ordered = tuple(sorted(merged, key=_candidate_source_sort_key))
    return ordered[:limit], len(ordered) > limit


def _bounded_diagnostics(
    diagnostics: Sequence[RetrievalDiagnostic],
    limit: int,
) -> tuple[RetrievalDiagnostic, ...]:
    unique = {_diagnostic_sort_key(item): item for item in diagnostics}
    return tuple(unique[key] for key in sorted(unique)[:limit])


def _select_chunk(
    candidate: RetrievalCandidate,
    chunks: Sequence[ChunkModel],
) -> ChunkModel | None:
    if not chunks:
        return None

    def priority(chunk: ChunkModel) -> tuple[int, int, int, str]:
        if candidate.entity_type is EntityType.CHUNK and chunk.id == candidate.entity_id:
            match_priority = 0
        elif candidate.entity_type is EntityType.SYMBOL and chunk.symbol_id == candidate.entity_id:
            match_priority = 1
        elif candidate.entity_type is EntityType.FILE:
            match_priority = 2 if chunk.kind == "module" else 3
        elif chunk.start_line <= candidate.start_line and chunk.end_line >= candidate.end_line:
            match_priority = 2
        else:
            match_priority = 4
        return (
            match_priority,
            chunk.end_line - chunk.start_line,
            chunk.start_line,
            chunk.id,
        )

    selected = min(chunks, key=priority)
    return selected if priority(selected)[0] < 4 else None


def _parse_git_diff(text: str, max_hunks: int) -> GitDiffResult:
    hunks: list[GitDiffHunk] = []
    old_path: str | None = None
    new_path: str | None = None
    old_path_invalid = False
    new_path_invalid = False
    current_header: tuple[int, int] | None = None
    current_lines: list[str] = []
    truncated = False
    invalid_paths = 0

    def flush() -> None:
        nonlocal invalid_paths, truncated
        if current_header is None or not current_lines:
            return
        if old_path_invalid or new_path_invalid:
            invalid_paths += 1
            return
        relative_path = _select_diff_path(old_path, new_path)
        if relative_path is None:
            invalid_paths += 1
            return
        if len(hunks) >= max_hunks:
            truncated = True
            return
        content = "".join(current_lines)
        hunks.append(
            GitDiffHunk(
                relative_path=relative_path,
                old_start_line=current_header[0],
                new_start_line=current_header[1],
                content=content,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            )
        )

    for line in text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            flush()
            old_path = None
            new_path = None
            old_path_invalid = False
            new_path_invalid = False
            current_header = None
            current_lines = []
            continue
        if line.startswith("--- "):
            flush()
            current_header = None
            current_lines = []
            new_path = None
            new_path_invalid = False
            old_path, old_path_invalid = _normalize_diff_path(line[4:].strip())
            continue
        if line.startswith("+++ "):
            new_path, new_path_invalid = _normalize_diff_path(line[4:].strip())
            continue
        header = _GIT_DIFF_HEADER.match(line)
        if header is not None:
            flush()
            current_header = (int(header.group(1)), int(header.group(3)))
            current_lines = [line]
            continue
        if current_header is not None:
            current_lines.append(line)
    flush()
    return GitDiffResult(
        hunks=tuple(hunks),
        truncated=truncated,
        invalid_paths=invalid_paths,
    )


def _normalize_diff_path(value: str) -> tuple[str | None, bool]:
    if value == "/dev/null":
        return None, False
    if value.startswith('"'):
        return None, True
    normalized = value[2:] if value.startswith(("a/", "b/")) else value
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        return None, True
    return path.as_posix(), False


def _select_diff_path(old_path: str | None, new_path: str | None) -> str | None:
    return new_path or old_path


def _graph_target(seed: RetrievalCandidate) -> str:
    return seed.relative_path if seed.entity_type is EntityType.CHUNK else seed.entity_id


def _candidate_source_sort_key(
    candidate: RetrievalCandidate,
) -> tuple[int, str, int, str, str]:
    return (
        candidate.retrieval_ordinal,
        candidate.relative_path,
        candidate.start_line,
        candidate.entity_type.value,
        candidate.entity_id,
    )


def _identity_sort_key(identity: CandidateIdentity) -> tuple[str, str, str]:
    return (identity[0], identity[1].value, identity[2])


def _evidence_sort_key(
    evidence: RetrievalEvidence,
) -> tuple[str, str, str, str, int, float, str]:
    return (
        evidence.kind.value,
        evidence.query,
        evidence.seed_id or "",
        evidence.relation_kind.value if evidence.relation_kind is not None else "",
        evidence.distance or 0,
        -evidence.source_score,
        evidence.explanation,
    )


def _diagnostic_sort_key(
    diagnostic: RetrievalDiagnostic,
) -> tuple[str, str, str, str]:
    return (
        diagnostic.code.value,
        diagnostic.severity.value,
        diagnostic.role.value if diagnostic.role is not None else "",
        diagnostic.message,
    )


def _graph_node_sort_key(node: GraphNode, distance: int) -> tuple[int, str, int, str, str]:
    return (
        distance,
        node.relative_path,
        node.start_line or 0,
        node.node_type,
        node.id,
    )


def _graph_edge_sort_key(edge: GraphEdge) -> tuple[str, str, str, str]:
    return (edge.kind.value, edge.source_id, edge.target_id, edge.id)
