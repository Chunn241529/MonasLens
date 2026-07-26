from __future__ import annotations

import json
import random
from collections.abc import Sequence
from pathlib import Path

import pytest

from monas_lens.config import Settings
from monas_lens.graph.contracts import RelationKind
from monas_lens.retrieval.confidence import (
    CONFIDENCE_FORMULA_VERSION,
    PRIMARY_CERTAINTY_TABLE_VERSION,
    ConfidenceGate,
    ConfidenceGateOutcome,
)
from monas_lens.retrieval.contracts import (
    CandidateRole,
    ConfidenceReason,
    ConfidenceStatus,
    EntityType,
    EvidenceKind,
    RetrievalCandidate,
    RetrievalEvidence,
    TaskAction,
    TaskResolution,
)
from monas_lens.retrieval.retriever import RetrievalBatch, RetrievalExpansion

type CandidateIdentity = tuple[str, EntityType, str]


class _Widener:
    def __init__(self, expansion: RetrievalExpansion | None = None) -> None:
        self._expansion = expansion or RetrievalExpansion(candidates=())
        self.calls: list[
            tuple[tuple[str, ...], frozenset[CandidateRole], frozenset[CandidateIdentity]]
        ] = []

    def widen(
        self,
        repository_id: str,
        seeds: Sequence[RetrievalCandidate],
        roles: frozenset[CandidateRole],
        existing_identities: frozenset[CandidateIdentity],
    ) -> RetrievalExpansion:
        assert repository_id == "repository-1"
        self.calls.append(
            (
                tuple(seed.entity_id for seed in seeds),
                roles,
                existing_identities,
            )
        )
        return self._expansion


def test_unique_qualified_target_with_coherent_evidence_clears_threshold(
    settings: Settings,
) -> None:
    primary = _primary("target")
    candidates = (
        primary,
        _related("dependency", CandidateRole.DEPENDENCY, "target", ordinal=10),
        _related("caller", CandidateRole.CALLER, "target", ordinal=11),
        _related("configuration", CandidateRole.CONFIGURATION, "target", ordinal=12),
        _related("test", CandidateRole.TEST, "target", ordinal=13),
    )
    widener = _Widener()

    outcome = ConfidenceGate(settings, widener).evaluate(
        _resolution(TaskAction.DIAGNOSE),
        _batch(candidates, primary),
    )

    assert CONFIDENCE_FORMULA_VERSION == "1.0"
    assert PRIMARY_CERTAINTY_TABLE_VERSION == "1.0"
    assert outcome.confidence.initial_components.model_dump() == {
        "primary_target_certainty": 0.95,
        "evidence_agreement": 1.0,
        "separation": 1.0,
        "role_coverage": 1.0,
    }
    assert outcome.confidence.final_confidence == pytest.approx(0.98)
    assert outcome.confidence.status is ConfidenceStatus.ACCEPTED
    assert outcome.confidence.expansion_count == 0
    assert ConfidenceReason.UNIQUE_TARGET in outcome.confidence.reason_codes
    assert ConfidenceReason.EVIDENCE_AGREEMENT in outcome.confidence.reason_codes
    assert widener.calls == []


def test_low_confidence_widens_missing_roles_once_and_reranks(settings: Settings) -> None:
    primary = _primary("target")
    expansion = RetrievalExpansion(
        candidates=(
            _related("dependency", CandidateRole.DEPENDENCY, "target", ordinal=10),
            _related("caller", CandidateRole.CALLER, "target", ordinal=11),
            _related("test", CandidateRole.TEST, "target", ordinal=12),
        )
    )
    widener = _Widener(expansion)

    outcome = ConfidenceGate(settings, widener).evaluate(
        _resolution(TaskAction.CHANGE),
        _batch((primary,), primary),
    )

    assert outcome.confidence.initial_confidence == pytest.approx(0.7425)
    assert outcome.confidence.final_confidence == pytest.approx(0.98)
    assert outcome.confidence.status is ConfidenceStatus.ACCEPTED
    assert outcome.confidence.expansion_count == 1
    assert outcome.confidence.missing_roles == ()
    assert outcome.confidence.reason_codes[-1] is ConfidenceReason.WIDENED
    assert {candidate.entity_id for candidate in outcome.new_candidates} == {
        "caller",
        "dependency",
        "test",
    }
    assert len(widener.calls) == 1
    seeds, roles, existing = widener.calls[0]
    assert seeds == ("target",)
    assert roles == {
        CandidateRole.CALLER,
        CandidateRole.DEPENDENCY,
        CandidateRole.TEST,
    }
    assert existing == {primary.identity}


