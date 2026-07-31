from pathlib import Path
from runpy import run_path
from typing import Any, cast

_BENCHMARK = run_path(str(Path(__file__).parents[1] / "benchmarks" / "phase5_retrieval_quality.py"))
GOLD_TASKS = cast(tuple[Any, ...], _BENCHMARK["GOLD_TASKS"])
run_quality_gate = cast(Any, _BENCHMARK["run_quality_gate"])


def test_gold_suite_covers_required_retrieval_categories() -> None:
    categories = {case.category for case in GOLD_TASKS}

    assert len({case.case_id for case in GOLD_TASKS}) == len(GOLD_TASKS)
    assert {
        "exact_lookup",
        "same_name_ambiguity",
        "method_closure",
        "import_alias",
        "interface_implementation",
        "inheritance_override",
        "exports_reexports",
        "framework_registration",
        "configuration",
        "regression_tests",
        "git_diff",
        "stale_recovery",
    } <= categories
    assert all(case.expected_primary_symbols for case in GOLD_TASKS)
    assert all(case.max_discovery_calls in {1, 2} for case in GOLD_TASKS)
    assert all(case.expansion_permitted or case.max_discovery_calls == 1 for case in GOLD_TASKS)


def test_quality_gate_emits_deterministic_metric_contract() -> None:
    report = run_quality_gate(repetitions=1, enforce=False)

    assert report["schema_version"] == "1.0"
    assert report["suite"]["case_count"] == len(GOLD_TASKS)
    assert report["suite"]["repetitions"] == 1
    assert set(report["release_gate"]["checks"]) == {
        "primary_top_1_recall",
        "primary_top_3_recall",
        "required_related_recall",
        "optional_related_recall",
        "median_discovery_calls",
        "p95_discovery_calls",
        "manual_fallback_count",
        "duplicate_content_hash_count",
        "token_reduction_ratio",
        "p95_retrieval_latency_ms",
        "deterministic_retrieval_json",
    }
    assert report["metrics"]["p95_discovery_calls"] <= 2
