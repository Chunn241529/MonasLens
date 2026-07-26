from __future__ import annotations

import json
import subprocess
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

import pytest
from sqlalchemy.orm import Session

from monas_lens.config import Settings
from monas_lens.db.session import Database
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.graph.contracts import GraphDirection, RelationKind
from monas_lens.graph.service import GraphEdge, GraphNode, GraphResponse
from monas_lens.indexing.service import IndexService
from monas_lens.repositories import RepositoryService
from monas_lens.retrieval.contracts import CandidateRole, TaskResolution
from monas_lens.retrieval.resolver import resolve_task
from monas_lens.retrieval.retriever import (
    GitDiffResult,
    IndexedChunkLookupAdapter,
    ParallelRetriever,
    RetrievalBatch,
    SubprocessGitDiffAdapter,
)
from monas_lens.search.service import SearchResponse, SearchResult


class _SearchAdapter:
    def __init__(
        self,
        repository_id: str,
        responses: dict[str, tuple[SearchResult, ...]],
        *,
        delays: dict[str, float] | None = None,
        calls: list[tuple[str, int]] | None = None,
        failure: Exception | None = None,
    ) -> None:
        self._repository_id = repository_id
        self._responses = responses
        self._delays = delays or {}
        self._calls = calls
        self._failure = failure

    def search(self, query: str, repository_id: str, *, limit: int) -> SearchResponse:
        if self._calls is not None:
            self._calls.append((query, limit))
        time.sleep(self._delays.get(query, 0))
        if self._failure is not None:
            raise self._failure
        assert repository_id == self._repository_id
        results = self._responses.get(query, ())[:limit]
        return SearchResponse(
            repository_id=repository_id,
            query=query,
            total=len(results),
            results=results,
        )


class _GraphAdapter:
    def __init__(
        self,
        repository_id: str,
        *,
        delays: dict[CandidateKey, float] | None = None,
        calls: list[tuple[str, frozenset[RelationKind], int, int]] | None = None,
        failure: Exception | None = None,
        foreign_repository_id: str | None = None,
    ) -> None:
        self._repository_id = repository_id
        self._delays = delays or {}
        self._calls = calls
        self._failure = failure
        self._foreign_repository_id = foreign_repository_id

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
        if self._calls is not None:
            self._calls.append((target, relation_kinds, depth, limit))
        key = (target, tuple(sorted(kind.value for kind in relation_kinds)))
        time.sleep(self._delays.get(key, 0))
        if self._failure is not None:
            raise self._failure
        assert repository_id == self._repository_id
        return _graph_response(
            self._foreign_repository_id or repository_id,
            target,
            direction,
            relation_kinds,
            depth,
            limit,
        )


class _FailingGitAdapter:
    def collect(self, repository_root: Path, *, max_hunks: int) -> GitDiffResult:
        raise OSError("unavailable")


type CandidateKey = tuple[str, tuple[str, ...]]


