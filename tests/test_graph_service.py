from pathlib import Path

import pytest

from monas_lens.config import Settings
from monas_lens.db.session import Database
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.graph.contracts import GraphDirection, RelationKind
from monas_lens.graph.service import (
    GraphService,
    parse_graph_direction,
    parse_relation_kinds,
)
from monas_lens.indexing.service import IndexService
from monas_lens.repositories import RepositoryService


def _indexed_graph(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> GraphService:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "service.py").write_text(
        "def alpha() -> str:\n    return beta()\n\ndef beta() -> str:\n    return alpha()\n",
        encoding="utf-8",
    )
    (repository_root / "test_service.py").write_text(
        "from service import alpha\n\ndef test_alpha() -> None:\n    assert alpha()\n",
        encoding="utf-8",
    )
    repository = RepositoryService(database, settings).add(repository_root)
    IndexService(database, settings).build(repository.id)
    return GraphService(database, settings)


def test_neighbors_supports_direction_and_relation_filters(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    service = _indexed_graph(database, settings, tmp_path)

    outgoing = service.neighbors(
        "alpha",
        direction=GraphDirection.OUTGOING,
        relation_kinds=frozenset({RelationKind.CALLS}),
    )
    test_links = service.neighbors(
        "alpha",
        direction=GraphDirection.OUTGOING,
        relation_kinds=frozenset({RelationKind.TESTED_BY}),
    )

    outgoing_names = {node.name for node in outgoing.nodes}
    test_link_names = {node.name for node in test_links.nodes}
    assert outgoing_names == {"alpha", "beta"}
    assert {edge.kind for edge in outgoing.edges} == {RelationKind.CALLS}
    assert test_link_names == {"alpha", "test_alpha"}
    assert {edge.kind for edge in test_links.edges} == {RelationKind.TESTED_BY}


def test_traverse_is_cycle_safe_and_deterministic(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    service = _indexed_graph(database, settings, tmp_path)

    first = service.traverse(
        "alpha",
        direction=GraphDirection.OUTGOING,
        relation_kinds=frozenset({RelationKind.CALLS}),
        depth=5,
    )
    second = service.traverse(
        "alpha",
        direction=GraphDirection.OUTGOING,
        relation_kinds=frozenset({RelationKind.CALLS}),
        depth=5,
    )

    assert {node.name for node in first.nodes} == {"alpha", "beta"}
    assert len(first.edges) == 2
    assert not first.truncated
    assert first == second


def test_graph_query_rejects_ambiguous_targets_and_invalid_bounds(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    for relative_path in ("first.py", "second.py"):
        (repository_root / relative_path).write_text(
            "def shared() -> None:\n    pass\n",
            encoding="utf-8",
        )
    repository = RepositoryService(database, settings).add(repository_root)
    IndexService(database, settings).build(repository.id)
    service = GraphService(database, settings)

    with pytest.raises(MonasLensError) as ambiguous:
        service.neighbors("shared")
    with pytest.raises(MonasLensError) as invalid_depth:
        service.traverse("first.py", depth=6)
    with pytest.raises(MonasLensError) as invalid_limit:
        service.neighbors("first.py", limit=0)

    assert ambiguous.value.code == ErrorCode.GRAPH_QUERY_INVALID
    assert ambiguous.value.details["candidate_count"] == 2
    assert invalid_depth.value.code == ErrorCode.GRAPH_QUERY_INVALID
    assert invalid_limit.value.code == ErrorCode.GRAPH_QUERY_INVALID


def test_parse_relation_kinds_validates_cli_filter() -> None:
    assert parse_relation_kinds(" calls,imports ") == frozenset(
        {RelationKind.CALLS, RelationKind.IMPORTS}
    )
    assert parse_relation_kinds(None) is None

    with pytest.raises(MonasLensError) as invalid:
        parse_relation_kinds("calls,unknown")

    assert invalid.value.code == ErrorCode.GRAPH_QUERY_INVALID


def test_parse_graph_direction_validates_cli_value() -> None:
    assert parse_graph_direction("incoming") == GraphDirection.INCOMING

    with pytest.raises(MonasLensError) as invalid:
        parse_graph_direction("sideways")

    assert invalid.value.code == ErrorCode.GRAPH_QUERY_INVALID
