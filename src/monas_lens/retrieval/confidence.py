"""Versioned confidence scoring and one-pass targeted widening."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from monas_lens.config import Settings
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.retrieval.contracts import (
    CandidateRole,
    ConfidenceComponents,
    ConfidenceReason,
    ConfidenceResult,
    ConfidenceStatus,
    DiagnosticSeverity,
    EntityType,
    EvidenceKind,
    RankedCandidate,
    RetrievalCandidate,
    RetrievalDiagnostic,
    RetrievalDiagnosticCode,
    TaskAction,
    TaskResolution,
)
from monas_lens.retrieval.ranker import deduplicate_candidates, rank_candidates
from monas_lens.retrieval.retriever import RetrievalBatch, RetrievalExpansion

CONFIDENCE_FORMULA_VERSION = "1.0"
PRIMARY_CERTAINTY_TABLE_VERSION = "1.0"

CONFIDENCE_COMPONENT_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {
        "primary_target_certainty": 0.40,
        "evidence_agreement": 0.25,
        "separation": 0.20,
        "role_coverage": 0.15,
    }
)
PRIMARY_CERTAINTY_TABLE: Mapping[str, float] = MappingProxyType(
    {
        "missing": 0.0,
        "ambiguous": 0.35,
        "fallback": 0.40,
        "lexical": 0.80,
        "path_lexical": 0.85,
        "explicit_focus": 0.85,
        "exact": 0.95,
        "exact_explicit_focus": 1.0,
    }
)
EVIDENCE_AGREEMENT_TABLE: Mapping[int, float] = MappingProxyType(
    {0: 0.0, 1: 0.25, 2: 0.65, 3: 0.90, 4: 1.0}
)

AMBIGUITY_SCORE_MARGIN = 0.05
FULL_SEPARATION_MARGIN = 0.20
UNAVAILABLE_CHANNEL_PENALTY = 0.05
TRUNCATED_CHANNEL_PENALTY = 0.025

type CandidateIdentity = tuple[str, EntityType, str]

_EXPECTED_ROLES: Mapping[TaskAction, tuple[CandidateRole, ...]] = MappingProxyType(
    {
        TaskAction.DIAGNOSE: (
            CandidateRole.DEPENDENCY,
            CandidateRole.CALLER,
            CandidateRole.CONFIGURATION,
            CandidateRole.TEST,
        ),
        TaskAction.CHANGE: (
            CandidateRole.DEPENDENCY,
            CandidateRole.CALLER,
            CandidateRole.TEST,
        ),
        TaskAction.REFACTOR: (
            CandidateRole.DEPENDENCY,
            CandidateRole.CALLER,
            CandidateRole.INTERFACE,
            CandidateRole.TEST,
        ),
        TaskAction.TEST: (CandidateRole.DEPENDENCY, CandidateRole.TEST),
        TaskAction.EXPLAIN: (
            CandidateRole.DEPENDENCY,
            CandidateRole.CALLER,
            CandidateRole.INTERFACE,
        ),
        TaskAction.UNKNOWN: (
            CandidateRole.DEPENDENCY,
            CandidateRole.CALLER,
            CandidateRole.TEST,
        ),
    }
)
_UNAVAILABLE_CODES = frozenset(
    {
        RetrievalDiagnosticCode.SEARCH_UNAVAILABLE,
        RetrievalDiagnosticCode.GRAPH_UNAVAILABLE,
        RetrievalDiagnosticCode.GIT_UNAVAILABLE,
        RetrievalDiagnosticCode.INDEX_STALE,
    }
)
_TRUNCATED_CODES = frozenset({RetrievalDiagnosticCode.GIT_TRUNCATED})
_REASON_ORDER = (
    ConfidenceReason.MISSING_PRIMARY,
    ConfidenceReason.AMBIGUOUS_TARGET,
    ConfidenceReason.LOW_SEPARATION,
    ConfidenceReason.MISSING_ROLES,
    ConfidenceReason.RETRIEVAL_DEGRADED,
    ConfidenceReason.UNIQUE_TARGET,
    ConfidenceReason.EXPLICIT_FOCUS,
    ConfidenceReason.EVIDENCE_AGREEMENT,
    ConfidenceReason.WIDENED,
)


@dataclass(frozen=True, slots=True)
class ConfidenceAssessment:
    value: float
    components: ConfidenceComponents
    reason_codes: tuple[ConfidenceReason, ...]
    expected_roles: tuple[CandidateRole, ...]
    missing_roles: tuple[CandidateRole, ...]
    unresolved_seeds: tuple[RetrievalCandidate, ...]


@dataclass(frozen=True, slots=True)
class ConfidenceGateOutcome:
    candidates: tuple[RetrievalCandidate, ...]
    ranked_candidates: tuple[RankedCandidate, ...]
    new_candidates: tuple[RetrievalCandidate, ...]
    confidence: ConfidenceResult
    diagnostics: tuple[RetrievalDiagnostic, ...]
    truncated: bool


@runtime_checkable
class ConfidenceWidenerProtocol(Protocol):
    """Targeted expansion used only after a low-confidence first pass."""

    def widen(
        self,
        repository_id: str,
        seeds: Sequence[RetrievalCandidate],
        roles: frozenset[CandidateRole],
        existing_identities: frozenset[CandidateIdentity],
    ) -> RetrievalExpansion: ...


class ConfidenceGate:
    """Calculate request confidence and perform no more than one widening pass."""

    def __init__(self, settings: Settings, widener: ConfidenceWidenerProtocol) -> None:
        self._settings = settings
        self._widener = widener

    def evaluate(
        self,
        resolution: TaskResolution,
        batch: RetrievalBatch,
    ) -> ConfidenceGateOutcome:
        if any(
            candidate.repository_id != batch.repository_id
            for candidate in (*batch.candidates, *batch.primary_seeds)
        ):
            raise MonasLensError(
                ErrorCode.CONTEXT_RETRIEVAL_FAILED,
                "Confidence input crossed a repository boundary.",
            )
        initial_ranked = rank_candidates(
            batch.candidates,
            resolution.explicit_focus_targets,
        )
        initial = assess_confidence(
            initial_ranked,
            resolution.action,
            batch.diagnostics,
            max_primary_targets=self._settings.context_max_primary_targets,
        )
        if (
            initial.value >= self._settings.context_confidence_threshold
            or self._settings.context_max_internal_expansions == 0
        ):
            return _outcome_without_expansion(batch, initial_ranked, initial, self._settings)

        existing_identities = frozenset(candidate.identity for candidate in batch.candidates)
        roles = frozenset(initial.missing_roles or initial.expected_roles)
        expansion = self._expand_once(
            batch.repository_id,
            initial.unresolved_seeds,
            roles,
            existing_identities,
        )
        new_candidates, capped = _bounded_new_candidates(
            expansion.candidates,
            batch.repository_id,
            existing_identities,
            max(self._settings.context_max_candidates - len(existing_identities), 0),
        )
        candidates = deduplicate_candidates((*batch.candidates, *new_candidates))
        ranked = rank_candidates(candidates, resolution.explicit_focus_targets)
        diagnostics = _bounded_diagnostics(
            (*batch.diagnostics, *expansion.diagnostics),
            self._settings.context_max_retrieval_diagnostics,
        )
        final = assess_confidence(
            ranked,
            resolution.action,
            diagnostics,
            max_primary_targets=self._settings.context_max_primary_targets,
            widened=True,
        )
        confidence = _confidence_result(
            initial,
            final,
            threshold=self._settings.context_confidence_threshold,
            expansion_count=1,
        )
        return ConfidenceGateOutcome(
            candidates=tuple(item.candidate for item in ranked),
            ranked_candidates=ranked,
            new_candidates=new_candidates,
            confidence=confidence,
            diagnostics=diagnostics,
            truncated=batch.truncated or expansion.truncated or capped,
        )

    def _expand_once(
        self,
        repository_id: str,
        seeds: tuple[RetrievalCandidate, ...],
        roles: frozenset[CandidateRole],
        existing_identities: frozenset[CandidateIdentity],
    ) -> RetrievalExpansion:
        try:
            return self._widener.widen(
                repository_id,
                seeds,
                roles,
                existing_identities,
            )
        except Exception:
            return RetrievalExpansion(
                candidates=(),
                diagnostics=(
                    RetrievalDiagnostic(
                        code=RetrievalDiagnosticCode.GRAPH_UNAVAILABLE,
                        severity=DiagnosticSeverity.WARNING,
                        message="The confidence widening pass was unavailable.",
                    ),
                ),
            )


def assess_confidence(
    ranked_candidates: Sequence[RankedCandidate],
    action: TaskAction,
    diagnostics: Sequence[RetrievalDiagnostic] = (),
    *,
    max_primary_targets: int = 3,
    widened: bool = False,
) -> ConfidenceAssessment:
    """Calculate one deterministic confidence snapshot from ranked evidence."""

    primary = _deduplicate_logical_primary(_meaningful_primary_candidates(ranked_candidates))
    top = primary[0] if primary else None
    ambiguous = _is_ambiguous(primary)
    target_certainty = _primary_target_certainty(top, ambiguous)
    separation = _separation(primary)
    agreement = _evidence_agreement(top, ranked_candidates)
    expected_roles = _EXPECTED_ROLES[action]
    present_roles = {role for ranked in ranked_candidates for role in ranked.candidate.role_hints}
    missing_roles = tuple(role for role in expected_roles if role not in present_roles)
    role_coverage = (
        (len(expected_roles) - len(missing_roles)) / len(expected_roles) if expected_roles else 1.0
    )
    components = ConfidenceComponents(
        primary_target_certainty=target_certainty,
        evidence_agreement=agreement,
        separation=separation,
        role_coverage=role_coverage,
    )
    value = _weighted_confidence(components) - _diagnostic_penalty(diagnostics)
    unresolved_seeds = _unresolved_seeds(
        primary,
        ambiguous=ambiguous,
        missing_roles=missing_roles,
        max_primary_targets=max_primary_targets,
    )
    reasons = _confidence_reasons(
        top,
        primary_count=len(primary),
        ambiguous=ambiguous,
        separation=separation,
        agreement=agreement,
        missing_roles=missing_roles,
        diagnostics=diagnostics,
        widened=widened,
    )
    return ConfidenceAssessment(
        value=min(max(value, 0.0), 1.0),
        components=components,
        reason_codes=reasons,
        expected_roles=expected_roles,
        missing_roles=missing_roles,
        unresolved_seeds=unresolved_seeds,
    )


def _outcome_without_expansion(
    batch: RetrievalBatch,
    ranked: tuple[RankedCandidate, ...],
    assessment: ConfidenceAssessment,
    settings: Settings,
) -> ConfidenceGateOutcome:
    confidence = _confidence_result(
        assessment,
        assessment,
        threshold=settings.context_confidence_threshold,
        expansion_count=0,
    )
    return ConfidenceGateOutcome(
        candidates=tuple(item.candidate for item in ranked),
        ranked_candidates=ranked,
        new_candidates=(),
        confidence=confidence,
        diagnostics=batch.diagnostics,
        truncated=batch.truncated,
    )


def _confidence_result(
    initial: ConfidenceAssessment,
    final: ConfidenceAssessment,
    *,
    threshold: float,
    expansion_count: int,
) -> ConfidenceResult:
    return ConfidenceResult(
        initial_confidence=initial.value,
        final_confidence=final.value,
        threshold=threshold,
        status=(
            ConfidenceStatus.ACCEPTED if final.value >= threshold else ConfidenceStatus.DEGRADED
        ),
        expansion_count=expansion_count,
        initial_components=initial.components,
        final_components=final.components,
        reason_codes=final.reason_codes,
        missing_roles=final.missing_roles,
    )


def _primary_target_certainty(top: RankedCandidate | None, ambiguous: bool) -> float:
    if top is None:
        return PRIMARY_CERTAINTY_TABLE["missing"]
    if ambiguous:
        return PRIMARY_CERTAINTY_TABLE["ambiguous"]
    if top.components.exact > 0 and top.explicit_focus:
        return PRIMARY_CERTAINTY_TABLE["exact_explicit_focus"]
    if top.components.exact > 0:
        return PRIMARY_CERTAINTY_TABLE["exact"]
    if top.explicit_focus:
        return PRIMARY_CERTAINTY_TABLE["explicit_focus"]
    if top.components.lexical > 0:
        # Path concordance: file-level hits with high lexical score signal strong relevance
        if (
            top.candidate.entity_type in {EntityType.FILE, EntityType.CHUNK}
            and top.components.lexical >= 0.70
        ):
            return PRIMARY_CERTAINTY_TABLE["path_lexical"]
        return PRIMARY_CERTAINTY_TABLE["lexical"]
    return PRIMARY_CERTAINTY_TABLE["fallback"]


def _is_ambiguous(primary: Sequence[RankedCandidate]) -> bool:
    if len(primary) < 2:
        return False
    top, alternative = primary[:2]
    if top.explicit_focus and not alternative.explicit_focus:
        return False
    return top.score - alternative.score <= AMBIGUITY_SCORE_MARGIN


def _deduplicate_logical_primary(
    primary: Sequence[RankedCandidate],
) -> tuple[RankedCandidate, ...]:
    selected: list[RankedCandidate] = []
    seen: set[tuple[str, str]] = set()
    for ranked in primary:
        candidate = ranked.candidate
        key = (
            candidate.relative_path,
            candidate.qualified_name or candidate.name or candidate.entity_id,
        )
        if key in seen:
            continue
        seen.add(key)
        selected.append(ranked)
    return tuple(selected)


def _meaningful_primary_candidates(
    ranked_candidates: Sequence[RankedCandidate],
) -> tuple[RankedCandidate, ...]:
    primary = tuple(
        ranked
        for ranked in ranked_candidates
        if CandidateRole.PRIMARY in ranked.candidate.role_hints
    )
    named_code = tuple(
        ranked
        for ranked in primary
        if ranked.candidate.entity_type in {EntityType.SYMBOL, EntityType.CHUNK}
        and (ranked.candidate.qualified_name or ranked.candidate.name)
    )
    return named_code or primary


def _separation(primary: Sequence[RankedCandidate]) -> float:
    if not primary:
        return 0.0
    if len(primary) == 1:
        return 1.0
    if primary[0].explicit_focus and not primary[1].explicit_focus:
        return 1.0
    margin = max(primary[0].score - primary[1].score, 0.0)
    return min(margin / FULL_SEPARATION_MARGIN, 1.0)


def _evidence_agreement(
    top: RankedCandidate | None,
    ranked_candidates: Sequence[RankedCandidate],
) -> float:
    if top is None:
        return EVIDENCE_AGREEMENT_TABLE[0]
    families: set[EvidenceKind] = set()
    for ranked in ranked_candidates:
        for evidence in ranked.candidate.evidence:
            if ranked.candidate.identity == top.candidate.identity or (
                evidence.seed_id == top.candidate.entity_id
            ):
                families.add(evidence.kind)
    return EVIDENCE_AGREEMENT_TABLE[min(len(families), max(EVIDENCE_AGREEMENT_TABLE))]


def _weighted_confidence(components: ConfidenceComponents) -> float:
    return sum(
        getattr(components, name) * weight for name, weight in CONFIDENCE_COMPONENT_WEIGHTS.items()
    )


def _diagnostic_penalty(diagnostics: Sequence[RetrievalDiagnostic]) -> float:
    codes = {diagnostic.code for diagnostic in diagnostics}
    penalty = UNAVAILABLE_CHANNEL_PENALTY if codes & _UNAVAILABLE_CODES else 0.0
    if codes & _TRUNCATED_CODES:
        penalty += TRUNCATED_CHANNEL_PENALTY
    return penalty


def _unresolved_seeds(
    primary: Sequence[RankedCandidate],
    *,
    ambiguous: bool,
    missing_roles: tuple[CandidateRole, ...],
    max_primary_targets: int,
) -> tuple[RetrievalCandidate, ...]:
    if not primary:
        return ()
    if ambiguous:
        top_score = primary[0].score
        return tuple(
            ranked.candidate
            for ranked in primary
            if top_score - ranked.score <= AMBIGUITY_SCORE_MARGIN
        )[:max_primary_targets]
    if missing_roles or primary[0].components.exact == 0:
        return (primary[0].candidate,)
    return ()


def _confidence_reasons(
    top: RankedCandidate | None,
    *,
    primary_count: int,
    ambiguous: bool,
    separation: float,
    agreement: float,
    missing_roles: tuple[CandidateRole, ...],
    diagnostics: Sequence[RetrievalDiagnostic],
    widened: bool,
) -> tuple[ConfidenceReason, ...]:
    selected: set[ConfidenceReason] = set()
    if top is None:
        selected.add(ConfidenceReason.MISSING_PRIMARY)
    elif ambiguous:
        selected.add(ConfidenceReason.AMBIGUOUS_TARGET)
    else:
        selected.add(ConfidenceReason.UNIQUE_TARGET)
    if primary_count > 1 and separation < 0.5:
        selected.add(ConfidenceReason.LOW_SEPARATION)
    if top is not None and top.explicit_focus:
        selected.add(ConfidenceReason.EXPLICIT_FOCUS)
    if agreement >= EVIDENCE_AGREEMENT_TABLE[2]:
        selected.add(ConfidenceReason.EVIDENCE_AGREEMENT)
    if missing_roles:
        selected.add(ConfidenceReason.MISSING_ROLES)
    if _diagnostic_penalty(diagnostics) > 0:
        selected.add(ConfidenceReason.RETRIEVAL_DEGRADED)
    if widened:
        selected.add(ConfidenceReason.WIDENED)
    return tuple(reason for reason in _REASON_ORDER if reason in selected)


def _bounded_new_candidates(
    candidates: Sequence[RetrievalCandidate],
    repository_id: str,
    existing_identities: frozenset[CandidateIdentity],
    limit: int,
) -> tuple[tuple[RetrievalCandidate, ...], bool]:
    if any(candidate.repository_id != repository_id for candidate in candidates):
        raise MonasLensError(
            ErrorCode.CONTEXT_RETRIEVAL_FAILED,
            "Confidence widening crossed a repository boundary.",
        )
    unseen = tuple(
        candidate for candidate in candidates if candidate.identity not in existing_identities
    )
    deduplicated = deduplicate_candidates(unseen)
    return deduplicated[:limit], len(deduplicated) > limit


def _bounded_diagnostics(
    diagnostics: Sequence[RetrievalDiagnostic],
    limit: int,
) -> tuple[RetrievalDiagnostic, ...]:
    unique = {_diagnostic_sort_key(diagnostic): diagnostic for diagnostic in diagnostics}
    return tuple(unique[key] for key in sorted(unique)[:limit])


def _diagnostic_sort_key(
    diagnostic: RetrievalDiagnostic,
) -> tuple[str, str, str, str]:
    return (
        diagnostic.code.value,
        diagnostic.severity.value,
        diagnostic.role.value if diagnostic.role is not None else "",
        diagnostic.message,
    )