def test_ambiguous_same_name_targets_remain_degraded_after_one_pass(
    settings: Settings,
) -> None:
    first = _primary("first", qualified_name="Service.run", relative_path="a.py")
    second = _primary("second", qualified_name="Service.run", relative_path="b.py")
    supporting = (
        _related("dependency", CandidateRole.DEPENDENCY, "first", ordinal=10),
        _related("caller", CandidateRole.CALLER, "first", ordinal=11),
        _related("test", CandidateRole.TEST, "first", ordinal=12),
    )
    widener = _Widener()
    resolution = _resolution(TaskAction.CHANGE)
    batch = _batch((first, second, *supporting), first, second)

    outcome = ConfidenceGate(settings, widener).evaluate(resolution, batch)

    assert outcome.confidence.status is ConfidenceStatus.DEGRADED
    assert outcome.confidence.expansion_count == 1
    assert ConfidenceReason.AMBIGUOUS_TARGET in outcome.confidence.reason_codes
    assert ConfidenceReason.LOW_SEPARATION in outcome.confidence.reason_codes
    assert len(widener.calls) == 1
    assert widener.calls[0][0] == ("first", "second")

    expected = _outcome_json(outcome)
    for seed in range(5):
        shuffled = list(batch.candidates)
        random.Random(seed).shuffle(shuffled)
        repeated = ConfidenceGate(settings, _Widener()).evaluate(
            resolution,
            batch.__class__(
                repository_id=batch.repository_id,
                candidates=tuple(shuffled),
                primary_seeds=batch.primary_seeds,
                diagnostics=batch.diagnostics,
            ),
        )
        assert _outcome_json(repeated) == expected


def test_widening_discards_existing_identities_and_obeys_global_candidate_cap(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "confidence", context_max_candidates=10)
    primary = _primary("target")
    returned = (
        primary,
        *(
            _related(
                f"dependency-{index:02}",
                CandidateRole.DEPENDENCY,
                "target",
                ordinal=10 + index,
            )
            for index in range(12)
        ),
    )
    widener = _Widener(RetrievalExpansion(candidates=returned))

    outcome = ConfidenceGate(settings, widener).evaluate(
        _resolution(TaskAction.CHANGE),
        _batch((primary,), primary),
    )

    assert primary.identity not in {candidate.identity for candidate in outcome.new_candidates}
    assert len(outcome.new_candidates) == 9
    assert len(outcome.candidates) == 10
    assert outcome.truncated
    assert len(widener.calls) == 1


def _resolution(action: TaskAction) -> TaskResolution:
    return TaskResolution(
        normalized_task="Change Service.run",
        action=action,
        qualified_identifiers=("Service.run",),
        lexical_queries=("Service.run",),
    )


def _batch(
    candidates: tuple[RetrievalCandidate, ...],
    *primary_seeds: RetrievalCandidate,
) -> RetrievalBatch:
    return RetrievalBatch(
        repository_id="repository-1",
        candidates=candidates,
        primary_seeds=primary_seeds,
        diagnostics=(),
    )


def _primary(
    entity_id: str,
    *,
    qualified_name: str = "Service.run",
    relative_path: str = "service.py",
) -> RetrievalCandidate:
    return RetrievalCandidate(
        repository_id="repository-1",
        entity_type=EntityType.SYMBOL,
        entity_id=entity_id,
        relative_path=relative_path,
        language="python",
        kind="method",
        name="run",
        qualified_name=qualified_name,
        start_line=1,
        end_line=3,
        role_hints=(CandidateRole.PRIMARY,),
        evidence=(
            RetrievalEvidence(
                kind=EvidenceKind.EXACT,
                query="Service.run",
                source_score=1.0,
                explanation="Exact symbol fixture.",
            ),
            RetrievalEvidence(
                kind=EvidenceKind.LEXICAL,
                query="Service.run",
                source_score=0.9,
                explanation="Lexical symbol fixture.",
            ),
        ),
        retrieval_ordinal=0,
    )


def _related(
    entity_id: str,
    role: CandidateRole,
    seed_id: str,
    *,
    ordinal: int,
) -> RetrievalCandidate:
    relation = {
        CandidateRole.CALLER: RelationKind.CALLS,
        CandidateRole.CONFIGURATION: RelationKind.CONFIGURED_BY,
        CandidateRole.DEPENDENCY: RelationKind.IMPORTS,
        CandidateRole.TEST: RelationKind.TESTED_BY,
    }[role]
    evidence_kind = EvidenceKind.TEST if role is CandidateRole.TEST else EvidenceKind.GRAPH
    return RetrievalCandidate(
        repository_id="repository-1",
        entity_type=EntityType.SYMBOL,
        entity_id=entity_id,
        relative_path=f"{entity_id}.py",
        language="python",
        kind="function",
        name=entity_id,
        qualified_name=entity_id,
        start_line=1,
        end_line=2,
        role_hints=(role,),
        evidence=(
            RetrievalEvidence(
                kind=evidence_kind,
                query=seed_id,
                seed_id=seed_id,
                relation_kind=relation,
                distance=1,
                source_score=0.9,
                explanation="Related fixture evidence.",
            ),
        ),
        retrieval_ordinal=ordinal,
    )


def _outcome_json(outcome: ConfidenceGateOutcome) -> str:
    return json.dumps(
        {
            "ranked": [ranked.model_dump(mode="json") for ranked in outcome.ranked_candidates],
            "confidence": outcome.confidence.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
