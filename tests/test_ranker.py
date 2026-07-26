from __future__ import annotations

import json
import random
from collections.abc import Sequence

import pytest

from monas_lens.graph.contracts import RelationKind
from monas_lens.retrieval import ranker as ranker_module
from monas_lens.retrieval.contracts import (
    CandidateRole,
    EntityType,
    EvidenceKind,
    RankedCandidate,
    RetrievalCandidate,
    RetrievalEvidence,
)
from monas_lens.retrieval.ranker import (
    ENABLED_WEIGHT_TOTAL,
    EXPLICIT_FOCUS_MAX_BOOST,
    rank_candidates,
)


def test_exact_unique_symbol_outranks_lexical_only_candidate() -> None:
    lexical = _candidate("lexical", (_evidence(EvidenceKind.LEXICAL, score=1.0),))
    exact = _candidate("exact", (_evidence(EvidenceKind.EXACT, score=1.0),))

    ranked = rank_candidates((lexical, exact))

    assert [item.candidate.entity_id for item in ranked] == ["exact", "lexical"]
    assert ranked[0].components.exact == 1.0
    assert ranked[0].score == pytest.approx(0.35 / ENABLED_WEIGHT_TOTAL)
    assert ranked[1].components.lexical == 1.0


def test_direct_graph_evidence_outranks_depth_two_evidence() -> None:
    depth_two = _candidate(
        "depth-two",
        (_evidence(EvidenceKind.GRAPH, score=0.8, distance=2),),
        relative_path="a.py",
        role=CandidateRole.DEPENDENCY,
    )
    direct = _candidate(
        "direct",
        (_evidence(EvidenceKind.GRAPH, score=0.8, distance=1),),
        relative_path="z.py",
        role=CandidateRole.DEPENDENCY,
    )

    ranked = rank_candidates((depth_two, direct))

    assert [item.candidate.entity_id for item in ranked] == ["direct", "depth-two"]
    assert ranked[0].components.graph == pytest.approx(0.8)
    assert ranked[1].components.graph == pytest.approx(0.4)


def test_tested_by_evidence_only_improves_the_related_test() -> None:
    unrelated = _candidate(
        "unrelated-test",
        (_evidence(EvidenceKind.LEXICAL, score=0.5),),
        relative_path="tests/a_test.py",
        role=CandidateRole.TEST,
        name="test_run",
    )
    related = _candidate(
        "related-test",
        (
            _evidence(EvidenceKind.LEXICAL, score=0.5),
            _evidence(EvidenceKind.TEST, score=0.9, distance=1),
        ),
        relative_path="tests/z_test.py",
        role=CandidateRole.TEST,
        name="test_run",
    )

    ranked = rank_candidates((unrelated, related))

    assert [item.candidate.entity_id for item in ranked] == ["related-test", "unrelated-test"]
    assert ranked[0].components.test == pytest.approx(0.9)
    assert ranked[1].components.test == 0.0


def test_disabled_semantic_weight_cannot_change_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = (
        _candidate("lexical", (_evidence(EvidenceKind.LEXICAL, score=1.0),)),
        _candidate("exact", (_evidence(EvidenceKind.EXACT, score=1.0),)),
    )
    expected = _ranked_json(rank_candidates(candidates))

    monkeypatch.setattr(ranker_module, "SEMANTIC_WEIGHT", 1.0)
    ranked = rank_candidates(candidates)

    assert _ranked_json(ranked) == expected
    assert pytest.approx(0.90) == ENABLED_WEIGHT_TOTAL
    assert all(item.components.semantic == 0.0 for item in ranked)


def test_only_explicit_focus_receives_a_bounded_boost() -> None:
    inferred = _candidate(
        "inferred",
        (_evidence(EvidenceKind.LEXICAL, score=0.7),),
        relative_path="a.py",
        qualified_name="Service.inferred",
    )
    focused = _candidate(
        "focused",
        (_evidence(EvidenceKind.LEXICAL, score=0.7),),
        relative_path="z.py",
        qualified_name="Service.focused",
    )
    source_payloads = (inferred.model_dump_json(), focused.model_dump_json())

    without_focus = rank_candidates((focused, inferred))
    with_focus = rank_candidates((focused, inferred), ("Service.focused",))

    assert [item.candidate.entity_id for item in without_focus] == ["inferred", "focused"]
    assert [item.candidate.entity_id for item in with_focus] == ["focused", "inferred"]
    assert with_focus[0].explicit_focus
    assert not with_focus[1].explicit_focus
    assert 0 < with_focus[0].score - with_focus[1].score <= EXPLICIT_FOCUS_MAX_BOOST
    assert (inferred.model_dump_json(), focused.model_dump_json()) == source_payloads


