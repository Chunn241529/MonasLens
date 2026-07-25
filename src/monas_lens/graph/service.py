"""Bounded repository graph lookup and traversal."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from monas_lens.config import Settings
from monas_lens.db.models import FileModel, RelationshipModel, SymbolModel
from monas_lens.db.session import Database
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.graph.contracts import GraphDirection, RelationKind
from monas_lens.repositories import RepositoryRecord, RepositoryService

_MAX_DEPTH = 5
_MAX_RESULTS = 500


class GraphNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    node_type: Literal["file", "symbol"]
    relative_path: str
    language: str
    kind: str
    name: str | None
    qualified_name: str | None
    start_line: int | None
    end_line: int | None


class GraphEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    kind: RelationKind
    source_id: str
    target_id: str
    confidence: float
    resolution_strategy: str


class GraphResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository_id: str
    root: GraphNode
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    depth: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class _NodeRef:
    node_type: Literal["file", "symbol"]
    id: str
    file_id: str
    symbol_id: str | None

    @property
    def key(self) -> tuple[str, str]:
        return (self.node_type, self.id)


class GraphService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self._database = database
        self._repositories = RepositoryService(database, settings)

    def neighbors(
        self,
        target: str,
        identifier: str | Path | None = None,
        *,
        direction: GraphDirection = GraphDirection.BOTH,
        relation_kinds: frozenset[RelationKind] | None = None,
        limit: int = 50,
    ) -> GraphResponse:
        return self._query(
            target,
            identifier,
            direction=direction,
            relation_kinds=relation_kinds,
            depth=1,
            limit=limit,
        )

    def traverse(
        self,
        target: str,
        identifier: str | Path | None = None,
        *,
        direction: GraphDirection = GraphDirection.BOTH,
        relation_kinds: frozenset[RelationKind] | None = None,
        depth: int = 2,
        limit: int = 200,
    ) -> GraphResponse:
        return self._query(
            target,
            identifier,
            direction=direction,
            relation_kinds=relation_kinds,
            depth=depth,
            limit=limit,
        )

    def _query(
        self,
        target: str,
        identifier: str | Path | None,
        *,
        direction: GraphDirection,
        relation_kinds: frozenset[RelationKind] | None,
        depth: int,
        limit: int,
    ) -> GraphResponse:
        _validate_bounds(depth, limit)
        repository = self._resolve_repository(identifier)
        with self._database.session() as session:
            root_ref = _resolve_node_ref(session, repository.id, target.strip())
            root = _graph_node(session, root_ref)
            nodes = {root_ref.key: root}
            visited = {root_ref.key}
            frontier = {root_ref}
            selected_edges: dict[str, RelationshipModel] = {}
            truncated = False

            for _level in range(depth):
                remaining = limit - len(selected_edges)
                if remaining <= 0 or not frontier:
                    truncated = remaining <= 0
                    break
                edges = _incident_edges(
                    session,
                    repository.id,
                    frontier,
                    direction,
                    relation_kinds,
                    remaining + 1,
                )
                if len(edges) > remaining:
                    edges = edges[:remaining]
                    truncated = True
                next_frontier: set[_NodeRef] = set()
                frontier_keys = {node.key for node in frontier}
                for edge in edges:
                    selected_edges.setdefault(edge.id, edge)
                    source_ref = _edge_source(edge)
                    target_ref = _edge_target(edge)
                    for node_ref in (source_ref, target_ref):
                        if node_ref.key not in nodes:
                            nodes[node_ref.key] = _graph_node(session, node_ref)
                    for neighbor in _edge_neighbors(
                        source_ref,
                        target_ref,
                        frontier_keys,
                        direction,
                    ):
                        if neighbor.key not in visited:
                            visited.add(neighbor.key)
                            next_frontier.add(neighbor)
                frontier = next_frontier
                if truncated:
                    break

            graph_edges = tuple(
                _graph_edge(edge)
                for edge in sorted(
                    selected_edges.values(),
                    key=lambda item: (
                        item.kind,
                        item.source_file_id,
                        item.source_symbol_id or "",
                        item.target_file_id,
                        item.target_symbol_id or "",
                        item.id,
                    ),
                )
            )
            graph_nodes = tuple(
                sorted(
                    nodes.values(),
                    key=lambda node: (
                        node.relative_path,
                        node.start_line or 0,
                        node.node_type,
                        node.id,
                    ),
                )
            )
        return GraphResponse(
            repository_id=repository.id,
            root=root,
            nodes=graph_nodes,
            edges=graph_edges,
            depth=depth,
            truncated=truncated,
        )

    def _resolve_repository(self, identifier: str | Path | None) -> RepositoryRecord:
        return (
            self._repositories.active()
            if identifier is None
            else self._repositories.get(identifier)
        )


def parse_relation_kinds(value: str | None) -> frozenset[RelationKind] | None:
    if value is None or not value.strip():
        return None
    try:
        return frozenset(RelationKind(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise MonasLensError(
            ErrorCode.GRAPH_QUERY_INVALID,
            "Graph relation filters must use known relation names.",
            details={"relations": value},
        ) from exc


def parse_graph_direction(value: str) -> GraphDirection:
    try:
        return GraphDirection(value.strip())
    except ValueError as exc:
        raise MonasLensError(
            ErrorCode.GRAPH_QUERY_INVALID,
            "Graph direction must be outgoing, incoming, or both.",
            details={"direction": value},
        ) from exc


def _validate_bounds(depth: int, limit: int) -> None:
    if not 1 <= depth <= _MAX_DEPTH:
        raise MonasLensError(
            ErrorCode.GRAPH_QUERY_INVALID,
            f"Graph depth must be between 1 and {_MAX_DEPTH}.",
        )
    if not 1 <= limit <= _MAX_RESULTS:
        raise MonasLensError(
            ErrorCode.GRAPH_QUERY_INVALID,
            f"Graph result limit must be between 1 and {_MAX_RESULTS}.",
        )


def _resolve_node_ref(session: Session, repository_id: str, target: str) -> _NodeRef:
    if not target:
        raise MonasLensError(
            ErrorCode.GRAPH_QUERY_INVALID,
            "Graph target must not be empty.",
        )
    symbol_by_id = session.scalar(
        select(SymbolModel)
        .join(FileModel, FileModel.id == SymbolModel.file_id)
        .where(
            FileModel.repository_id == repository_id,
            SymbolModel.id == target,
        )
    )
    if symbol_by_id is not None:
        return _NodeRef("symbol", symbol_by_id.id, symbol_by_id.file_id, symbol_by_id.id)

    file = session.scalar(
        select(FileModel).where(
            FileModel.repository_id == repository_id,
            or_(FileModel.id == target, FileModel.relative_path == target),
        )
    )
    if file is not None:
        return _NodeRef("file", file.id, file.id, None)

    symbols = session.scalars(
        select(SymbolModel)
        .join(FileModel, FileModel.id == SymbolModel.file_id)
        .where(
            FileModel.repository_id == repository_id,
            or_(
                SymbolModel.qualified_name == target,
                SymbolModel.name == target,
            ),
        )
        .order_by(FileModel.relative_path, SymbolModel.start_line, SymbolModel.id)
    ).all()
    if len(symbols) == 1:
        symbol = symbols[0]
        return _NodeRef("symbol", symbol.id, symbol.file_id, symbol.id)
    if len(symbols) > 1:
        raise MonasLensError(
            ErrorCode.GRAPH_QUERY_INVALID,
            "The graph target is ambiguous; use a qualified name or symbol ID.",
            details={"target": target, "candidate_count": len(symbols)},
        )
    raise MonasLensError(
        ErrorCode.GRAPH_QUERY_INVALID,
        "The graph target was not found in the selected repository.",
        details={"target": target},
    )


def _incident_edges(
    session: Session,
    repository_id: str,
    frontier: set[_NodeRef],
    direction: GraphDirection,
    relation_kinds: frozenset[RelationKind] | None,
    limit: int,
) -> list[RelationshipModel]:
    outgoing: list[ColumnElement[bool]] = []
    incoming: list[ColumnElement[bool]] = []
    for node in frontier:
        if node.symbol_id is not None:
            outgoing.append(RelationshipModel.source_symbol_id == node.symbol_id)
            incoming.append(RelationshipModel.target_symbol_id == node.symbol_id)
        else:
            outgoing.append(
                and_(
                    RelationshipModel.source_file_id == node.file_id,
                    RelationshipModel.source_symbol_id.is_(None),
                )
            )
            incoming.append(
                and_(
                    RelationshipModel.target_file_id == node.file_id,
                    RelationshipModel.target_symbol_id.is_(None),
                )
            )
    predicates: list[ColumnElement[bool]] = []
    if direction in {GraphDirection.OUTGOING, GraphDirection.BOTH}:
        predicates.extend(outgoing)
    if direction in {GraphDirection.INCOMING, GraphDirection.BOTH}:
        predicates.extend(incoming)
    statement = select(RelationshipModel).where(
        RelationshipModel.repository_id == repository_id,
        or_(*predicates),
    )
    if relation_kinds:
        statement = statement.where(
            RelationshipModel.kind.in_(kind.value for kind in relation_kinds)
        )
    return list(
        session.scalars(
            statement.order_by(
                RelationshipModel.kind,
                RelationshipModel.source_file_id,
                RelationshipModel.source_symbol_id,
                RelationshipModel.target_file_id,
                RelationshipModel.target_symbol_id,
                RelationshipModel.id,
            ).limit(limit)
        ).all()
    )


def _edge_neighbors(
    source: _NodeRef,
    target: _NodeRef,
    frontier_keys: set[tuple[str, str]],
    direction: GraphDirection,
) -> tuple[_NodeRef, ...]:
    selected: list[_NodeRef] = []
    if direction in {GraphDirection.OUTGOING, GraphDirection.BOTH} and source.key in frontier_keys:
        selected.append(target)
    if direction in {GraphDirection.INCOMING, GraphDirection.BOTH} and target.key in frontier_keys:
        selected.append(source)
    return tuple(dict.fromkeys(selected))


def _edge_source(edge: RelationshipModel) -> _NodeRef:
    if edge.source_symbol_id is not None:
        return _NodeRef(
            "symbol",
            edge.source_symbol_id,
            edge.source_file_id,
            edge.source_symbol_id,
        )
    return _NodeRef("file", edge.source_file_id, edge.source_file_id, None)


def _edge_target(edge: RelationshipModel) -> _NodeRef:
    if edge.target_symbol_id is not None:
        return _NodeRef(
            "symbol",
            edge.target_symbol_id,
            edge.target_file_id,
            edge.target_symbol_id,
        )
    return _NodeRef("file", edge.target_file_id, edge.target_file_id, None)


def _graph_node(session: Session, reference: _NodeRef) -> GraphNode:
    file = session.get(FileModel, reference.file_id)
    if file is None:
        raise MonasLensError(
            ErrorCode.GRAPH_QUERY_INVALID,
            "A graph node references a missing file.",
        )
    if reference.symbol_id is None:
        return GraphNode(
            id=file.id,
            node_type="file",
            relative_path=file.relative_path,
            language=file.language,
            kind="file",
            name=Path(file.relative_path).name,
            qualified_name=None,
            start_line=1,
            end_line=None,
        )
    symbol = session.get(SymbolModel, reference.symbol_id)
    if symbol is None:
        raise MonasLensError(
            ErrorCode.GRAPH_QUERY_INVALID,
            "A graph edge references a missing symbol.",
        )
    return GraphNode(
        id=symbol.id,
        node_type="symbol",
        relative_path=file.relative_path,
        language=symbol.language,
        kind=symbol.kind,
        name=symbol.name,
        qualified_name=symbol.qualified_name,
        start_line=symbol.start_line,
        end_line=symbol.end_line,
    )


def _graph_edge(edge: RelationshipModel) -> GraphEdge:
    return GraphEdge(
        id=edge.id,
        kind=RelationKind(edge.kind),
        source_id=edge.source_symbol_id or edge.source_file_id,
        target_id=edge.target_symbol_id or edge.target_file_id,
        confidence=edge.confidence,
        resolution_strategy=edge.resolution_strategy,
    )
