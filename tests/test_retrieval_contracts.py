import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import monas_lens.retrieval.contracts as retrieval_contracts
from monas_lens.config import Settings
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.graph import RelationKind
from monas_lens.retrieval import (
    CandidateRole,
    ConfidenceComponents,
    ConfidenceResult,
    ConfidenceStatus,
    ContextBudget,
    ContextBundle,
    ContextSnippet,
    ContextSourceReference,
    EntityType,
    EvidenceKind,
    RankedCandidate,
    RetrievalCandidate,
    RetrievalEvidence,
    RoleTokenUsage,
    ScoreComponents,
    TaskAction,
    TaskResolution,
    TokenEstimate,
    ValidationCommand,
    parse_task_context_request,
)

EXPECTED_SCHEMA_SHA256 = "046d2edfa89fa859509cd6a92ac8dad4625404c9f6c8bbdcd3380dd205680240"


def test_context_settings_defaults_and_bounds(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "state")

    assert settings.context_max_task_chars == 4_000
    assert settings.context_max_focus_targets == 10
    assert settings.context_max_primary_targets == 3
    assert settings.context_max_dependency_snippets == 6
    assert settings.context_max_caller_snippets == 6
    assert settings.context_max_test_snippets == 4
    assert settings.context_max_git_entries == 5
    assert settings.context_max_total_tokens == 12_000
    assert settings.context_confidence_threshold == 0.80
    assert settings.context_max_internal_expansions == 1
    assert settings.context_initial_graph_depth == 1
    assert settings.context_expanded_graph_depth == 2

    with pytest.raises(ValidationError):
        Settings(data_dir=tmp_path / "state", context_confidence_threshold=1.01)
    with pytest.raises(ValidationError):
        Settings(data_dir=tmp_path / "state", context_max_internal_expansions=2)
    with pytest.raises(ValidationError):
        Settings(data_dir=tmp_path / "state", context_expanded_graph_depth=3)


def test_request_parser_normalizes_input_and_applies_budget_default() -> None:
    request = parse_task_context_request(
        {
            "task": "  Fix Parser.run  ",
            "focus_targets": [" src/parser.py ", "src/parser.py", "Parser.run"],
        },
        max_tokens_limit=12_000,
    )

    assert request.task == "Fix Parser.run"
    assert request.focus_targets == ("src/parser.py", "Parser.run")
    assert request.max_tokens == 12_000

    with pytest.raises(ValidationError):
        request.task = "different"


@pytest.mark.parametrize(
    ("payload", "limit", "expected_code"),
    [
        ({"task": "!!!"}, 12_000, ErrorCode.CONTEXT_REQUEST_INVALID),
        (
            {"task": "fix", "focus_targets": [f"target-{index}" for index in range(11)]},
            12_000,
            ErrorCode.CONTEXT_REQUEST_INVALID,
        ),
        ({"task": "fix", "max_tokens": 255}, 12_000, ErrorCode.CONTEXT_BUDGET_INVALID),
        ({"task": "fix", "max_tokens": 12_001}, 12_000, ErrorCode.CONTEXT_BUDGET_INVALID),
    ],
)
def test_request_parser_returns_stable_domain_errors(
    payload: dict[str, object],
    limit: int,
    expected_code: ErrorCode,
) -> None:
    with pytest.raises(MonasLensError) as error:
        parse_task_context_request(payload, max_tokens_limit=limit)

    assert error.value.code is expected_code
    assert "input" not in error.value.details


def test_evidence_relation_role_and_confidence_contracts_are_strict() -> None:
    with pytest.raises(ValidationError):
        RetrievalEvidence.model_validate(
            {
                "kind": "graph",
                "query": "Parser.run",
                "relation_kind": "not_a_relation",
                "distance": 1,
                "source_score": 0.9,
                "explanation": "invalid relation",
            }
        )
    with pytest.raises(ValidationError):
        RetrievalEvidence(
            kind=EvidenceKind.EXACT,
            query="Parser.run",
            relation_kind=RelationKind.CALLS,
            distance=1,
            source_score=1,
            explanation="invalid exact evidence",
        )

    candidate_payload = _candidate().model_dump(mode="json")
    candidate_payload["role_hints"] = ["not_a_role"]
    with pytest.raises(ValidationError):
        RetrievalCandidate.model_validate(candidate_payload)

    components = _confidence_components()
    with pytest.raises(ValidationError):
        ConfidenceResult(
            initial_confidence=0.9,
            final_confidence=0.9,
            threshold=0.8,
            status=ConfidenceStatus.DEGRADED,
            initial_components=components,
            final_components=components,
        )


