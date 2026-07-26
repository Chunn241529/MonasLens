"""Deterministic materialization and assembly of focused context bundles."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from monas_lens.config import Settings
from monas_lens.db.session import Database
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.indexing.identity import stable_id
from monas_lens.repositories import RepositoryService
from monas_lens.retrieval.contracts import (
    MIN_CONTEXT_TOKENS,
    CandidateRole,
    ConfidenceResult,
    ContextBudget,
    ContextBundle,
    ContextSnippet,
    ContextSourceReference,
    DiagnosticSeverity,
    EntityType,
    RankedCandidate,
    RetrievalDiagnostic,
    RetrievalDiagnosticCode,
    RoleTokenUsage,
    TaskResolution,
)
from monas_lens.retrieval.retriever import (
    GitDiffHunk,
    IndexedChunk,
    IndexedChunkLookupAdapter,
    IndexedChunkLookupProtocol,
)
from monas_lens.retrieval.token_estimator import (
    HeuristicTokenEstimator,
    TokenEstimatorProtocol,
)
from monas_lens.retrieval.validation import (
    normalize_repository_relative_path,
    suggest_validation_commands,
)

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
_ALLOCATION_STAGES = (
    (CandidateRole.PRIMARY,),
    (
        CandidateRole.INTERFACE,
        CandidateRole.SCHEMA,
        CandidateRole.CONFIGURATION,
        CandidateRole.DEPENDENCY,
    ),
    (CandidateRole.CALLER,),
    (CandidateRole.TEST,),
    (CandidateRole.GIT_DIFF,),
)


@dataclass(frozen=True, slots=True)
class _PreparedSnippet:
    role: CandidateRole
    relative_path: str
    language: str
    kind: str
    start_line: int
    end_line: int
    content: str
    content_hash: str
    provenance: tuple[ContextSourceReference, ...]
    rank_score: float
    focus_line: int
    cropped: bool = False


@dataclass(frozen=True, slots=True)
class _BudgetSelection:
    snippets: tuple[ContextSnippet, ...]
    budget: ContextBudget


class ContextBundleBuilder:
    """Build a versioned context bundle from ranked, repository-scoped evidence."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        chunk_lookup: IndexedChunkLookupProtocol | None = None,
        estimator: TokenEstimatorProtocol | None = None,
    ) -> None:
        self._settings = settings
        self._repositories = RepositoryService(database, settings)
        self._chunk_lookup = chunk_lookup or IndexedChunkLookupAdapter(database)
        self._estimator = estimator or HeuristicTokenEstimator()

    def build(
        self,
        repository_id: str,
        resolution: TaskResolution,
        ranked_candidates: Sequence[RankedCandidate],
        confidence: ConfidenceResult,
        *,
        requested_tokens: int,
        diagnostics: Sequence[RetrievalDiagnostic] = (),
        git_diff_hunks: Sequence[GitDiffHunk] = (),
        retrieval_truncated: bool = False,
    ) -> ContextBundle:
        """Materialize, deduplicate, budget, and assemble one deterministic bundle."""

        self._validate_inputs(repository_id, ranked_candidates, requested_tokens)
        repository = self._repositories.get(repository_id)
        ordered_ranked = tuple(sorted(ranked_candidates, key=_ranked_sort_key))
        chunks = self._chunk_lookup.lookup(
            repository_id,
            tuple(item.candidate for item in ordered_ranked),
        )
        chunks_by_identity = {chunk.candidate_identity: chunk for chunk in chunks}
        materialized = _materialize_ranked(ordered_ranked, chunks_by_identity)
        deduplicated = _deduplicate_prepared(materialized)
        git_prepared, invalid_git_paths = _materialize_relevant_git_hunks(
            git_diff_hunks,
            ordered_ranked,
            resolution,
        )
        prepared = _deduplicate_prepared((*deduplicated, *git_prepared))
        selection = _select_under_budget(
            prepared,
            requested_tokens=requested_tokens,
            settings=self._settings,
            estimator=self._estimator,
        )
        primary_targets = tuple(
            item
            for item in ordered_ranked
            if CandidateRole.PRIMARY in item.candidate.role_hints
            and item.candidate.identity in chunks_by_identity
        )[: self._settings.context_max_primary_targets]
        selected_diagnostics = _bundle_diagnostics(
            diagnostics,
            confidence,
            ordered_ranked,
            materialized,
            selection.budget,
            invalid_git_paths=invalid_git_paths,
            limit=self._settings.context_max_retrieval_diagnostics,
        )
        validation_commands = suggest_validation_commands(
            repository.canonical_path,
            selection.snippets,
        )
        truncated = (
            retrieval_truncated
            or selection.budget.omitted_items > 0
            or selection.budget.cropped
            or invalid_git_paths > 0
        )
        return ContextBundle(
            repository_id=repository_id,
            resolution=resolution,
            primary_targets=primary_targets,
            confidence=confidence,
            internal_widening_occurred=confidence.expansion_count > 0,
            snippets=selection.snippets,
            budget=selection.budget,
            diagnostics=selected_diagnostics,
            validation_commands=validation_commands,
            truncated=truncated,
        )

    def _validate_inputs(
        self,
        repository_id: str,
        ranked_candidates: Sequence[RankedCandidate],
        requested_tokens: int,
    ) -> None:
        if any(item.candidate.repository_id != repository_id for item in ranked_candidates):
            raise MonasLensError(
                ErrorCode.CONTEXT_RETRIEVAL_FAILED,
                "Context bundle candidates must belong to the selected repository.",
            )
        if not MIN_CONTEXT_TOKENS <= requested_tokens <= self._settings.context_max_total_tokens:
            raise MonasLensError(
                ErrorCode.CONTEXT_BUDGET_INVALID,
                "The context bundle budget is outside the configured bounds.",
                details={"max_tokens": self._settings.context_max_total_tokens},
            )