def test_shuffled_worker_delays_produce_identical_merged_output(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_id = _register_empty_repository(database, settings, tmp_path)
    responses = {
        "Alpha.run": (_search_result("symbol-alpha", "Alpha.run", match_type="exact", score=1),),
        "timeout": (
            _search_result("symbol-alpha", "Alpha.run", score=0.82),
            _search_result("symbol-timeout", "handle_timeout", score=0.79),
        ),
    }
    resolution = TaskResolution(
        normalized_task="Fix Alpha.run timeout",
        qualified_identifiers=("Alpha.run",),
        lexical_queries=("Alpha.run", "timeout"),
    )

    first = ParallelRetriever(
        database,
        settings,
        search_adapter_factory=lambda: _SearchAdapter(
            repository_id,
            responses,
            delays={"Alpha.run": 0.02},
        ),
        graph_adapter_factory=lambda: _GraphAdapter(
            repository_id,
            delays={("symbol-alpha", ("calls",)): 0.02},
        ),
    ).retrieve(resolution, repository_id, include_git_diff=False)
    second = ParallelRetriever(
        database,
        settings,
        search_adapter_factory=lambda: _SearchAdapter(
            repository_id,
            responses,
            delays={"timeout": 0.02},
        ),
        graph_adapter_factory=lambda: _GraphAdapter(
            repository_id,
            delays={("symbol-timeout", ("configured_by",)): 0.02},
        ),
    ).retrieve(resolution, repository_id, include_git_diff=False)

    assert _batch_json(first) == _batch_json(second)
    alpha = next(item for item in first.candidates if item.entity_id == "symbol-alpha")
    assert {evidence.query for evidence in alpha.evidence} == {"Alpha.run", "timeout"}


def test_two_stage_retrieval_assigns_graph_roles(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_id = _register_empty_repository(database, settings, tmp_path)
    responses = {
        "Alpha.run": (_search_result("symbol-alpha", "Alpha.run", match_type="exact", score=1),)
    }
    batch = ParallelRetriever(
        database,
        settings,
        search_adapter_factory=lambda: _SearchAdapter(repository_id, responses),
        graph_adapter_factory=lambda: _GraphAdapter(repository_id),
    ).retrieve(
        TaskResolution(
            normalized_task="Fix Alpha.run",
            qualified_identifiers=("Alpha.run",),
            lexical_queries=("Alpha.run",),
        ),
        repository_id,
        include_git_diff=False,
    )

    roles = {
        role.value
        for candidate in batch.candidates
        if candidate.entity_id != "symbol-alpha"
        for role in candidate.role_hints
    }
    assert roles == {"caller", "dependency", "interface", "test", "configuration"}
    assert len(batch.primary_seeds) == 1


def test_confidence_widening_targets_missing_roles_and_returns_only_new_candidates(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_id = _register_empty_repository(database, settings, tmp_path)
    responses = {
        "Alpha.run": (_search_result("symbol-alpha", "Alpha.run", match_type="exact", score=1),)
    }
    graph_calls: list[tuple[str, frozenset[RelationKind], int, int]] = []
    retriever = ParallelRetriever(
        database,
        settings,
        search_adapter_factory=lambda: _SearchAdapter(repository_id, responses),
        graph_adapter_factory=lambda: _GraphAdapter(repository_id, calls=graph_calls),
    )
    batch = retriever.retrieve(
        TaskResolution(
            normalized_task="Fix Alpha.run",
            qualified_identifiers=("Alpha.run",),
            lexical_queries=("Alpha.run",),
        ),
        repository_id,
        include_git_diff=False,
    )
    existing_identities = frozenset(candidate.identity for candidate in batch.candidates)
    graph_calls.clear()

    expansion = retriever.widen(
        repository_id,
        batch.primary_seeds,
        frozenset({CandidateRole.TEST}),
        existing_identities,
    )

    assert graph_calls == [
        (
            "symbol-alpha",
            frozenset({RelationKind.TESTED_BY}),
            settings.context_expanded_graph_depth,
            settings.context_max_test_snippets,
        )
    ]
    assert [candidate.entity_id for candidate in expansion.candidates] == [
        "symbol-alpha-test-depth-two"
    ]
    assert all(candidate.identity not in existing_identities for candidate in expansion.candidates)
    assert all(candidate.role_hints == (CandidateRole.TEST,) for candidate in expansion.candidates)


def test_worker_sessions_are_owned_by_one_thread_and_repository_is_scoped(
    database: Database,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_root = tmp_path / "first"
    first_root.mkdir()
    (first_root / "service.py").write_text(
        "def alpha() -> str:\n    return beta()\n\ndef beta() -> str:\n    return 'first'\n",
        encoding="utf-8",
    )
    first_id = RepositoryService(database, settings).add(first_root).id
    IndexService(database, settings).build(first_id)

    second_root = tmp_path / "second"
    second_root.mkdir()
    (second_root / "service.py").write_text(
        "def alpha() -> str:\n    return 'second'\n",
        encoding="utf-8",
    )
    second_id = RepositoryService(database, settings).add(second_root).id
    IndexService(database, settings).build(second_id)
    assert first_id != second_id

    original_session = database.session
    owners: dict[int, set[int]] = {}
    retained_sessions: list[Session] = []
    entered = 0
    exited = 0
    lock = threading.Lock()

    @contextmanager
    def tracked_session() -> Generator[Session]:
        nonlocal entered, exited
        with original_session() as session:
            with lock:
                retained_sessions.append(session)
                owners.setdefault(id(session), set()).add(threading.get_ident())
                entered += 1
            try:
                yield session
            finally:
                with lock:
                    exited += 1

    monkeypatch.setattr(database, "session", tracked_session)
    batch = ParallelRetriever(database, settings).retrieve(
        resolve_task("Fix alpha beta"),
        first_id,
        include_git_diff=False,
    )

    assert entered == exited
    assert retained_sessions
    assert all(len(thread_ids) == 1 for thread_ids in owners.values())
    assert batch.repository_id == first_id
    assert batch.candidates
    assert all(candidate.repository_id == first_id for candidate in batch.candidates)
    assert all(
        "second" not in evidence.query
        for candidate in batch.candidates
        for evidence in candidate.evidence
    )


def test_optional_failures_degrade_and_cross_repository_graph_is_discarded(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / ".git").mkdir()
    repository_id = RepositoryService(database, settings).add(repository_root).id
    responses = {"Alpha": (_search_result("symbol-alpha", "Alpha", score=0.9),)}

    failed = ParallelRetriever(
        database,
        settings,
        search_adapter_factory=lambda: _SearchAdapter(repository_id, responses),
        graph_adapter_factory=lambda: _GraphAdapter(
            repository_id,
            failure=RuntimeError("graph failed"),
        ),
        git_diff_adapter=_FailingGitAdapter(),
    ).retrieve(
        TaskResolution(normalized_task="Fix Alpha", lexical_queries=("Alpha",)),
        repository_id,
    )
    foreign = ParallelRetriever(
        database,
        settings,
        search_adapter_factory=lambda: _SearchAdapter(repository_id, responses),
        graph_adapter_factory=lambda: _GraphAdapter(
            repository_id,
            foreign_repository_id="foreign-repository",
        ),
    ).retrieve(
        TaskResolution(normalized_task="Fix Alpha", lexical_queries=("Alpha",)),
        repository_id,
        include_git_diff=False,
    )

    assert {diagnostic.code.value for diagnostic in failed.diagnostics} == {
        "git_unavailable",
        "graph_unavailable",
    }
    assert failed.primary_seeds[0].entity_id == "symbol-alpha"
    assert all(candidate.repository_id == repository_id for candidate in foreign.candidates)
    assert {diagnostic.code.value for diagnostic in foreign.diagnostics} == {"graph_unavailable"}


def test_required_lexical_failure_uses_stable_error(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_id = _register_empty_repository(database, settings, tmp_path)
    retriever = ParallelRetriever(
        database,
        settings,
        search_adapter_factory=lambda: _SearchAdapter(
            repository_id,
            {},
            failure=RuntimeError("search failed"),
        ),
    )

    with pytest.raises(MonasLensError) as raised:
        retriever.retrieve(
            TaskResolution(normalized_task="Fix Alpha", lexical_queries=("Alpha",)),
            repository_id,
            include_git_diff=False,
        )

    assert raised.value.code is ErrorCode.CONTEXT_RETRIEVAL_FAILED
    assert raised.value.details == {"stage": "lexical", "worker_ordinal": 0}


def test_query_candidate_and_graph_work_are_capped(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    bounded_settings = settings.model_copy(
        update={
            "context_max_retrieval_queries": 2,
            "context_max_candidates": 10,
            "context_parallel_workers": 2,
        }
    )
    repository_id = _register_empty_repository(database, bounded_settings, tmp_path)
    search_calls: list[tuple[str, int]] = []
    graph_calls: list[tuple[str, frozenset[RelationKind], int, int]] = []
    responses = {
        query: tuple(
            _search_result(f"{query}-symbol-{index}", f"{query}_{index}", score=0.8)
            for index in range(30)
        )
        for query in ("alpha", "bravo", "charlie")
    }
    batch = ParallelRetriever(
        database,
        bounded_settings,
        search_adapter_factory=lambda: _SearchAdapter(
            repository_id,
            responses,
            calls=search_calls,
        ),
        graph_adapter_factory=lambda: _GraphAdapter(
            repository_id,
            calls=graph_calls,
        ),
    ).retrieve(
        TaskResolution(
            normalized_task="alpha bravo charlie",
            lexical_queries=("alpha", "bravo", "charlie"),
        ),
        repository_id,
        include_git_diff=False,
    )

    assert len(search_calls) == 2
    assert all(limit == 10 for _, limit in search_calls)
    assert len(batch.primary_seeds) == 3
    assert len(graph_calls) == 15
    assert all(depth == 1 and 1 <= limit <= 6 for _, _, depth, limit in graph_calls)
    assert len(batch.candidates) == 10
    assert batch.truncated


def test_indexed_chunk_lookup_is_narrow_and_rejects_foreign_candidates(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "service.py").write_text(
        "def alpha() -> str:\n    return 'alpha'\n",
        encoding="utf-8",
    )
    repository_id = RepositoryService(database, settings).add(repository_root).id
    IndexService(database, settings).build(repository_id)
    batch = ParallelRetriever(database, settings).retrieve(
        resolve_task("Fix alpha"),
        repository_id,
        include_git_diff=False,
    )
    seed = batch.primary_seeds[0]
    chunks = IndexedChunkLookupAdapter(database).lookup(repository_id, (seed,))

    assert len(chunks) == 1
    assert chunks[0].candidate_identity == seed.identity
    assert chunks[0].source_text.startswith("def alpha")

    foreign = seed.model_copy(update={"repository_id": "foreign-repository"})
    with pytest.raises(MonasLensError) as raised:
        IndexedChunkLookupAdapter(database).lookup(repository_id, (foreign,))
    assert raised.value.code is ErrorCode.CONTEXT_RETRIEVAL_FAILED


def test_git_diff_adapter_uses_fixed_arguments_and_hunk_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    output = (
        b"--- a/service.py\n"
        b"+++ b/service.py\n"
        b"@@ -1 +1 @@\n"
        b"-old\n"
        b"+new\n"
        b"@@ -5 +5 @@\n"
        b"-before\n"
        b"+after\n"
    )

    def fake_run(arguments: tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        captured["arguments"] = arguments
        captured.update(kwargs)
        return subprocess.CompletedProcess(arguments, 0, stdout=output)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = SubprocessGitDiffAdapter(timeout_seconds=1, max_bytes=10_000).collect(
        tmp_path,
        max_hunks=1,
    )

    assert captured["arguments"] == (
        "git",
        "diff",
        "--no-ext-diff",
        "--no-color",
        "--unified=3",
        "HEAD",
        "--",
    )
    assert captured["cwd"] == tmp_path
    assert captured["shell"] is False
    assert len(result.hunks) == 1
    assert result.hunks[0].relative_path == "service.py"
    assert result.truncated


def _register_empty_repository(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> str:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    return RepositoryService(database, settings).add(repository_root).id


def _search_result(
    entity_id: str,
    qualified_name: str,
    *,
    match_type: Literal["exact", "fts"] = "fts",
    score: float,
) -> SearchResult:
    name = qualified_name.rsplit(".", maxsplit=1)[-1]
    return SearchResult(
        entity_type="symbol",
        entity_id=entity_id,
        relative_path=f"{name.casefold()}.py",
        language="python",
        kind="function",
        name=name,
        qualified_name=qualified_name,
        signature=f"def {name}() -> None",
        snippet=name,
        start_line=1,
        end_line=2,
        match_type=match_type,
        score=score,
    )


def _graph_response(
    repository_id: str,
    target: str,
    direction: GraphDirection,
    relation_kinds: frozenset[RelationKind],
    depth: int,
    limit: int,
) -> GraphResponse:
    root = _graph_node(target, "Alpha.run", "alpha.py")
    if not relation_kinds or limit == 0:
        return GraphResponse(
            repository_id=repository_id,
            root=root,
            nodes=(root,),
            edges=(),
            depth=depth,
            truncated=False,
        )
    relation = sorted(relation_kinds, key=lambda item: item.value)[0]
    suffix = {
        RelationKind.CALLS: "caller" if direction is GraphDirection.INCOMING else "dependency",
        RelationKind.IMPORTS: "dependency",
        RelationKind.INHERITS: "interface",
        RelationKind.IMPLEMENTS: "interface",
        RelationKind.TESTED_BY: "test",
        RelationKind.CONFIGURED_BY: "configuration",
    }[relation]
    neighbor = _graph_node(f"{target}-{suffix}", suffix, f"{suffix}.py")
    source_id, target_id = (
        (neighbor.id, root.id) if direction is GraphDirection.INCOMING else (root.id, neighbor.id)
    )
    edge = GraphEdge(
        id=f"edge-{target}-{suffix}",
        kind=relation,
        source_id=source_id,
        target_id=target_id,
        confidence=0.9,
        resolution_strategy="fixture",
    )
    nodes = [root, neighbor]
    edges = [edge]
    if depth > 1:
        depth_two = _graph_node(
            f"{target}-{suffix}-depth-two",
            f"{suffix}-depth-two",
            f"{suffix}_depth_two.py",
        )
        depth_two_source, depth_two_target = (
            (depth_two.id, neighbor.id)
            if direction is GraphDirection.INCOMING
            else (neighbor.id, depth_two.id)
        )
        nodes.append(depth_two)
        edges.append(
            GraphEdge(
                id=f"edge-{target}-{suffix}-depth-two",
                kind=relation,
                source_id=depth_two_source,
                target_id=depth_two_target,
                confidence=0.8,
                resolution_strategy="fixture",
            )
        )
    return GraphResponse(
        repository_id=repository_id,
        root=root,
        nodes=tuple(nodes),
        edges=tuple(edges),
        depth=depth,
        truncated=False,
    )


def _graph_node(entity_id: str, name: str, relative_path: str) -> GraphNode:
    return GraphNode(
        id=entity_id,
        node_type="symbol",
        relative_path=relative_path,
        language="python",
        kind="function",
        name=name,
        qualified_name=name,
        start_line=1,
        end_line=2,
    )


def _batch_json(selected: RetrievalBatch) -> str:
    payload = {
        "repository_id": selected.repository_id,
        "candidates": [candidate.model_dump(mode="json") for candidate in selected.candidates],
        "primary_seeds": [seed.identity for seed in selected.primary_seeds],
        "diagnostics": [diagnostic.model_dump(mode="json") for diagnostic in selected.diagnostics],
        "truncated": selected.truncated,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
