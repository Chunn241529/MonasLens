"""Deterministic Phase 5 retrieval-efficiency release gate."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from monas_lens.config import Settings, ensure_runtime_directories
from monas_lens.db.migration import upgrade_database
from monas_lens.db.models import ChunkModel, FileModel, SymbolModel, SyntaxFactModel
from monas_lens.db.session import Database
from monas_lens.indexing.service import IndexService
from monas_lens.mcp.service import CommunityTools
from monas_lens.repositories import RepositoryService
from monas_lens.retrieval.contracts import ContextBundle, ContextSnippet
from monas_lens.retrieval.token_estimator import HeuristicTokenEstimator

_RELEASE_THRESHOLDS = {
    "primary_top_1_recall": 0.95,
    "primary_top_3_recall": 1.0,
    "required_related_recall": 1.0,
    "optional_related_recall": 0.90,
    "median_discovery_calls": 1.0,
    "p95_discovery_calls": 2.0,
    "manual_fallback_count": 0,
    "duplicate_content_hash_count": 0,
    "token_reduction_ratio": 0.60,
    "p95_retrieval_latency_ms": 500.0,
}


@dataclass(frozen=True, slots=True)
class GoldSymbol:
    relative_path: str
    qualified_name: str

    @property
    def identity(self) -> str:
        return f"{self.relative_path}::{self.qualified_name}"


@dataclass(frozen=True, slots=True)
class RoleExpectation:
    role: str
    symbols: tuple[GoldSymbol, ...]


@dataclass(frozen=True, slots=True)
class GoldTask:
    case_id: str
    category: str
    task: str
    expected_primary_symbols: tuple[GoldSymbol, ...]
    required_related_symbols: tuple[RoleExpectation, ...] = ()
    optional_related_symbols: tuple[RoleExpectation, ...] = ()
    focus_targets: tuple[str, ...] = ()
    max_discovery_calls: int = 1
    expansion_permitted: bool = False
    expansion_focus: str | None = None
    expected_next_action: str = "none"


@dataclass(frozen=True, slots=True)
class _WorkflowResult:
    retrieval_payloads: tuple[dict[str, Any], ...]
    primary_identities: tuple[str, ...]
    primary_scores: tuple[dict[str, Any], ...]
    related_identities: Mapping[str, frozenset[str]]
    content_hashes: tuple[str, ...]
    returned_tokens: int
    discovery_calls: int
    next_action: str
    next_action_reason: str
    confidence: dict[str, Any]
    diagnostic_codes: tuple[str, ...]
    diagnostic_messages: tuple[str, ...]
    fallback_reasons: tuple[str, ...]
    latencies_ms: tuple[float, ...]


GOLD_TASKS = (
    GoldTask(
        case_id="exact-function",
        category="exact_lookup",
        task="Explain exact_target",
        expected_primary_symbols=(GoldSymbol("exact.py", "exact_target"),),
    ),
    GoldTask(
        case_id="exact-class",
        category="exact_lookup",
        task="Explain ExactService",
        expected_primary_symbols=(GoldSymbol("exact.py", "ExactService"),),
    ),
    GoldTask(
        case_id="same-name-focused",
        category="same_name_ambiguity",
        task="Fix duplicate in alpha/duplicate.py",
        focus_targets=("alpha/duplicate.py",),
        expected_primary_symbols=(GoldSymbol("alpha/duplicate.py", "duplicate"),),
    ),
    GoldTask(
        case_id="method-callers-callees",
        category="method_closure",
        task="Fix PaymentService.run and inspect its callers and callees",
        expected_primary_symbols=(GoldSymbol("service.py", "PaymentService.run"),),
        required_related_symbols=(
            RoleExpectation(
                "caller",
                (GoldSymbol("controller.py", "checkout"),),
            ),
            RoleExpectation(
                "dependency",
                (GoldSymbol("service.py", "PaymentService.validate"),),
            ),
        ),
        max_discovery_calls=2,
        expansion_permitted=True,
        expansion_focus="PaymentService.run",
    ),
    GoldTask(
        case_id="import-alias-qualified-call",
        category="import_alias",
        task="Refactor provide and inspect imported alias callers",
        expected_primary_symbols=(GoldSymbol("provider.py", "provide"),),
        required_related_symbols=(
            RoleExpectation("caller", (GoldSymbol("consumer.py", "consume"),)),
        ),
        max_discovery_calls=2,
        expansion_permitted=True,
        expansion_focus="provide",
    ),
    GoldTask(
        case_id="interface-implementation",
        category="interface_implementation",
        task="Refactor Runner and inspect every implementation",
        expected_primary_symbols=(GoldSymbol("contracts.ts", "Runner"),),
        required_related_symbols=(
            RoleExpectation(
                "implementation",
                (GoldSymbol("runner.ts", "LocalRunner"),),
            ),
        ),
        max_discovery_calls=2,
        expansion_permitted=True,
        expansion_focus="Runner",
    ),
    GoldTask(
        case_id="inheritance-override",
        category="inheritance_override",
        task="Refactor BaseWorker.run and inspect overrides",
        expected_primary_symbols=(GoldSymbol("base_worker.py", "BaseWorker.run"),),
        required_related_symbols=(
            RoleExpectation(
                "implementation",
                (GoldSymbol("worker.py", "Worker.run"),),
            ),
        ),
        max_discovery_calls=2,
        expansion_permitted=True,
        expansion_focus="BaseWorker.run",
    ),
    GoldTask(
        case_id="barrel-reexport",
        category="exports_reexports",
        task="Refactor fetchUser through the public barrel export",
        expected_primary_symbols=(GoldSymbol("api.ts", "fetchUser"),),
        required_related_symbols=(
            RoleExpectation(
                "caller",
                (GoldSymbol("export_consumer.ts", "useUser"),),
            ),
        ),
        max_discovery_calls=2,
        expansion_permitted=True,
        expansion_focus="fetchUser",
    ),
    GoldTask(
        case_id="route-handler-schema",
        category="framework_registration",
        task="Fix create_user route handler and its request schema",
        expected_primary_symbols=(GoldSymbol("routes.py", "create_user"),),
        required_related_symbols=(
            RoleExpectation("schema", (GoldSymbol("schemas.py", "UserCreate"),)),
        ),
        max_discovery_calls=2,
        expansion_permitted=True,
        expansion_focus="create_user",
    ),
    GoldTask(
        case_id="configuration-dependency",
        category="configuration",
        task="Fix the API_URL configuration dependency in load_config",
        expected_primary_symbols=(GoldSymbol("configuration.py", "load_config"),),
        required_related_symbols=(
            RoleExpectation(
                "configuration",
                (GoldSymbol("configuration.py", "load_config"),),
            ),
        ),
    ),
    GoldTask(
        case_id="production-regression-test",
        category="regression_tests",
        task="Fix PaymentService.run and include its regression test",
        expected_primary_symbols=(GoldSymbol("service.py", "PaymentService.run"),),
        required_related_symbols=(
            RoleExpectation("test", (GoldSymbol("test_service.py", "test_run"),)),
        ),
        optional_related_symbols=(
            RoleExpectation("caller", (GoldSymbol("controller.py", "checkout"),)),
        ),
        max_discovery_calls=2,
        expansion_permitted=True,
        expansion_focus="PaymentService.run",
    ),
    GoldTask(
        case_id="relevant-git-diff",
        category="git_diff",
        task="Explain the current change to changed_target",
        expected_primary_symbols=(GoldSymbol("changed.py", "changed_target"),),
        required_related_symbols=(
            RoleExpectation("git_diff", (GoldSymbol("changed.py", "changed_target"),)),
        ),
        expected_next_action="refresh_index",
    ),
    GoldTask(
        case_id="stale-index-recovery",
        category="stale_recovery",
        task="Fix stale_target using the current source",
        expected_primary_symbols=(GoldSymbol("stale.py", "stale_target"),),
        expected_next_action="refresh_index",
    ),
)


def run_quality_gate(
    *,
    repetitions: int = 3,
    enforce: bool = True,
) -> dict[str, Any]:
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")

    with tempfile.TemporaryDirectory(prefix="monas-lens-phase5-quality-") as temporary:
        workspace = Path(temporary)
        repository_root = workspace / "repository"
        _write_fixture(repository_root)
        _initialize_git(repository_root)
        settings = Settings(data_dir=workspace / "state")
        ensure_runtime_directories(settings)
        database = Database(settings)
        try:
            upgrade_database(database.engine)
            repository = RepositoryService(database, settings).add(repository_root)
            index_summary = IndexService(database, settings).build(repository.id)
            _write_worktree_changes(repository_root)
            tools = CommunityTools(database, settings)
            workflows: list[tuple[GoldTask, _WorkflowResult]] = []
            deterministic = True
            all_latencies: list[float] = []

            for case in GOLD_TASKS:
                repeated = tuple(
                    _execute_case(
                        case,
                        tools=tools,
                        database=database,
                        repository_id=repository.id,
                    )
                    for _iteration in range(repetitions)
                )
                canonical_payload = _stable_json(repeated[0].retrieval_payloads)
                deterministic = deterministic and all(
                    _stable_json(item.retrieval_payloads) == canonical_payload
                    for item in repeated[1:]
                )
                workflows.append((case, repeated[0]))
                all_latencies.extend(latency for item in repeated for latency in item.latencies_ms)

            report = _build_report(
                repository_root,
                index_summary.duration_ms,
                workflows,
                all_latencies,
                repetitions=repetitions,
                deterministic=deterministic,
            )
        finally:
            database.dispose()

    if enforce and not report["release_gate"]["passed"]:
        raise SystemExit(1)
    return report


def _execute_case(
    case: GoldTask,
    *,
    tools: CommunityTools,
    database: Database,
    repository_id: str,
) -> _WorkflowResult:
    started = perf_counter()
    bundle = tools.resolve_task_context(
        case.task,
        repository_id,
        focus_targets=case.focus_targets,
        max_tokens=3_000,
        include_git_diff=True,
    )
    latencies = [(perf_counter() - started) * 1_000]
    payloads: list[dict[str, Any]] = [bundle.model_dump(mode="json")]
    snippets = list(bundle.snippets)
    primary_identities = _primary_identities(bundle)
    related = _related_identities(database, bundle.snippets)
    missing_required = _missing_related(case.required_related_symbols, related)
    next_action, recommended_focus = _next_action(
        bundle,
        case,
        missing_required=missing_required,
    )
    fallback_reasons: list[str] = []
    discovery_calls = 1

    if next_action == "expand":
        if not case.expansion_permitted or discovery_calls >= case.max_discovery_calls:
            fallback_reasons.append("expansion_not_permitted")
        elif recommended_focus is None:
            fallback_reasons.append("expansion_focus_unavailable")
        else:
            started = perf_counter()
            expansion = tools.expand_context(
                case.task,
                recommended_focus,
                repository_id,
                known_content_hashes=tuple(item.content_hash for item in snippets),
                max_tokens=3_000,
            )
            latencies.append((perf_counter() - started) * 1_000)
            payloads.append(expansion.model_dump(mode="json"))
            discovery_calls += 1
            snippets.extend(expansion.snippets)
            _merge_related(related, _related_identities(database, expansion.snippets))
            missing_required = _missing_related(case.required_related_symbols, related)
    elif next_action == "manual_fallback":
        fallback_reasons.append("retrieval_requested_manual_fallback")

    if next_action != case.expected_next_action:
        fallback_reasons.append(f"next_action_mismatch:{next_action}!={case.expected_next_action}")
    if missing_required:
        fallback_reasons.extend(
            f"missing_required:{role}:{identity}"
            for role, identities in sorted(missing_required.items())
            for identity in sorted(identities)
        )
    if discovery_calls > case.max_discovery_calls:
        fallback_reasons.append("discovery_call_budget_exceeded")

    return _WorkflowResult(
        retrieval_payloads=tuple(payloads),
        primary_identities=primary_identities,
        primary_scores=tuple(
            {
                "identity": _symbol_identity(
                    target.candidate.relative_path,
                    target.candidate.qualified_name or target.candidate.name,
                ),
                "entity_id": target.candidate.entity_id,
                "entity_type": target.candidate.entity_type.value,
                "score": target.score,
                "components": target.components.model_dump(mode="json"),
            }
            for target in bundle.primary_targets[:3]
            if target.candidate.qualified_name or target.candidate.name
        ),
        related_identities={role: frozenset(values) for role, values in related.items()},
        content_hashes=tuple(item.content_hash for item in snippets),
        returned_tokens=sum(item.token_estimate.estimated_tokens for item in snippets),
        discovery_calls=discovery_calls,
        next_action=next_action,
        next_action_reason=bundle.next_action.reason.value,
        confidence=bundle.confidence.model_dump(mode="json"),
        diagnostic_codes=tuple(diagnostic.code.value for diagnostic in bundle.diagnostics),
        diagnostic_messages=tuple(diagnostic.message for diagnostic in bundle.diagnostics),
        fallback_reasons=tuple(sorted(set(fallback_reasons))),
        latencies_ms=tuple(latencies),
    )


def _next_action(
    bundle: ContextBundle,
    case: GoldTask,
    *,
    missing_required: Mapping[str, set[str]],
) -> tuple[str, str | None]:
    payload = bundle.model_dump(mode="json")
    raw_action = payload.get("next_action")
    if isinstance(raw_action, dict):
        kind = raw_action.get("kind")
        if isinstance(kind, str):
            focus = payload.get("recommended_focus_target")
            return kind, focus if isinstance(focus, str) else None
    if missing_required and case.expansion_permitted:
        return "expand", case.expansion_focus
    if missing_required:
        return "manual_fallback", None
    return "none", None


def _primary_identities(bundle: ContextBundle) -> tuple[str, ...]:
    return tuple(
        _symbol_identity(
            target.candidate.relative_path,
            target.candidate.qualified_name or target.candidate.name,
        )
        for target in bundle.primary_targets
        if target.candidate.qualified_name or target.candidate.name
    )


def _related_identities(
    database: Database,
    snippets: Sequence[ContextSnippet],
) -> dict[str, set[str]]:
    selected: dict[str, set[str]] = defaultdict(set)
    with database.session() as session:
        for snippet in snippets:
            for reference in snippet.provenance:
                symbol = _symbol_for_reference(
                    session,
                    entity_type=reference.entity_type.value,
                    entity_id=reference.entity_id,
                    relative_path=reference.relative_path,
                    start_line=reference.start_line,
                    end_line=reference.end_line,
                )
                if symbol is not None:
                    identity = _symbol_identity(symbol[0], symbol[1])
                    for role in snippet.roles:
                        selected[role.value].add(identity)
    return dict(selected)


def _symbol_for_reference(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    relative_path: str,
    start_line: int,
    end_line: int,
) -> tuple[str, str] | None:
    symbol: SymbolModel | None = None
    if entity_type == "symbol":
        symbol = session.get(SymbolModel, entity_id)
    elif entity_type == "chunk":
        chunk = session.get(ChunkModel, entity_id)
        if chunk is not None and chunk.symbol_id is not None:
            symbol = session.get(SymbolModel, chunk.symbol_id)
    elif entity_type == "fact":
        fact = session.get(SyntaxFactModel, entity_id)
        if fact is not None and fact.source_symbol_id is not None:
            symbol = session.get(SymbolModel, fact.source_symbol_id)
    elif entity_type == "git_diff":
        file = session.scalar(select(FileModel).where(FileModel.relative_path == relative_path))
        if file is not None:
            symbol = session.scalar(
                select(SymbolModel)
                .where(
                    SymbolModel.file_id == file.id,
                    SymbolModel.start_line <= end_line,
                    SymbolModel.end_line >= start_line,
                )
                .order_by(
                    (SymbolModel.end_line - SymbolModel.start_line),
                    SymbolModel.start_line,
                    SymbolModel.id,
                )
                .limit(1)
            )
    if symbol is None:
        return None
    file = session.get(FileModel, symbol.file_id)
    if file is None:
        return None
    return file.relative_path, symbol.qualified_name


def _merge_related(
    destination: dict[str, set[str]],
    source: Mapping[str, set[str]],
) -> None:
    for role, identities in source.items():
        destination.setdefault(role, set()).update(identities)


def _missing_related(
    expected: Sequence[RoleExpectation],
    observed: Mapping[str, set[str] | frozenset[str]],
) -> dict[str, set[str]]:
    return {
        expectation.role: {
            symbol.identity
            for symbol in expectation.symbols
            if symbol.identity not in observed.get(expectation.role, ())
        }
        for expectation in expected
        if any(
            symbol.identity not in observed.get(expectation.role, ())
            for symbol in expectation.symbols
        )
    }


def _build_report(
    repository_root: Path,
    index_ms: float,
    workflows: Sequence[tuple[GoldTask, _WorkflowResult]],
    latencies_ms: Sequence[float],
    *,
    repetitions: int,
    deterministic: bool,
) -> dict[str, Any]:
    primary_top_1_hits = 0
    primary_top_3_hits = 0
    required_hits = 0
    required_total = 0
    optional_hits = 0
    optional_total = 0
    returned_tokens = 0
    baseline_tokens = 0
    discovery_calls: list[int] = []
    duplicate_hashes = 0
    manual_fallbacks: list[dict[str, str]] = []
    case_reports: list[dict[str, Any]] = []

    for case, result in workflows:
        expected_primary = {item.identity for item in case.expected_primary_symbols}
        primary_top_1_hits += int(
            bool(result.primary_identities and result.primary_identities[0] in expected_primary)
        )
        primary_top_3_hits += int(bool(set(result.primary_identities[:3]) & expected_primary))
        case_required_hits, case_required_total = _related_recall_counts(
            case.required_related_symbols,
            result.related_identities,
        )
        case_optional_hits, case_optional_total = _related_recall_counts(
            case.optional_related_symbols,
            result.related_identities,
        )
        required_hits += case_required_hits
        required_total += case_required_total
        optional_hits += case_optional_hits
        optional_total += case_optional_total
        returned_tokens += result.returned_tokens
        baseline = _baseline_tokens(repository_root, case)
        baseline_tokens += baseline
        discovery_calls.append(result.discovery_calls)
        duplicate_hashes += len(result.content_hashes) - len(set(result.content_hashes))
        manual_fallbacks.extend(
            {"case_id": case.case_id, "reason": reason} for reason in result.fallback_reasons
        )
        case_reports.append(
            {
                "case_id": case.case_id,
                "category": case.category,
                "discovery_calls": result.discovery_calls,
                "next_action": result.next_action,
                "next_action_reason": result.next_action_reason,
                "confidence": result.confidence,
                "diagnostic_codes": list(result.diagnostic_codes),
                "diagnostic_messages": list(result.diagnostic_messages),
                "primary_top_3": list(result.primary_identities[:3]),
                "primary_scores": list(result.primary_scores),
                "required_related_hits": case_required_hits,
                "required_related_total": case_required_total,
                "optional_related_hits": case_optional_hits,
                "optional_related_total": case_optional_total,
                "returned_tokens": result.returned_tokens,
                "baseline_tokens": baseline,
                "fallback_reasons": list(result.fallback_reasons),
            }
        )

    case_count = len(workflows)
    primary_top_1_recall = primary_top_1_hits / case_count
    primary_top_3_recall = primary_top_3_hits / case_count
    required_recall = required_hits / required_total if required_total else 1.0
    optional_recall = optional_hits / optional_total if optional_total else 1.0
    token_reduction = (
        max(baseline_tokens - returned_tokens, 0) / baseline_tokens if baseline_tokens else 0.0
    )
    metrics = {
        "primary_top_1_recall": round(primary_top_1_recall, 4),
        "primary_top_3_recall": round(primary_top_3_recall, 4),
        "required_related_recall": round(required_recall, 4),
        "optional_related_recall": round(optional_recall, 4),
        "missing_role_count": sum(
            1
            for case, result in workflows
            for expected in case.required_related_symbols
            if any(
                symbol.identity not in result.related_identities.get(expected.role, ())
                for symbol in expected.symbols
            )
        ),
        "duplicate_content_hash_count": duplicate_hashes,
        "returned_estimated_tokens": returned_tokens,
        "baseline_estimated_tokens": baseline_tokens,
        "token_reduction_ratio": round(token_reduction, 4),
        "median_discovery_calls": round(float(median(discovery_calls)), 3),
        "p95_discovery_calls": float(_percentile(discovery_calls, 0.95)),
        "manual_fallback_count": len(manual_fallbacks),
        "median_retrieval_latency_ms": round(float(median(latencies_ms)), 3),
        "p95_retrieval_latency_ms": round(float(_percentile(latencies_ms, 0.95)), 3),
        "deterministic_retrieval_json": deterministic,
    }
    checks = {
        "primary_top_1_recall": (
            primary_top_1_recall >= _RELEASE_THRESHOLDS["primary_top_1_recall"]
        ),
        "primary_top_3_recall": (
            primary_top_3_recall == _RELEASE_THRESHOLDS["primary_top_3_recall"]
        ),
        "required_related_recall": (
            required_recall == _RELEASE_THRESHOLDS["required_related_recall"]
        ),
        "optional_related_recall": (
            optional_recall >= _RELEASE_THRESHOLDS["optional_related_recall"]
        ),
        "median_discovery_calls": (
            median(discovery_calls) == _RELEASE_THRESHOLDS["median_discovery_calls"]
        ),
        "p95_discovery_calls": (
            _percentile(discovery_calls, 0.95) <= _RELEASE_THRESHOLDS["p95_discovery_calls"]
        ),
        "manual_fallback_count": (
            len(manual_fallbacks) == _RELEASE_THRESHOLDS["manual_fallback_count"]
        ),
        "duplicate_content_hash_count": (
            duplicate_hashes == _RELEASE_THRESHOLDS["duplicate_content_hash_count"]
        ),
        "token_reduction_ratio": (token_reduction >= _RELEASE_THRESHOLDS["token_reduction_ratio"]),
        "p95_retrieval_latency_ms": (
            _percentile(latencies_ms, 0.95) < _RELEASE_THRESHOLDS["p95_retrieval_latency_ms"]
        ),
        "deterministic_retrieval_json": deterministic and repetitions >= 3,
    }
    return {
        "schema_version": "1.0",
        "suite": {
            "case_count": case_count,
            "repetitions": repetitions,
            "index_ms": round(index_ms, 3),
        },
        "metrics": metrics,
        "manual_fallbacks": manual_fallbacks,
        "cases": case_reports,
        "release_gate": {
            "passed": all(checks.values()),
            "checks": checks,
            "thresholds": _RELEASE_THRESHOLDS,
        },
    }


def _related_recall_counts(
    expected: Sequence[RoleExpectation],
    observed: Mapping[str, frozenset[str]],
) -> tuple[int, int]:
    total = sum(len(item.symbols) for item in expected)
    hits = sum(
        symbol.identity in observed.get(item.role, ())
        for item in expected
        for symbol in item.symbols
    )
    return hits, total


def _baseline_tokens(repository_root: Path, case: GoldTask) -> int:
    relevant_paths = {
        symbol.relative_path
        for symbol in (
            *case.expected_primary_symbols,
            *(symbol for item in case.required_related_symbols for symbol in item.symbols),
            *(symbol for item in case.optional_related_symbols for symbol in item.symbols),
        )
    }
    estimator = HeuristicTokenEstimator()
    return sum(
        estimator.estimate(
            (repository_root / relative_path).read_text(encoding="utf-8")
        ).estimated_tokens
        for relative_path in sorted(relevant_paths)
    )


def _percentile(values: Sequence[int | float], fraction: float) -> int | float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, ceil(len(ordered) * fraction) - 1)
    return ordered[index]


def _symbol_identity(relative_path: str, qualified_name: str | None) -> str:
    return f"{relative_path}::{qualified_name or ''}"


def _stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _write_fixture(root: Path) -> None:
    root.mkdir()
    files = {
        "exact.py": (
            "def exact_target(value: int) -> int:\n"
            "    return value + 1\n\n"
            "class ExactService:\n"
            "    def run(self) -> int:\n"
            "        return exact_target(1)\n"
        ),
        "alpha/duplicate.py": "def duplicate() -> str:\n    return 'alpha'\n",
        "beta/duplicate.py": "def duplicate() -> str:\n    return 'beta'\n",
        "service.py": (
            "class PaymentService:\n"
            "    def validate(self, value: int) -> bool:\n"
            "        return value > 0\n\n"
            "    def run(self, value: int) -> int:\n"
            "        if not self.validate(value):\n"
            "            raise ValueError('invalid')\n"
            "        return value * 2\n"
        ),
        "controller.py": (
            "from service import PaymentService\n\n"
            "def checkout(value: int) -> int:\n"
            "    service = PaymentService()\n"
            "    return service.run(value)\n"
        ),
        "test_service.py": (
            "from service import PaymentService\n\n"
            "def test_run() -> None:\n"
            "    assert PaymentService().run(2) == 4\n"
        ),
        "provider.py": "def provide() -> str:\n    return 'provided'\n",
        "consumer.py": (
            "from provider import provide as supply\n\ndef consume() -> str:\n    return supply()\n"
        ),
        "contracts.ts": "export interface Runner { run(value: number): string; }\n",
        "runner.ts": (
            "import { Runner } from './contracts';\n"
            "export class LocalRunner implements Runner {\n"
            "  run(value: number): string { return String(value); }\n"
            "}\n"
        ),
        "base_worker.py": (
            "class BaseWorker:\n    def run(self, value: int) -> int:\n        return value\n"
        ),
        "worker.py": (
            "from base_worker import BaseWorker\n\n"
            "class Worker(BaseWorker):\n"
            "    def run(self, value: int) -> int:\n"
            "        return value + 1\n"
        ),
        "api.ts": "export function fetchUser(): string { return 'user'; }\n",
        "index.ts": "export { fetchUser } from './api';\n",
        "export_consumer.ts": (
            "import { fetchUser } from './index';\n"
            "export function useUser(): string { return fetchUser(); }\n"
        ),
        "schemas.py": (
            "class UserCreate:\n"
            "    def __init__(self, name: str) -> None:\n"
            "        self.name = name\n"
        ),
        "routes.py": (
            "from schemas import UserCreate\n\n"
            "@app.post('/users')\n"
            "def create_user(payload: UserCreate) -> str:\n"
            "    return payload.name\n"
        ),
        "configuration.py": (
            "import os\n\ndef load_config() -> str:\n    return os.getenv('API_URL', '')\n"
        ),
        "changed.py": "def changed_target() -> str:\n    return 'before'\n",
        "stale.py": "def stale_target() -> str:\n    return 'indexed'\n",
    }
    for relative_path, content in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content + _file_padding(path), encoding="utf-8")


def _initialize_git(root: Path) -> None:
    commands: Iterable[tuple[str, ...]] = (
        ("git", "init", "--quiet"),
        ("git", "config", "user.email", "quality@monas-lens.local"),
        ("git", "config", "user.name", "Monas Lens Quality"),
        ("git", "add", "."),
        ("git", "commit", "--quiet", "-m", "gold fixture"),
    )
    for command in commands:
        subprocess.run(
            command,
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )


def _write_worktree_changes(root: Path) -> None:
    changes = {
        "changed.py": "def changed_target() -> str:\n    return 'after'\n",
        "stale.py": "def stale_target() -> str:\n    return 'worktree'\n",
    }
    for relative_path, content in changes.items():
        path = root / relative_path
        path.write_text(content + _file_padding(path), encoding="utf-8")


def _file_padding(path: Path) -> str:
    marker = "//" if path.suffix in {".ts", ".tsx", ".js"} else "#"
    label = path.stem.replace("-", "_")
    return (
        "\n"
        + "\n".join(
            f"{marker} {label} unrelated implementation note {index:02d} for full-file baseline"
            for index in range(24)
        )
        + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repetitions",
        type=int,
        default=3,
        help="Determinism repetitions per gold task (default: 3).",
    )
    parser.add_argument(
        "--no-enforce",
        action="store_true",
        help="Emit the report without returning a failing release-gate exit code.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Emit metrics and compact per-case decisions instead of the full report.",
    )
    arguments = parser.parse_args()
    report = run_quality_gate(
        repetitions=arguments.repetitions,
        enforce=False,
    )
    output = report
    if arguments.summary_only:
        output = {
            "metrics": report["metrics"],
            "release_gate": report["release_gate"],
            "cases": [
                {
                    "case_id": case["case_id"],
                    "fallback_reasons": case["fallback_reasons"],
                    "next_action": case["next_action"],
                    "next_action_reason": case["next_action_reason"],
                    "confidence_status": case["confidence"]["status"],
                    "confidence_reasons": case["confidence"]["reason_codes"],
                    "diagnostic_codes": case["diagnostic_codes"],
                    "primary_top_3": case["primary_top_3"],
                }
                for case in report["cases"]
            ],
        }
    print(json.dumps(output, indent=2, sort_keys=True))
    if not arguments.no_enforce and not report["release_gate"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