def _materialize_ranked(
    ranked_candidates: Sequence[RankedCandidate],
    chunks_by_identity: dict[tuple[str, EntityType, str], IndexedChunk],
) -> tuple[_PreparedSnippet, ...]:
    selected: list[_PreparedSnippet] = []
    for ranked in ranked_candidates:
        chunk = chunks_by_identity.get(ranked.candidate.identity)
        if chunk is None or not chunk.source_text:
            continue
        candidate = ranked.candidate
        selected.append(
            _PreparedSnippet(
                role=min(candidate.role_hints, key=lambda role: _ROLE_PRIORITY[role]),
                relative_path=chunk.relative_path,
                language=chunk.language,
                kind=chunk.kind,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                content=chunk.source_text,
                content_hash=_content_hash(chunk.source_text),
                provenance=(
                    ContextSourceReference(
                        entity_type=candidate.entity_type,
                        entity_id=candidate.entity_id,
                        relative_path=candidate.relative_path,
                        start_line=candidate.start_line,
                        end_line=candidate.end_line,
                    ),
                ),
                rank_score=ranked.score,
                focus_line=min(max(candidate.start_line, chunk.start_line), chunk.end_line),
            )
        )
    return tuple(selected)


def _materialize_relevant_git_hunks(
    hunks: Sequence[GitDiffHunk],
    ranked_candidates: Sequence[RankedCandidate],
    resolution: TaskResolution,
) -> tuple[tuple[_PreparedSnippet, ...], int]:
    ranked_paths: dict[str, float] = {}
    for ranked in ranked_candidates:
        normalized = normalize_repository_relative_path(ranked.candidate.relative_path)
        if normalized is not None:
            ranked_paths[normalized.casefold()] = max(
                ranked_paths.get(normalized.casefold(), 0.0),
                ranked.score,
            )
    relevant_paths = set(ranked_paths)
    for value in (*resolution.path_candidates, *resolution.explicit_focus_targets):
        normalized = normalize_repository_relative_path(value)
        if normalized is not None:
            relevant_paths.add(normalized.casefold())

    prepared: list[_PreparedSnippet] = []
    invalid_paths = 0
    for hunk in hunks:
        relative_path = normalize_repository_relative_path(hunk.relative_path)
        if relative_path is None:
            invalid_paths += 1
            continue
        path_key = relative_path.casefold()
        if path_key not in relevant_paths or not hunk.content:
            continue
        start_line = max(hunk.new_start_line or hunk.old_start_line, 1)
        end_line = start_line + max(_git_hunk_line_count(hunk.content), 1) - 1
        content_hash = _content_hash(hunk.content)
        prepared.append(
            _PreparedSnippet(
                role=CandidateRole.GIT_DIFF,
                relative_path=relative_path,
                language="diff",
                kind="git_hunk",
                start_line=start_line,
                end_line=end_line,
                content=hunk.content,
                content_hash=content_hash,
                provenance=(
                    ContextSourceReference(
                        entity_type=EntityType.GIT_DIFF,
                        entity_id=stable_id(
                            "git-diff",
                            relative_path,
                            hunk.old_start_line,
                            hunk.new_start_line,
                            content_hash,
                        ),
                        relative_path=relative_path,
                        start_line=start_line,
                        end_line=end_line,
                    ),
                ),
                rank_score=ranked_paths.get(path_key, 0.0),
                focus_line=start_line,
            )
        )
    return tuple(prepared), invalid_paths


