"""Repeatable Phase 3 lexical-search and relationship-graph benchmark."""

from __future__ import annotations

import argparse
import json
import platform
import tempfile
from collections.abc import Callable
from math import ceil
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

from monas_lens.config import Settings, ensure_runtime_directories
from monas_lens.db.migration import upgrade_database
from monas_lens.db.session import Database
from monas_lens.graph.contracts import GraphDirection
from monas_lens.graph.service import GraphService
from monas_lens.indexing.service import IndexService
from monas_lens.repositories import RepositoryService
from monas_lens.search.service import SearchService


def _write_fixture(root: Path, *, updated: bool = False) -> None:
    root.mkdir(exist_ok=True)
    token = "updated benchmark token" if updated else "initial benchmark token"
    (root / "base.py").write_text(
        "class BenchBase:\n    pass\n\nAPI_URL = 'https://example.invalid'\n",
        encoding="utf-8",
    )
    (root / "service.py").write_text(
        "import os\n"
        "from base import BenchBase\n\n"
        "class BenchService(BenchBase):\n"
        "    def helper(self) -> str:\n"
        f"        return '{token}'\n\n"
        "    def run(self) -> str:\n"
        "        return self.helper() + os.getenv('API_URL', '')\n",
        encoding="utf-8",
    )
    (root / "test_service.py").write_text(
        "from service import BenchService\n\n"
        "def test_run() -> None:\n"
        "    assert BenchService().run()\n",
        encoding="utf-8",
    )
    (root / "service.js").write_text(
        "export function javascriptBench() { return 'benchmark'; }\n",
        encoding="utf-8",
    )
    (root / "service.ts").write_text(
        "export function typescriptBench(): string { return 'benchmark'; }\n",
        encoding="utf-8",
    )
    (root / "component.tsx").write_text(
        "export function tsxBench() { return <main>benchmark</main>; }\n",
        encoding="utf-8",
    )
    (root / "service.dart").write_text(
        "String dartBench() => 'benchmark';\n",
        encoding="utf-8",
    )


def _latencies(
    operation: Callable[[], object],
    iterations: int,
) -> dict[str, float]:
    samples: list[float] = []
    for _iteration in range(iterations):
        started = perf_counter()
        operation()
        samples.append((perf_counter() - started) * 1000)
    ordered = sorted(samples)
    p95_index = min(len(ordered) - 1, ceil(len(ordered) * 0.95) - 1)
    return {
        "median_ms": round(median(ordered), 3),
        "p95_ms": round(ordered[p95_index], 3),
    }


def run_benchmark(iterations: int) -> dict[str, Any]:
    if iterations < 1:
        raise ValueError("iterations must be at least 1")

    with tempfile.TemporaryDirectory(prefix="monas-lens-phase3-") as temporary:
        workspace = Path(temporary)
        repository_root = workspace / "repository"
        _write_fixture(repository_root)
        settings = Settings(data_dir=workspace / "state")
        ensure_runtime_directories(settings)
        database = Database(settings)
        try:
            upgrade_database(database.engine)
            repository = RepositoryService(database, settings).add(repository_root)
            indexing = IndexService(database, settings)
            search = SearchService(database, settings)
            graph = GraphService(database, settings)

            full = indexing.build(repository.id)
            _write_fixture(repository_root, updated=True)
            incremental_started = perf_counter()
            incremental = indexing.build(repository.id)
            incremental_ms = (perf_counter() - incremental_started) * 1000

            search.search("BenchService.run", repository.id)
            search.search("updated benchmark", repository.id)
            graph.neighbors(
                "BenchService.run",
                repository.id,
                direction=GraphDirection.OUTGOING,
            )

            return {
                "environment": {
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "iterations": iterations,
                    "fixture_files": full.scanned_files,
                },
                "index": {
                    "full_ms": round(full.duration_ms, 3),
                    "full_graph_ms": round(full.graph_duration_ms, 3),
                    "relationships": full.relationships,
                    "incremental_ms": round(incremental_ms, 3),
                    "incremental_graph_ms": round(
                        incremental.graph_duration_ms,
                        3,
                    ),
                    "incremental_refreshed_facts": (incremental.graph_refreshed_facts),
                },
                "exact_lookup": _latencies(
                    lambda: search.search("BenchService.run", repository.id),
                    iterations,
                ),
                "fts_ranking": _latencies(
                    lambda: search.search("updated benchmark", repository.id),
                    iterations,
                ),
                "one_hop_graph": _latencies(
                    lambda: graph.neighbors(
                        "BenchService.run",
                        repository.id,
                        direction=GraphDirection.OUTGOING,
                    ),
                    iterations,
                ),
            }
        finally:
            database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--iterations",
        type=int,
        default=50,
        help="Measured query iterations per operation (default: 50).",
    )
    arguments = parser.parse_args()
    print(
        json.dumps(
            run_benchmark(arguments.iterations),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