def test_context_bundle_is_frozen_and_serializes_deterministically() -> None:
    candidate = _candidate()
    ranked = RankedCandidate(
        candidate=candidate,
        components=ScoreComponents(exact=1),
        score=1,
        explicit_focus=True,
        rank=1,
    )
    components = _confidence_components()
    confidence = ConfidenceResult(
        initial_confidence=0.9,
        final_confidence=0.9,
        status=ConfidenceStatus.ACCEPTED,
        initial_components=components,
        final_components=components,
    )
    content = "def run() -> None:\n    pass\n"
    estimate = TokenEstimate(
        estimator_name="fixture",
        estimator_version="1",
        is_exact=False,
        characters=len(content),
        utf8_bytes=len(content.encode()),
        estimated_tokens=10,
    )
    snippet = ContextSnippet(
        role=CandidateRole.PRIMARY,
        relative_path="src/parser.py",
        language="python",
        kind="function",
        start_line=10,
        end_line=11,
        content=content,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        provenance=(
            ContextSourceReference(
                entity_type=EntityType.SYMBOL,
                entity_id="symbol-1",
                relative_path="src/parser.py",
                start_line=10,
                end_line=11,
            ),
        ),
        rank_score=1,
        token_estimate=estimate,
    )
    budget = ContextBudget(
        requested_tokens=1_000,
        reserved_tokens=100,
        used_tokens=10,
        remaining_tokens=890,
        pre_budget_tokens=10,
        estimated_tokens_saved=0,
        reduction_ratio=0,
        role_usage=(
            RoleTokenUsage(
                role=CandidateRole.PRIMARY,
                estimated_tokens=10,
                item_count=1,
            ),
        ),
    )
    bundle = ContextBundle(
        repository_id="repository-1",
        resolution=TaskResolution(
            normalized_task="Fix Parser.run",
            action=TaskAction.CHANGE,
            qualified_identifiers=("Parser.run",),
            lexical_queries=("Parser.run",),
            explicit_focus_targets=("Parser.run",),
        ),
        primary_targets=(ranked,),
        confidence=confidence,
        internal_widening_occurred=False,
        snippets=(snippet,),
        budget=budget,
        validation_commands=(
            ValidationCommand(
                label="Run parser tests",
                arguments=("uv", "run", "pytest", "tests/test_parsing.py"),
            ),
        ),
    )

    assert bundle.model_dump_json() == bundle.model_dump_json()
    assert bundle.primary_targets[0].candidate.identity == (
        "repository-1",
        EntityType.SYMBOL,
        "symbol-1",
    )
    with pytest.raises(ValidationError):
        bundle.truncated = True


def test_validation_commands_reject_unsafe_contract_values() -> None:
    with pytest.raises(ValidationError):
        ValidationCommand(
            label="unsafe",
            arguments=("pytest\nwhoami",),
        )
    with pytest.raises(ValidationError):
        ValidationCommand(
            label="outside",
            arguments=("pytest",),
            working_directory="../outside",
        )


def test_retrieval_contract_schema_snapshot() -> None:
    models = sorted(
        retrieval_contracts.ContractModel.__subclasses__(),
        key=lambda model: model.__name__,
    )
    schemas = {model.__name__: model.model_json_schema() for model in models}
    payload = json.dumps(schemas, sort_keys=True, separators=(",", ":")).encode()

    assert hashlib.sha256(payload).hexdigest() == EXPECTED_SCHEMA_SHA256


def _candidate() -> RetrievalCandidate:
    return RetrievalCandidate(
        repository_id="repository-1",
        entity_type=EntityType.SYMBOL,
        entity_id="symbol-1",
        relative_path="src/parser.py",
        language="python",
        kind="function",
        name="run",
        qualified_name="Parser.run",
        start_line=10,
        end_line=11,
        role_hints=(CandidateRole.PRIMARY,),
        evidence=(
            RetrievalEvidence(
                kind=EvidenceKind.EXACT,
                query="Parser.run",
                source_score=1,
                explanation="Exact qualified-name match.",
            ),
        ),
        retrieval_ordinal=0,
    )


def _confidence_components() -> ConfidenceComponents:
    return ConfidenceComponents(
        primary_target_certainty=1,
        evidence_agreement=0.5,
        separation=1,
        role_coverage=0.5,
    )