def test_shuffled_candidates_and_evidence_produce_byte_equivalent_ranked_json() -> None:
    primary = _candidate(
        "target",
        (
            _evidence(EvidenceKind.LEXICAL, score=0.8, query="timeout"),
            _evidence(EvidenceKind.EXACT, score=1.0, query="Service.run"),
        ),
        qualified_name="Service.run",
        retrieval_ordinal=4,
    )
    duplicate = _candidate(
        "target",
        (_evidence(EvidenceKind.GRAPH, score=0.9, distance=1),),
        role=CandidateRole.CALLER,
        qualified_name="Service.run",
        retrieval_ordinal=9,
    )
    test = _candidate(
        "related-test",
        (_evidence(EvidenceKind.TEST, score=0.9, distance=1),),
        role=CandidateRole.TEST,
        relative_path="tests/test_service.py",
    )
    expected = _ranked_json(rank_candidates((primary, duplicate, test), ("Service.run",)))

    for seed in range(10):
        randomizer = random.Random(seed)
        shuffled: list[RetrievalCandidate] = []
        candidates = [primary, duplicate, test]
        randomizer.shuffle(candidates)
        for candidate in candidates:
            evidence = list(candidate.evidence)
            randomizer.shuffle(evidence)
            shuffled.append(candidate.model_copy(update={"evidence": tuple(evidence)}))

        ranked = rank_candidates(tuple(shuffled), ("Service.run",))

        assert _ranked_json(ranked) == expected
        assert len(ranked) == 2


def test_identity_deduplication_keeps_strongest_bounded_evidence() -> None:
    lexical_evidence = tuple(
        _evidence(EvidenceKind.LEXICAL, score=0.1, query=f"query-{index:02}") for index in range(32)
    )
    first = _candidate("target", lexical_evidence)
    duplicate = _candidate(
        "target",
        (
            _evidence(EvidenceKind.EXACT, score=1.0, query="exact"),
            _evidence(EvidenceKind.LEXICAL, score=0.9, query="strong-lexical"),
            _evidence(EvidenceKind.GRAPH, score=0.8, distance=1),
            _evidence(EvidenceKind.TEST, score=0.7, distance=1),
        ),
        role=CandidateRole.TEST,
        retrieval_ordinal=1,
    )

    ranked = rank_candidates((duplicate, first))

    assert len(ranked) == 1
    assert len(ranked[0].candidate.evidence) == 32
    assert ranked[0].candidate.role_hints == (CandidateRole.PRIMARY, CandidateRole.TEST)
    assert ranked[0].components.exact == 1.0
    assert ranked[0].components.lexical == 0.9
    assert ranked[0].components.graph == 0.8
    assert ranked[0].components.test == 0.7


def _candidate(
    entity_id: str,
    evidence: tuple[RetrievalEvidence, ...],
    *,
    relative_path: str | None = None,
    role: CandidateRole = CandidateRole.PRIMARY,
    name: str | None = None,
    qualified_name: str | None = None,
    retrieval_ordinal: int = 0,
) -> RetrievalCandidate:
    display_name = name or entity_id
    return RetrievalCandidate(
        repository_id="repository-1",
        entity_type=EntityType.SYMBOL,
        entity_id=entity_id,
        relative_path=relative_path or f"src/{entity_id}.py",
        language="python",
        kind="function",
        name=display_name,
        qualified_name=qualified_name or display_name,
        start_line=1,
        end_line=2,
        role_hints=(role,),
        evidence=evidence,
        retrieval_ordinal=retrieval_ordinal,
    )


def _evidence(
    kind: EvidenceKind,
    *,
    score: float,
    distance: int | None = None,
    query: str = "run",
) -> RetrievalEvidence:
    relation_kind: RelationKind | None = None
    seed_id: str | None = None
    if kind is EvidenceKind.GRAPH:
        relation_kind = RelationKind.CALLS
        seed_id = "seed"
    elif kind is EvidenceKind.TEST:
        relation_kind = RelationKind.TESTED_BY
        seed_id = "seed"
    return RetrievalEvidence(
        kind=kind,
        query=query,
        seed_id=seed_id,
        relation_kind=relation_kind,
        distance=distance,
        source_score=score,
        explanation=f"{kind.value} fixture evidence.",
    )


def _ranked_json(ranked: Sequence[RankedCandidate]) -> bytes:
    return json.dumps(
        [item.model_dump(mode="json") for item in ranked],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
