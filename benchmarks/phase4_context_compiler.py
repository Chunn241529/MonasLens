"""Repeatable Phase 4 Context Compiler benchmark with per-stage timing."""

from __future__ import annotations

import argparse
import json
import platform
import tempfile
from math import ceil
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

from monas_lens.config import Settings, ensure_runtime_directories
from monas_lens.db.migration import upgrade_database
from monas_lens.db.session import Database
from monas_lens.indexing.service import IndexService
from monas_lens.repositories import RepositoryService
from monas_lens.retrieval.bundle import ContextBundleBuilder
from monas_lens.retrieval.confidence import ConfidenceGate
from monas_lens.retrieval.contracts import parse_task_context_request
from monas_lens.retrieval.resolver import resolve_task
from monas_lens.retrieval.retriever import ParallelRetriever

_TASKS = (
    "Fix the missing import used by BenchService.run",
    "Fix the wrong configuration key in BenchConfig",
    "Fix the broken API schema BenchResponse",
    "Fix expired session logic in SessionService.isExpired",
    "Rename LegacyFormatter across files",
    "Add a missing regression test for calculateTotal",
    "Explain the unrelated change near untouchedHelper",
)


def run_benchmark(iterations: int) -> dict[str, Any]:
    if iterations < 1:
        raise ValueError("iterations must be at least 1")

    with tempfile.TemporaryDirectory(prefix="monas-lens-phase4-") as temporary:
        workspace = Path(temporary)
        repository_root = workspace / "repository"
        _write_fixture(repository_root)
        settings = Settings(data_dir=workspace / "state")
        ensure_runtime_directories(settings)
        database = Database(settings)
        try:
            upgrade_database(database.engine)
            repository = RepositoryService(database, settings).add(repository_root)
            index_summary = IndexService(database, settings).build(repository.id)
            retriever = ParallelRetriever(database, settings)
            gate = ConfidenceGate(settings, retriever)
            builder = ContextBundleBuilder(database, settings)
            samples: dict[str, list[float]] = {
                "task_resolver": [],
                "retrieval": [],
                "ranking_confidence": [],
                "context_assembly": [],
                "total": [],
            }
            candidate_counts: list[int] = []
            token_estimates: list[int] = []
            reduction_ratios: list[float] = []

            for iteration in range(iterations):
                request = parse_task_context_request(
                    {
                        "task": _TASKS[iteration % len(_TASKS)],
                        "repository": repository.id,
                        "max_tokens": 3_000,
                        "include_git_diff": False,
                    },
                    max_tokens_limit=settings.context_max_total_tokens,
                )
                total_started = perf_counter()
                stage_started = perf_counter()
                resolution = resolve_task(
                    request.task,
                    focus_targets=request.focus_targets,
                )
                samples["task_resolver"].append(_elapsed_ms(stage_started))
                stage_started = perf_counter()
                batch = retriever.retrieve(
                    resolution,
                    request.repository,
                    include_git_diff=False,
                )
                samples["retrieval"].append(_elapsed_ms(stage_started))
                stage_started = perf_counter()
                outcome = gate.evaluate(resolution, batch)
                samples["ranking_confidence"].append(_elapsed_ms(stage_started))
                stage_started = perf_counter()
                bundle = builder.build(
                    batch.repository_id,
                    resolution,
                    outcome.ranked_candidates,
                    outcome.confidence,
                    requested_tokens=request.max_tokens or 3_000,
                    diagnostics=outcome.diagnostics,
                    git_diff_hunks=batch.git_diff_hunks,
                    retrieval_truncated=outcome.truncated,
                )
                samples["context_assembly"].append(_elapsed_ms(stage_started))
                samples["total"].append((perf_counter() - total_started) * 1_000)
                candidate_counts.append(len(outcome.ranked_candidates))
                token_estimates.append(bundle.budget.used_tokens)
                reduction_ratios.append(bundle.budget.reduction_ratio)

            return {
                "environment": {
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "iterations": iterations,
                    "fixture_files": index_summary.scanned_files,
                },
                "index_ms": round(index_summary.duration_ms, 3),
                "stages": {name: _latencies(values) for name, values in samples.items()},
                "results": {
                    "median_candidates": median(candidate_counts),
                    "median_context_tokens": median(token_estimates),
                    "median_reduction_ratio": round(median(reduction_ratios), 4),
                },
            }
        finally:
            database.dispose()


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1_000


def _latencies(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    p95_index = min(len(ordered) - 1, ceil(len(ordered) * 0.95) - 1)
    return {
        "median_ms": round(median(ordered), 3),
        "p95_ms": round(ordered[p95_index], 3),
    }


def _write_fixture(root: Path) -> None:
    root.mkdir()
    (root / "service.py").write_text(
        "class BenchService:\n"
        "    def helper(self) -> str:\n"
        "        return 'ok'\n\n"
        "    def run(self) -> str:\n"
        "        return self.helper()\n",
        encoding="utf-8",
    )
    (root / "test_service.py").write_text(
        "from service import BenchService\n\n"
        "def test_run() -> None:\n"
        "    assert BenchService().run()\n",
        encoding="utf-8",
    )
    (root / "configuration.ts").write_text(
        "export class BenchConfig { apiKey: string = 'local'; }\n",
        encoding="utf-8",
    )
    (root / "schema.ts").write_text(
        "export interface BenchResponse { id: string; }\n",
        encoding="utf-8",
    )
    (root / "session.ts").write_text(
        "export class SessionService {\n"
        "  isExpired(value: number): boolean { return value < Date.now(); }\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "billing.js").write_text(
        "export function calculateTotal(values) {\n"
        "  return values.reduce((total, value) => total + value, 0);\n"
        "}\n"
        "export function untouchedHelper() { return true; }\n",
        encoding="utf-8",
    )
    (root / "formatter.dart").write_text(
        "class LegacyFormatter {\n  String format(String value) => value.trim();\n}\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--iterations",
        type=int,
        default=20,
        help="Measured task iterations (default: 20).",
    )
    arguments = parser.parse_args()
    print(json.dumps(run_benchmark(arguments.iterations), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
