"""Phase 4 Context Compiler orchestration service."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from time import perf_counter
from typing import Any

from monas_lens.config import Settings
from monas_lens.db.session import Database
from monas_lens.retrieval.bundle import ContextBundleBuilder
from monas_lens.retrieval.confidence import ConfidenceGate
from monas_lens.retrieval.contracts import (
    ContextBundle,
    TaskContextRequest,
    parse_task_context_request,
)
from monas_lens.retrieval.resolver import resolve_task
from monas_lens.retrieval.retriever import ParallelRetriever

logger = logging.getLogger(__name__)


class ContextCompiler:
    """Compile one bounded repository context bundle for a coding task."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        retriever: ParallelRetriever | None = None,
        bundle_builder: ContextBundleBuilder | None = None,
    ) -> None:
        self._settings = settings
        self._retriever = retriever or ParallelRetriever(database, settings)
        self._bundle_builder = bundle_builder or ContextBundleBuilder(database, settings)

    def resolve(
        self,
        request: TaskContextRequest | Mapping[str, Any],
    ) -> ContextBundle:
        """Resolve, retrieve, rank, widen, and assemble one deterministic bundle."""

        operation_started = perf_counter()
        parsed = parse_task_context_request(
            request,
            max_tokens_limit=self._settings.context_max_total_tokens,
        )

        stage_started = perf_counter()
        resolution = resolve_task(parsed.task, focus_targets=parsed.focus_targets)
        _log_stage(
            "resolve",
            stage_started,
            lexical_queries=len(resolution.lexical_queries),
            focus_targets=len(resolution.explicit_focus_targets),
        )

        stage_started = perf_counter()
        batch = self._retriever.retrieve(
            resolution,
            parsed.repository,
            include_git_diff=parsed.include_git_diff,
        )
        _log_stage(
            "retrieve",
            stage_started,
            candidates=len(batch.candidates),
            primary_seeds=len(batch.primary_seeds),
            diagnostics=len(batch.diagnostics),
            git_hunks=len(batch.git_diff_hunks),
        )

        stage_started = perf_counter()
        outcome = ConfidenceGate(self._settings, self._retriever).evaluate(resolution, batch)
        _log_stage(
            "rank_confidence",
            stage_started,
            ranked_candidates=len(outcome.ranked_candidates),
            expansion_count=outcome.confidence.expansion_count,
            accepted=outcome.confidence.status.value == "accepted",
        )

        stage_started = perf_counter()
        bundle = self._bundle_builder.build(
            batch.repository_id,
            resolution,
            outcome.ranked_candidates,
            outcome.confidence,
            requested_tokens=parsed.max_tokens or self._settings.context_max_total_tokens,
            diagnostics=outcome.diagnostics,
            git_diff_hunks=batch.git_diff_hunks,
            retrieval_truncated=outcome.truncated,
        )
        _log_stage(
            "bundle",
            stage_started,
            snippets=len(bundle.snippets),
            used_tokens=bundle.budget.used_tokens,
            omitted_items=bundle.budget.omitted_items,
        )
        _log_stage(
            "complete",
            operation_started,
            snippets=len(bundle.snippets),
            diagnostics=len(bundle.diagnostics),
        )
        return bundle


def _log_stage(stage: str, started: float, **counts: int | bool) -> None:
    fields = " ".join(f"{name}={value}" for name, value in sorted(counts.items()))
    duration_ms = (perf_counter() - started) * 1_000
    logger.info(
        "context_stage stage=%s duration_ms=%.3f%s",
        stage,
        duration_ms,
        f" {fields}" if fields else "",
    )
