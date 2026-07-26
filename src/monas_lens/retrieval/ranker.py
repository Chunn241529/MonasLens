"""Deterministic evidence ranking for retrieved context candidates."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from monas_lens.retrieval.contracts import (
    CandidateRole,
    EntityType,
    EvidenceKind,
    RankedCandidate,
    RetrievalCandidate,
    RetrievalEvidence,
    ScoreComponents,
)

EXACT_WEIGHT = 0.35
GRAPH_WEIGHT = 0.25
LEXICAL_WEIGHT = 0.20
TEST_WEIGHT = 0.10
SEMANTIC_WEIGHT = 0.10
ENABLED_WEIGHT_TOTAL = EXACT_WEIGHT + GRAPH_WEIGHT + LEXICAL_WEIGHT + TEST_WEIGHT

GRAPH_DEPTH_DECAY = {1: 1.0, 2: 0.5}
EXPLICIT_FOCUS_MAX_BOOST = 0.05

_MAX_EVIDENCE_PER_CANDIDATE = 32
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
_EVIDENCE_PRIORITY = {
    EvidenceKind.EXACT: 0,
    EvidenceKind.LEXICAL: 1,
    EvidenceKind.GRAPH: 2,
    EvidenceKind.TEST: 3,
}

type CandidateIdentity = tuple[str, EntityType, str]
type ScoredCandidate = tuple[RetrievalCandidate, ScoreComponents, float, bool]


def rank_candidates(
    candidates: Sequence[RetrievalCandidate],
    explicit_focus_targets: Sequence[str] = (),
) -> tuple[RankedCandidate, ...]:
    """Deduplicate and rank candidates without changing source-service evidence scores.

    Semantic evidence is disabled, so normalization uses the enabled weight total of ``0.90``.
    Depth-two relationship evidence receives half the depth-one signal. Explicit focus is not an
    evidence family: it closes at most five percent of the remaining score headroom and is then a
    stable tie-break, so inferred targets never receive the boost.
    """

    focus_targets = frozenset(target.strip() for target in explicit_focus_targets if target.strip())
    scored: list[ScoredCandidate] = []
    for candidate in deduplicate_candidates(candidates):
        components = _score_components(candidate.evidence)
        base_score = _normalized_score(components)
        explicit_focus = _matches_explicit_focus(candidate, focus_targets)
        score = _apply_explicit_focus_boost(base_score) if explicit_focus else base_score
        scored.append((candidate, components, score, explicit_focus))

    ordered = sorted(scored, key=_rank_sort_key)
    return tuple(
        RankedCandidate(
            candidate=candidate,
            components=components,
            score=score,
            explicit_focus=explicit_focus,
            rank=rank,
        )
        for rank, (candidate, components, score, explicit_focus) in enumerate(ordered, start=1)
    )


def deduplicate_candidates(
    candidates: Sequence[RetrievalCandidate],
) -> tuple[RetrievalCandidate, ...]:
    """Merge duplicate candidate identities with canonical roles and evidence ordering."""

    grouped: dict[CandidateIdentity, list[RetrievalCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.identity, []).append(candidate)

    merged: list[RetrievalCandidate] = []
    for identity in sorted(grouped, key=_identity_sort_key):
        occurrences = grouped[identity]
        base = min(occurrences, key=_candidate_canonical_key)
        roles = tuple(
            sorted(
                {role for candidate in occurrences for role in candidate.role_hints},
                key=lambda role: (_ROLE_PRIORITY[role], role.value),
            )
        )
        evidence = _merge_evidence(occurrences)
        merged.append(
            base.model_copy(
                update={
                    "role_hints": roles,
                    "evidence": evidence,
                    "retrieval_ordinal": min(
                        candidate.retrieval_ordinal for candidate in occurrences
                    ),
                }
            )
        )
    return tuple(merged)


def _score_components(evidence: Sequence[RetrievalEvidence]) -> ScoreComponents:
    return ScoreComponents(
        exact=max(
            (item.source_score for item in evidence if item.kind is EvidenceKind.EXACT),
            default=0.0,
        ),
        lexical=max(
            (item.source_score for item in evidence if item.kind is EvidenceKind.LEXICAL),
            default=0.0,
        ),
        graph=max(
            (_relationship_signal(item) for item in evidence if item.kind is EvidenceKind.GRAPH),
            default=0.0,
        ),
        test=max(
            (_relationship_signal(item) for item in evidence if item.kind is EvidenceKind.TEST),
            default=0.0,
        ),
        semantic=0.0,
    )


def _relationship_signal(evidence: RetrievalEvidence) -> float:
    distance = cast(int, evidence.distance)
    return evidence.source_score * GRAPH_DEPTH_DECAY[distance]


def _normalized_score(components: ScoreComponents) -> float:
    weighted_sum = (
        (components.exact * EXACT_WEIGHT)
        + (components.graph * GRAPH_WEIGHT)
        + (components.lexical * LEXICAL_WEIGHT)
        + (components.test * TEST_WEIGHT)
    )
    return min(max(weighted_sum / ENABLED_WEIGHT_TOTAL, 0.0), 1.0)


def _apply_explicit_focus_boost(score: float) -> float:
    boost = (1.0 - score) * EXPLICIT_FOCUS_MAX_BOOST
    return min(score + boost, 1.0)


def _matches_explicit_focus(
    candidate: RetrievalCandidate,
    focus_targets: frozenset[str],
) -> bool:
    return any(
        value is not None and value in focus_targets
        for value in (
            candidate.entity_id,
            candidate.relative_path,
            candidate.name,
            candidate.qualified_name,
        )
    )


def _merge_evidence(
    occurrences: Sequence[RetrievalCandidate],
) -> tuple[RetrievalEvidence, ...]:
    unique = {
        _evidence_sort_key(evidence): evidence
        for candidate in occurrences
        for evidence in candidate.evidence
    }
    ordered = [unique[key] for key in sorted(unique)]
    if len(ordered) <= _MAX_EVIDENCE_PER_CANDIDATE:
        return tuple(ordered)

    strongest: dict[EvidenceKind, RetrievalEvidence] = {}
    for evidence in ordered:
        current = strongest.get(evidence.kind)
        if current is None or _strongest_evidence_key(evidence) < _strongest_evidence_key(current):
            strongest[evidence.kind] = evidence
    selected_keys = {_evidence_sort_key(evidence) for evidence in strongest.values()}
    for evidence in ordered:
        if len(selected_keys) == _MAX_EVIDENCE_PER_CANDIDATE:
            break
        selected_keys.add(_evidence_sort_key(evidence))
    return tuple(unique[key] for key in sorted(selected_keys))


def _strongest_evidence_key(
    evidence: RetrievalEvidence,
) -> tuple[float, int, tuple[int, str, str, str, int, float, str]]:
    signal = (
        _relationship_signal(evidence)
        if evidence.kind in {EvidenceKind.GRAPH, EvidenceKind.TEST}
        else evidence.source_score
    )
    return (-signal, evidence.distance or 0, _evidence_sort_key(evidence))


def _rank_sort_key(
    scored: ScoredCandidate,
) -> tuple[float, bool, int, str, int, str, str, str]:
    candidate, _, score, explicit_focus = scored
    role_priority = min(_ROLE_PRIORITY[role] for role in candidate.role_hints)
    return (
        -score,
        not explicit_focus,
        role_priority,
        candidate.relative_path,
        candidate.start_line,
        candidate.entity_type.value,
        candidate.entity_id,
        candidate.repository_id,
    )


def _candidate_canonical_key(
    candidate: RetrievalCandidate,
) -> tuple[int, str, int, int, str, str, str, str, str]:
    return (
        candidate.retrieval_ordinal,
        candidate.relative_path,
        candidate.start_line,
        candidate.end_line,
        candidate.language,
        candidate.kind,
        candidate.name or "",
        candidate.qualified_name or "",
        candidate.entity_id,
    )


def _identity_sort_key(identity: CandidateIdentity) -> tuple[str, str, str]:
    return (identity[0], identity[1].value, identity[2])


def _evidence_sort_key(
    evidence: RetrievalEvidence,
) -> tuple[int, str, str, str, int, float, str]:
    return (
        _EVIDENCE_PRIORITY[evidence.kind],
        evidence.query,
        evidence.seed_id or "",
        evidence.relation_kind.value if evidence.relation_kind is not None else "",
        evidence.distance or 0,
        -evidence.source_score,
        evidence.explanation,
    )