def _deduplicate_prepared(
    snippets: Sequence[_PreparedSnippet],
) -> tuple[_PreparedSnippet, ...]:
    grouped: dict[str, list[_PreparedSnippet]] = {}
    for snippet in snippets:
        grouped.setdefault(snippet.content_hash, []).append(snippet)

    selected: list[_PreparedSnippet] = []
    for content_hash in sorted(grouped):
        occurrences = sorted(grouped[content_hash], key=_prepared_sort_key)
        canonical = occurrences[0]
        provenance_by_key = {
            _source_reference_sort_key(reference): reference
            for occurrence in occurrences
            for reference in occurrence.provenance
        }
        selected.append(
            _PreparedSnippet(
                role=canonical.role,
                relative_path=canonical.relative_path,
                language=canonical.language,
                kind=canonical.kind,
                start_line=canonical.start_line,
                end_line=canonical.end_line,
                content=canonical.content,
                content_hash=canonical.content_hash,
                provenance=tuple(provenance_by_key[key] for key in sorted(provenance_by_key)),
                rank_score=canonical.rank_score,
                focus_line=canonical.focus_line,
                cropped=canonical.cropped,
            )
        )
    return tuple(sorted(selected, key=_prepared_sort_key))


def _select_under_budget(
    prepared: Sequence[_PreparedSnippet],
    *,
    requested_tokens: int,
    settings: Settings,
    estimator: TokenEstimatorProtocol,
) -> _BudgetSelection:
    reserved_tokens = min(
        requested_tokens,
        int(requested_tokens * settings.context_token_safety_margin)
        + settings.context_response_envelope_tokens,
    )
    available_tokens = requested_tokens - reserved_tokens
    caps = {
        CandidateRole.PRIMARY: settings.context_max_primary_targets,
        CandidateRole.INTERFACE: settings.context_max_dependency_snippets,
        CandidateRole.SCHEMA: settings.context_max_dependency_snippets,
        CandidateRole.CONFIGURATION: settings.context_max_dependency_snippets,
        CandidateRole.DEPENDENCY: settings.context_max_dependency_snippets,
        CandidateRole.CALLER: settings.context_max_caller_snippets,
        CandidateRole.TEST: settings.context_max_test_snippets,
        CandidateRole.GIT_DIFF: settings.context_max_git_entries,
    }
    by_role: dict[CandidateRole, tuple[_PreparedSnippet, ...]] = {}
    for role in CandidateRole:
        role_items = sorted(
            (item for item in prepared if item.role is role),
            key=_prepared_sort_key,
        )
        by_role[role] = tuple(role_items[: caps[role]])

    selected: list[ContextSnippet] = []
    used_tokens = 0
    for stage in _ALLOCATION_STAGES:
        for item in _round_robin(by_role, stage):
            remaining = available_tokens - used_tokens
            if remaining <= 0:
                break
            candidate = _to_context_snippet(item, estimator)
            if candidate.token_estimate.estimated_tokens > remaining:
                cropped = _crop_to_budget(item, remaining, estimator)
                if cropped is None:
                    continue
                candidate = _to_context_snippet(cropped, estimator)
            selected.append(candidate)
            used_tokens += candidate.token_estimate.estimated_tokens

    pre_budget_tokens = sum(estimator.estimate(item.content).estimated_tokens for item in prepared)
    omitted_items = max(len(prepared) - len(selected), 0)
    role_usage = tuple(
        RoleTokenUsage(
            role=role,
            estimated_tokens=sum(
                snippet.token_estimate.estimated_tokens
                for snippet in selected
                if snippet.role is role
            ),
            item_count=sum(1 for snippet in selected if snippet.role is role),
        )
        for role in CandidateRole
        if any(snippet.role is role for snippet in selected)
    )
    estimated_tokens_saved = max(pre_budget_tokens - used_tokens, 0)
    budget = ContextBudget(
        requested_tokens=requested_tokens,
        reserved_tokens=reserved_tokens,
        used_tokens=used_tokens,
        remaining_tokens=requested_tokens - reserved_tokens - used_tokens,
        pre_budget_tokens=pre_budget_tokens,
        estimated_tokens_saved=estimated_tokens_saved,
        reduction_ratio=(estimated_tokens_saved / pre_budget_tokens if pre_budget_tokens else 0.0),
        role_usage=role_usage,
        omitted_items=omitted_items,
        cropped=any(snippet.cropped for snippet in selected),
    )
    return _BudgetSelection(snippets=tuple(selected), budget=budget)


