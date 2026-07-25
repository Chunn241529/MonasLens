"""Incremental construction of deterministic repository relationships."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from monas_lens.db.models import (
    FileModel,
    RelationshipModel,
    RepositoryModel,
    ResolutionDiagnosticModel,
    SymbolModel,
    SyntaxFactModel,
    utc_now,
)
from monas_lens.db.session import Database
from monas_lens.graph.contracts import (
    DiagnosticReason,
    NormalizedFact,
    NormalizedTarget,
    RelationKind,
    TargetKind,
)
from monas_lens.graph.normalization import normalize_fact
from monas_lens.indexing.contracts import FactKind, Language, SymbolKind
from monas_lens.indexing.identity import stable_id

_TYPE_KINDS = {
    SymbolKind.CLASS.value,
    SymbolKind.INTERFACE.value,
    SymbolKind.ENUM.value,
    SymbolKind.MIXIN.value,
    SymbolKind.EXTENSION.value,
    SymbolKind.TYPE_ALIAS.value,
}


@dataclass(frozen=True, slots=True)
class GraphCounts:
    relationships: int
    diagnostics: int
    unresolved: int
    ambiguous: int
    unsupported: int


@dataclass(frozen=True, slots=True)
class GraphBuildSummary:
    refreshed_facts: int
    relationships: int
    diagnostics: int
    full_rebuild: bool
    duration_ms: float


@dataclass(frozen=True, slots=True)
class _FileRecord:
    id: str
    relative_path: str
    language: Language


@dataclass(frozen=True, slots=True)
class _SymbolRecord:
    id: str
    file_id: str
    kind: str
    name: str
    qualified_name: str


@dataclass(frozen=True, slots=True)
class _FactRecord:
    id: str
    file_id: str
    relative_path: str
    language: Language
    kind: FactKind
    target_text: str
    source_symbol_id: str | None
    start_line: int


@dataclass(frozen=True, slots=True)
class _ImportBinding:
    target_file_id: str
    imported_name: str | None


@dataclass(frozen=True, slots=True)
class _Endpoint:
    file_id: str
    symbol_id: str | None


@dataclass(frozen=True, slots=True)
class _Resolution:
    candidates: tuple[_Endpoint, ...]
    strategy: str
    confidence: float
    reason: DiagnosticReason | None


@dataclass(slots=True)
class _GraphData:
    files_by_id: dict[str, _FileRecord]
    files_by_path: dict[str, tuple[_FileRecord, ...]]
    symbols_by_id: dict[str, _SymbolRecord]
    symbols_by_name: dict[str, tuple[_SymbolRecord, ...]]
    symbols_by_file: dict[str, tuple[_SymbolRecord, ...]]
    facts: tuple[_FactRecord, ...]
    normalized: dict[str, NormalizedFact]
    bindings: dict[str, dict[str, tuple[_ImportBinding, ...]]]


class GraphBuilder:
    def __init__(self, database: Database) -> None:
        self._database = database

    def is_dirty(self, repository_id: str) -> bool:
        with self._database.session() as session:
            repository = session.get(RepositoryModel, repository_id)
            return repository is not None and repository.graph_dirty

    def snapshot_keys(
        self,
        repository_id: str,
        paths: set[str],
    ) -> dict[str, frozenset[str]]:
        if not paths:
            return {}
        with self._database.session() as session:
            files = session.scalars(
                select(FileModel).where(
                    FileModel.repository_id == repository_id,
                    FileModel.relative_path.in_(paths),
                )
            ).all()
            file_ids = [file.id for file in files]
            symbols: list[SymbolModel] = (
                list(
                    session.scalars(
                        select(SymbolModel).where(SymbolModel.file_id.in_(file_ids))
                    ).all()
                )
                if file_ids
                else []
            )
        keys = {file.relative_path: {f"path:{file.relative_path.casefold()}"} for file in files}
        paths_by_file = {file.id: file.relative_path for file in files}
        for symbol in symbols:
            path = paths_by_file[symbol.file_id]
            keys[path].update(
                {
                    f"symbol:{symbol.name.casefold()}",
                    f"qualified:{symbol.qualified_name.casefold()}",
                }
            )
        return {path: frozenset(values) for path, values in keys.items()}

    def refresh(
        self,
        repository_id: str,
        *,
        changed_paths: set[str],
        previous_keys: Mapping[str, frozenset[str]],
        force_full: bool = False,
    ) -> GraphBuildSummary:
        started = perf_counter()
        with self._database.session() as session:
            data = _load_graph_data(session, repository_id)
            current_keys = _keys_for_paths(data, changed_paths)
            affected_keys = frozenset(
                key
                for path in changed_paths
                for key in (*previous_keys.get(path, ()), *current_keys.get(path, ()))
            )
            selected = (
                data.facts
                if force_full
                else tuple(
                    fact
                    for fact in data.facts
                    if fact.relative_path in changed_paths
                    or bool(data.normalized[fact.id].dependency_keys & affected_keys)
                )
            )
            _delete_previous_results(
                session,
                repository_id,
                selected,
                full_rebuild=force_full,
            )
            relationships, diagnostics = _build_results(repository_id, selected, data)
            existing_ids = set(
                session.scalars(
                    select(RelationshipModel.id).where(
                        RelationshipModel.repository_id == repository_id
                    )
                ).all()
            )
            session.add_all(
                relationship
                for relationship in relationships.values()
                if relationship.id not in existing_ids
            )
            session.add_all(diagnostics.values())

            repository = session.get(RepositoryModel, repository_id)
            if repository is not None:
                repository.graph_dirty = False
                repository.graph_updated_at = utc_now()
            session.commit()
            counts = _counts(session, repository_id)
        return GraphBuildSummary(
            refreshed_facts=len(selected),
            relationships=counts.relationships,
            diagnostics=counts.diagnostics,
            full_rebuild=force_full,
            duration_ms=round((perf_counter() - started) * 1_000, 3),
        )

    def counts(self, repository_id: str) -> GraphCounts:
        with self._database.session() as session:
            return _counts(session, repository_id)


def _load_graph_data(session: Session, repository_id: str) -> _GraphData:
    file_models = session.scalars(
        select(FileModel)
        .where(FileModel.repository_id == repository_id)
        .order_by(FileModel.relative_path, FileModel.id)
    ).all()
    files = tuple(
        _FileRecord(
            id=model.id,
            relative_path=model.relative_path,
            language=Language(model.language),
        )
        for model in file_models
    )
    file_ids = [file.id for file in files]
    symbol_models: list[SymbolModel] = (
        list(
            session.scalars(
                select(SymbolModel)
                .where(SymbolModel.file_id.in_(file_ids))
                .order_by(SymbolModel.file_id, SymbolModel.start_line, SymbolModel.id)
            ).all()
        )
        if file_ids
        else []
    )
    symbols = tuple(
        _SymbolRecord(
            id=model.id,
            file_id=model.file_id,
            kind=model.kind,
            name=model.name,
            qualified_name=model.qualified_name,
        )
        for model in symbol_models
    )
    file_by_id = {file.id: file for file in files}
    fact_models: list[SyntaxFactModel] = (
        list(
            session.scalars(
                select(SyntaxFactModel)
                .where(SyntaxFactModel.file_id.in_(file_ids))
                .order_by(
                    SyntaxFactModel.file_id,
                    SyntaxFactModel.start_line,
                    SyntaxFactModel.id,
                )
            ).all()
        )
        if file_ids
        else []
    )
    facts = tuple(
        _FactRecord(
            id=model.id,
            file_id=model.file_id,
            relative_path=file_by_id[model.file_id].relative_path,
            language=file_by_id[model.file_id].language,
            kind=FactKind(model.kind),
            target_text=model.target_text,
            source_symbol_id=model.source_symbol_id,
            start_line=model.start_line,
        )
        for model in fact_models
    )
    normalized = {
        fact.id: normalize_fact(
            fact.language,
            fact.kind,
            fact.target_text,
            fact.relative_path,
        )
        for fact in facts
    }
    data = _GraphData(
        files_by_id=file_by_id,
        files_by_path=_group_files_by_path(files),
        symbols_by_id={symbol.id: symbol for symbol in symbols},
        symbols_by_name=_group_symbols(symbols, lambda symbol: symbol.name),
        symbols_by_file=_group_symbols(symbols, lambda symbol: symbol.file_id),
        facts=facts,
        normalized=normalized,
        bindings={},
    )
    data.bindings = _build_import_bindings(data)
    return data


def _build_import_bindings(
    data: _GraphData,
) -> dict[str, dict[str, tuple[_ImportBinding, ...]]]:
    mutable: dict[str, dict[str, list[_ImportBinding]]] = {}
    for fact in data.facts:
        normalized = data.normalized[fact.id]
        if normalized.relation_kind is not RelationKind.IMPORTS:
            continue
        for target in normalized.targets:
            if target.alias is None:
                continue
            resolution = _resolve_module(target, data)
            if resolution.reason is not None or len(resolution.candidates) != 1:
                continue
            binding = _ImportBinding(
                target_file_id=resolution.candidates[0].file_id,
                imported_name=target.imported_name,
            )
            aliases = mutable.setdefault(fact.file_id, {})
            aliases.setdefault(target.alias, []).append(binding)
    return {
        file_id: {alias: tuple(dict.fromkeys(bindings)) for alias, bindings in aliases.items()}
        for file_id, aliases in mutable.items()
    }


def _build_results(
    repository_id: str,
    facts: tuple[_FactRecord, ...],
    data: _GraphData,
) -> tuple[dict[str, RelationshipModel], dict[str, ResolutionDiagnosticModel]]:
    relationships: dict[str, RelationshipModel] = {}
    diagnostics: dict[str, ResolutionDiagnosticModel] = {}
    for fact in facts:
        normalized = data.normalized[fact.id]
        if not normalized.supported:
            diagnostic = _diagnostic_model(
                repository_id,
                fact,
                DiagnosticReason.UNSUPPORTED,
                normalized_target="",
                details={"normalizer": normalized.diagnostic or "unsupported"},
            )
            diagnostics[diagnostic.id] = diagnostic
            continue
        if normalized.relation_kind is None:
            continue
        for target in normalized.targets:
            resolution = _resolve_target(fact, normalized.relation_kind, target, data)
            if resolution.reason is not None:
                diagnostic = _diagnostic_model(
                    repository_id,
                    fact,
                    resolution.reason,
                    normalized_target=_target_label(target),
                    details={
                        "candidate_count": len(resolution.candidates),
                        "strategy": resolution.strategy,
                    },
                )
                diagnostics[diagnostic.id] = diagnostic
                continue
            endpoint = resolution.candidates[0]
            relationship = _relationship_model(
                repository_id,
                fact,
                normalized.relation_kind,
                endpoint,
                target,
                resolution,
            )
            relationships.setdefault(relationship.id, relationship)
            tested_by = _tested_by_relationship(
                repository_id,
                fact,
                endpoint,
                target,
                resolution,
                data,
            )
            if tested_by is not None:
                relationships.setdefault(tested_by.id, tested_by)
    return relationships, diagnostics


def _resolve_target(
    fact: _FactRecord,
    relation_kind: RelationKind,
    target: NormalizedTarget,
    data: _GraphData,
) -> _Resolution:
    if target.kind is TargetKind.MODULE:
        return _resolve_module(target, data)
    if target.kind is TargetKind.CONFIGURATION:
        return _resolve_configuration(fact, target, data)
    return _resolve_symbol(fact, relation_kind, target, data)


def _resolve_module(target: NormalizedTarget, data: _GraphData) -> _Resolution:
    candidates = tuple(
        _Endpoint(file.id, None)
        for path in target.candidate_paths
        for file in data.files_by_path.get(path.casefold(), ())
    )
    return _finalize_resolution(candidates, "module_path", 0.98)


def _resolve_configuration(
    fact: _FactRecord,
    target: NormalizedTarget,
    data: _GraphData,
) -> _Resolution:
    candidates = tuple(
        symbol
        for symbol in data.symbols_by_name.get(target.value, ())
        if symbol.kind == SymbolKind.CONSTANT.value
    )
    same_file = tuple(symbol for symbol in candidates if symbol.file_id == fact.file_id)
    if same_file:
        return _symbol_resolution(same_file, "same_file_configuration", 1.0)
    return _symbol_resolution(candidates, "repository_configuration", 0.85)


def _resolve_symbol(
    fact: _FactRecord,
    relation_kind: RelationKind,
    target: NormalizedTarget,
    data: _GraphData,
) -> _Resolution:
    allowed_kinds = (
        _TYPE_KINDS
        if relation_kind
        in {
            RelationKind.INHERITS,
            RelationKind.IMPLEMENTS,
        }
        else None
    )
    source_symbol = (
        data.symbols_by_id.get(fact.source_symbol_id) if fact.source_symbol_id is not None else None
    )
    tiers: list[tuple[str, float, tuple[_SymbolRecord, ...]]] = []

    if (
        target.qualifier in {"self", "this", "super"}
        and source_symbol is not None
        and "." in source_symbol.qualified_name
    ):
        owner = source_symbol.qualified_name.rsplit(".", 1)[0]
        tiers.append(
            (
                "receiver_scope",
                1.0,
                _symbols_matching(
                    data,
                    file_id=fact.file_id,
                    qualified_name=f"{owner}.{target.value}",
                    allowed_kinds=allowed_kinds,
                ),
            )
        )

    if target.qualifier is not None:
        imported = _symbols_from_binding(
            data,
            fact.file_id,
            target.qualifier,
            target.value,
            constructor=False,
            allowed_kinds=allowed_kinds,
        )
        tiers.append(("import_alias_member", 0.98, imported))
        tiers.append(
            (
                "same_file_qualified",
                0.96,
                _symbols_matching(
                    data,
                    file_id=fact.file_id,
                    qualified_name=f"{target.qualifier}.{target.value}",
                    allowed_kinds=allowed_kinds,
                ),
            )
        )
    else:
        imported = _symbols_from_binding(
            data,
            fact.file_id,
            target.value,
            target.value,
            constructor=True,
            allowed_kinds=allowed_kinds,
        )
        tiers.append(("import_alias_symbol", 0.98, imported))

    tiers.append(
        (
            "same_file_name",
            0.92,
            _symbols_matching(
                data,
                file_id=fact.file_id,
                name=target.value,
                allowed_kinds=allowed_kinds,
            ),
        )
    )
    repository_candidates = tuple(
        symbol
        for symbol in data.symbols_by_name.get(target.value, ())
        if allowed_kinds is None or symbol.kind in allowed_kinds
    )
    tiers.append(("repository_unique_name", 0.75, repository_candidates))

    for strategy, confidence, candidates in tiers:
        if candidates:
            return _symbol_resolution(candidates, strategy, confidence)
    return _Resolution((), "no_candidate", 0.0, DiagnosticReason.UNRESOLVED)


def _symbols_from_binding(
    data: _GraphData,
    source_file_id: str,
    alias: str,
    value: str,
    *,
    constructor: bool,
    allowed_kinds: set[str] | None,
) -> tuple[_SymbolRecord, ...]:
    bindings = data.bindings.get(source_file_id, {}).get(alias, ())
    candidates: list[_SymbolRecord] = []
    for binding in bindings:
        for symbol in data.symbols_by_file.get(binding.target_file_id, ()):
            if allowed_kinds is not None and symbol.kind not in allowed_kinds:
                continue
            if constructor:
                expected = binding.imported_name or alias
                if symbol.name == expected:
                    candidates.append(symbol)
            elif binding.imported_name is None:
                if symbol.name == value:
                    candidates.append(symbol)
            elif (
                symbol.qualified_name == f"{binding.imported_name}.{value}"
                or symbol.qualified_name.endswith(f".{binding.imported_name}.{value}")
            ):
                candidates.append(symbol)
    return tuple(dict.fromkeys(candidates))


def _symbols_matching(
    data: _GraphData,
    *,
    file_id: str,
    name: str | None = None,
    qualified_name: str | None = None,
    allowed_kinds: set[str] | None,
) -> tuple[_SymbolRecord, ...]:
    return tuple(
        symbol
        for symbol in data.symbols_by_file.get(file_id, ())
        if (name is None or symbol.name == name)
        and (
            qualified_name is None
            or symbol.qualified_name == qualified_name
            or symbol.qualified_name.endswith(f".{qualified_name}")
        )
        and (allowed_kinds is None or symbol.kind in allowed_kinds)
    )


def _finalize_resolution(
    candidates: tuple[_Endpoint, ...],
    strategy: str,
    confidence: float,
) -> _Resolution:
    unique = tuple(dict.fromkeys(candidates))
    if len(unique) == 1:
        return _Resolution(unique, strategy, confidence, None)
    if len(unique) > 1:
        return _Resolution(unique, strategy, 0.0, DiagnosticReason.AMBIGUOUS)
    return _Resolution((), strategy, 0.0, DiagnosticReason.UNRESOLVED)


def _symbol_resolution(
    symbols: tuple[_SymbolRecord, ...],
    strategy: str,
    confidence: float,
) -> _Resolution:
    return _finalize_resolution(
        tuple(_Endpoint(symbol.file_id, symbol.id) for symbol in symbols),
        strategy,
        confidence,
    )


def _relationship_model(
    repository_id: str,
    fact: _FactRecord,
    kind: RelationKind,
    endpoint: _Endpoint,
    target: NormalizedTarget,
    resolution: _Resolution,
) -> RelationshipModel:
    relationship_id = _relationship_id(
        repository_id,
        fact.file_id,
        fact.source_symbol_id,
        endpoint.file_id,
        endpoint.symbol_id,
        kind,
    )
    return RelationshipModel(
        id=relationship_id,
        repository_id=repository_id,
        fact_id=fact.id,
        source_file_id=fact.file_id,
        source_symbol_id=fact.source_symbol_id,
        target_file_id=endpoint.file_id,
        target_symbol_id=endpoint.symbol_id,
        kind=kind.value,
        confidence=resolution.confidence,
        resolution_strategy=resolution.strategy,
        raw_target=_bounded(fact.target_text),
        normalized_target=_bounded(_target_label(target)),
        metadata_json={},
    )


def _tested_by_relationship(
    repository_id: str,
    fact: _FactRecord,
    endpoint: _Endpoint,
    target: NormalizedTarget,
    resolution: _Resolution,
    data: _GraphData,
) -> RelationshipModel | None:
    if fact.kind is not FactKind.CALL or fact.source_symbol_id is None:
        return None
    source = data.symbols_by_id.get(fact.source_symbol_id)
    target_symbol = (
        data.symbols_by_id.get(endpoint.symbol_id) if endpoint.symbol_id is not None else None
    )
    if (
        source is None
        or source.kind != SymbolKind.TEST.value
        or target_symbol is None
        or target_symbol.kind == SymbolKind.TEST.value
    ):
        return None
    relationship_id = _relationship_id(
        repository_id,
        target_symbol.file_id,
        target_symbol.id,
        source.file_id,
        source.id,
        RelationKind.TESTED_BY,
    )
    return RelationshipModel(
        id=relationship_id,
        repository_id=repository_id,
        fact_id=fact.id,
        source_file_id=target_symbol.file_id,
        source_symbol_id=target_symbol.id,
        target_file_id=source.file_id,
        target_symbol_id=source.id,
        kind=RelationKind.TESTED_BY.value,
        confidence=resolution.confidence,
        resolution_strategy=resolution.strategy,
        raw_target=_bounded(fact.target_text),
        normalized_target=_bounded(_target_label(target)),
        metadata_json={},
    )


def _relationship_id(
    repository_id: str,
    source_file_id: str,
    source_symbol_id: str | None,
    target_file_id: str,
    target_symbol_id: str | None,
    kind: RelationKind,
) -> str:
    return stable_id(
        "relationship",
        repository_id,
        source_file_id,
        source_symbol_id or "",
        target_file_id,
        target_symbol_id or "",
        kind.value,
    )


def _diagnostic_model(
    repository_id: str,
    fact: _FactRecord,
    reason: DiagnosticReason,
    *,
    normalized_target: str,
    details: dict[str, object],
) -> ResolutionDiagnosticModel:
    diagnostic_id = stable_id(
        "resolution-diagnostic",
        repository_id,
        fact.id,
        reason.value,
        normalized_target,
    )
    return ResolutionDiagnosticModel(
        id=diagnostic_id,
        repository_id=repository_id,
        file_id=fact.file_id,
        fact_id=fact.id,
        reason=reason.value,
        fact_kind=fact.kind.value,
        raw_target=_bounded(fact.target_text),
        normalized_target=_bounded(normalized_target),
        details_json=details,
    )


def _delete_previous_results(
    session: Session,
    repository_id: str,
    facts: tuple[_FactRecord, ...],
    *,
    full_rebuild: bool,
) -> None:
    if full_rebuild:
        session.execute(
            delete(RelationshipModel).where(RelationshipModel.repository_id == repository_id)
        )
        session.execute(
            delete(ResolutionDiagnosticModel).where(
                ResolutionDiagnosticModel.repository_id == repository_id
            )
        )
        return
    fact_ids = [fact.id for fact in facts]
    if not fact_ids:
        return
    session.execute(delete(RelationshipModel).where(RelationshipModel.fact_id.in_(fact_ids)))
    session.execute(
        delete(ResolutionDiagnosticModel).where(ResolutionDiagnosticModel.fact_id.in_(fact_ids))
    )


def _counts(session: Session, repository_id: str) -> GraphCounts:
    relationships = session.scalar(
        select(func.count())
        .select_from(RelationshipModel)
        .where(RelationshipModel.repository_id == repository_id)
    )
    diagnostic_counts: dict[str, int] = {}
    rows = session.execute(
        select(ResolutionDiagnosticModel.reason, func.count())
        .where(ResolutionDiagnosticModel.repository_id == repository_id)
        .group_by(ResolutionDiagnosticModel.reason)
    ).tuples()
    for reason, count in rows:
        diagnostic_counts[reason] = count
    return GraphCounts(
        relationships=relationships or 0,
        diagnostics=sum(diagnostic_counts.values()),
        unresolved=diagnostic_counts.get(DiagnosticReason.UNRESOLVED.value, 0),
        ambiguous=diagnostic_counts.get(DiagnosticReason.AMBIGUOUS.value, 0),
        unsupported=diagnostic_counts.get(DiagnosticReason.UNSUPPORTED.value, 0),
    )


def _keys_for_paths(
    data: _GraphData,
    paths: set[str],
) -> dict[str, frozenset[str]]:
    keys: dict[str, set[str]] = {path: {f"path:{path.casefold()}"} for path in paths}
    file_ids = {
        file.id: file.relative_path
        for file in data.files_by_id.values()
        if file.relative_path in paths
    }
    for symbol in data.symbols_by_id.values():
        path = file_ids.get(symbol.file_id)
        if path is None:
            continue
        keys[path].update(
            {
                f"symbol:{symbol.name.casefold()}",
                f"qualified:{symbol.qualified_name.casefold()}",
            }
        )
    return {path: frozenset(values) for path, values in keys.items()}


def _group_files_by_path(
    files: tuple[_FileRecord, ...],
) -> dict[str, tuple[_FileRecord, ...]]:
    mutable: dict[str, list[_FileRecord]] = {}
    for file in files:
        mutable.setdefault(file.relative_path.casefold(), []).append(file)
    return {key: tuple(values) for key, values in mutable.items()}


def _group_symbols(
    symbols: tuple[_SymbolRecord, ...],
    key: Callable[[_SymbolRecord], str],
) -> dict[str, tuple[_SymbolRecord, ...]]:
    mutable: dict[str, list[_SymbolRecord]] = {}
    for symbol in symbols:
        selected_key = key(symbol)
        mutable.setdefault(selected_key, []).append(symbol)
    return {selected_key: tuple(values) for selected_key, values in mutable.items()}


def _target_label(target: NormalizedTarget) -> str:
    return f"{target.qualifier}.{target.value}" if target.qualifier else target.value


def _bounded(value: str) -> str:
    return value[:500]