def _round_robin(
    by_role: dict[CandidateRole, tuple[_PreparedSnippet, ...]],
    roles: tuple[CandidateRole, ...],
) -> tuple[_PreparedSnippet, ...]:
    maximum = max((len(by_role[role]) for role in roles), default=0)
    return tuple(
        by_role[role][index]
        for index in range(maximum)
        for role in roles
        if index < len(by_role[role])
    )


def _crop_to_budget(
    item: _PreparedSnippet,
    max_tokens: int,
    estimator: TokenEstimatorProtocol,
) -> _PreparedSnippet | None:
    lines = item.content.splitlines()
    if not lines:
        return None
    focus_index = min(max(item.focus_line - item.start_line, 0), len(lines) - 1)
    start = focus_index
    end = focus_index + 1
    content = _cropped_content(lines, start, end)
    if estimator.estimate(content).estimated_tokens > max_tokens:
        return None

    prefer_before = True
    while start > 0 or end < len(lines):
        candidates: list[tuple[int, int]] = []
        if prefer_before and start > 0:
            candidates.append((start - 1, end))
        if end < len(lines):
            candidates.append((start, end + 1))
        if not prefer_before and start > 0:
            candidates.append((start - 1, end))
        expanded = False
        for candidate_start, candidate_end in candidates:
            candidate_content = _cropped_content(lines, candidate_start, candidate_end)
            if estimator.estimate(candidate_content).estimated_tokens <= max_tokens:
                start, end, content = candidate_start, candidate_end, candidate_content
                expanded = True
                prefer_before = not prefer_before
                break
        if not expanded:
            break

    start_line = item.start_line + start
    end_line = item.start_line + end - 1
    return _PreparedSnippet(
        role=item.role,
        relative_path=item.relative_path,
        language=item.language,
        kind=item.kind,
        start_line=start_line,
        end_line=end_line,
        content=content,
        content_hash=_content_hash(content),
        provenance=item.provenance,
        rank_score=item.rank_score,
        focus_line=min(max(item.focus_line, start_line), end_line),
        cropped=start > 0 or end < len(lines),
    )


def _cropped_content(lines: Sequence[str], start: int, end: int) -> str:
    selected = list(lines[start:end])
    if start > 0:
        selected.insert(0, f"... ({start} lines omitted) ...")
    if end < len(lines):
        selected.append(f"... ({len(lines) - end} lines omitted) ...")
    return "\n".join(selected)


def _to_context_snippet(
    item: _PreparedSnippet,
    estimator: TokenEstimatorProtocol,
) -> ContextSnippet:
    return ContextSnippet(
        role=item.role,
        relative_path=item.relative_path,
        language=item.language,
        kind=item.kind,
        start_line=item.start_line,
        end_line=item.end_line,
        content=item.content,
        content_hash=item.content_hash,
        provenance=item.provenance,
        rank_score=item.rank_score,
        token_estimate=estimator.estimate(item.content),
        cropped=item.cropped,
    )


def _bundle_diagnostics(
    diagnostics: Sequence[RetrievalDiagnostic],
    confidence: ConfidenceResult,
    ranked_candidates: Sequence[RankedCandidate],
    materialized: Sequence[_PreparedSnippet],
    budget: ContextBudget,
    *,
    invalid_git_paths: int,
    limit: int,
) -> tuple[RetrievalDiagnostic, ...]:
    selected = list(diagnostics)
    materialized_roles = {item.role for item in materialized}
    ranked_roles = {role for ranked in ranked_candidates for role in ranked.candidate.role_hints}
    missing_roles = set(confidence.missing_roles)
    missing_roles.update(role for role in ranked_roles if role not in materialized_roles)
    for role in sorted(missing_roles, key=lambda item: (_ROLE_PRIORITY[item], item.value)):
        selected.append(
            RetrievalDiagnostic(
                code=RetrievalDiagnosticCode.ROLE_MISSING,
                severity=DiagnosticSeverity.WARNING,
                message="An expected context role could not be materialized from the index.",
                role=role,
            )
        )
    if budget.omitted_items:
        selected.append(
            RetrievalDiagnostic(
                code=RetrievalDiagnosticCode.BUDGET_OMITTED,
                severity=DiagnosticSeverity.WARNING,
                message="Some context items were omitted by role or token limits.",
            )
        )
    if invalid_git_paths:
        selected.append(
            RetrievalDiagnostic(
                code=RetrievalDiagnosticCode.GIT_UNAVAILABLE,
                severity=DiagnosticSeverity.WARNING,
                message="An optional Git diff entry had an invalid repository-relative path.",
                role=CandidateRole.GIT_DIFF,
            )
        )
    unique = {_diagnostic_sort_key(item): item for item in selected}
    return tuple(unique[key] for key in sorted(unique)[:limit])


def _git_hunk_line_count(content: str) -> int:
    return sum(
        1
        for line in content.splitlines()
        if line.startswith(("+", " ")) and not line.startswith("+++")
    )


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _ranked_sort_key(
    item: RankedCandidate,
) -> tuple[int, str, int, str, str]:
    candidate = item.candidate
    return (
        item.rank,
        candidate.relative_path,
        candidate.start_line,
        candidate.entity_type.value,
        candidate.entity_id,
    )


def _prepared_sort_key(
    item: _PreparedSnippet,
) -> tuple[float, int, str, int, int, str]:
    return (
        -item.rank_score,
        _ROLE_PRIORITY[item.role],
        item.relative_path,
        item.start_line,
        item.end_line,
        item.content_hash,
    )


def _source_reference_sort_key(
    reference: ContextSourceReference,
) -> tuple[str, int, int, str, str]:
    return (
        reference.relative_path,
        reference.start_line,
        reference.end_line,
        reference.entity_type.value,
        reference.entity_id,
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
