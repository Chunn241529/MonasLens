"""Tests for the Token Estimator and budget allocation."""

from __future__ import annotations

from monas_lens.retrieval.contracts import CandidateRole
from monas_lens.retrieval.token_estimator import (
    HeuristicTokenEstimator,
    allocate_budget,
    create_default_estimator,
    crop_text_to_budget,
)


def test_heuristic_estimator_properties() -> None:
    estimator = HeuristicTokenEstimator()

    assert estimator.name == "heuristic"
    assert estimator.version == "1.0.0"
    assert estimator.is_exact is False


def test_heuristic_estimator_empty_text() -> None:
    estimator = create_default_estimator()
    estimate = estimator.estimate("")

    assert estimate.characters == 0
    assert estimate.utf8_bytes == 0
    assert estimate.estimated_tokens == 0


def test_heuristic_estimator_ascii_code() -> None:
    estimator = create_default_estimator()
    text = "def hello() -> None:\n    print('hello')\n"
    estimate = estimator.estimate(text)

    assert estimate.characters == len(text)
    assert estimate.utf8_bytes == len(text.encode("utf-8"))
    assert estimate.estimated_tokens > 0
    assert estimate.estimator_name == "heuristic"


def test_heuristic_estimator_unicode() -> None:
    estimator = create_default_estimator()
    text = "パーサー モジュール"
    estimate = estimator.estimate(text)

    assert estimate.characters == len(text)
    assert estimate.utf8_bytes == len(text.encode("utf-8"))
    assert estimate.estimated_tokens > 0


def test_heuristic_estimator_multiline() -> None:
    estimator = create_default_estimator()
    text = "line1\nline2\nline3\n"
    estimate = estimator.estimate(text)

    # Should have at least 3 tokens (one per line)
    assert estimate.estimated_tokens >= 3


def test_heuristic_estimator_deterministic() -> None:
    estimator = create_default_estimator()
    text = "def run() -> str:\n    return 'hello'\n"

    first = estimator.estimate(text)
    second = estimator.estimate(text)

    assert first.model_dump_json() == second.model_dump_json()


def test_allocate_budget_basic() -> None:
    budget = allocate_budget(
        requested_tokens=1000,
        role_token_estimates=[
            (CandidateRole.PRIMARY, 100),
            (CandidateRole.DEPENDENCY, 50),
        ],
    )

    assert budget.requested_tokens == 1000
    assert budget.reserved_tokens > 0
    assert budget.used_tokens == 150
    assert budget.remaining_tokens > 0


def test_allocate_budget_respects_role_caps() -> None:
    budget = allocate_budget(
        requested_tokens=10000,
        max_primary_targets=2,
        role_token_estimates=[
            (CandidateRole.PRIMARY, 100),
            (CandidateRole.PRIMARY, 100),
            (CandidateRole.PRIMARY, 100),  # Should be omitted
        ],
    )

    # Only 2 primary targets should be included
    primary_usage = next((u for u in budget.role_usage if u.role == CandidateRole.PRIMARY), None)
    assert primary_usage is not None
    assert primary_usage.item_count == 2


def test_allocate_budget_enforces_token_limit() -> None:
    budget = allocate_budget(
        requested_tokens=500,
        role_token_estimates=[
            (CandidateRole.PRIMARY, 200),
            (CandidateRole.PRIMARY, 200),
            (CandidateRole.PRIMARY, 200),
        ],
    )

    # Should not exceed available tokens after reservation
    assert budget.used_tokens + budget.reserved_tokens <= budget.requested_tokens


def test_allocate_budget_accounting_consistency() -> None:
    budget = allocate_budget(
        requested_tokens=2000,
        role_token_estimates=[
            (CandidateRole.PRIMARY, 100),
            (CandidateRole.TEST, 50),
        ],
    )

    # Accounting: reserved + used + remaining = requested
    assert (
        budget.reserved_tokens + budget.used_tokens + budget.remaining_tokens
        == budget.requested_tokens
    )


def test_allocate_budget_empty_estimates() -> None:
    budget = allocate_budget(requested_tokens=1000)

    assert budget.used_tokens == 0
    assert budget.remaining_tokens > 0
    assert budget.role_usage == ()


def test_allocate_budget_deterministic() -> None:
    estimates = [
        (CandidateRole.PRIMARY, 100),
        (CandidateRole.DEPENDENCY, 50),
        (CandidateRole.TEST, 30),
    ]
    first = allocate_budget(requested_tokens=1000, role_token_estimates=estimates)
    second = allocate_budget(requested_tokens=1000, role_token_estimates=estimates)

    assert first.model_dump_json() == second.model_dump_json()


def test_crop_text_to_budget_no_crop_needed() -> None:
    text = "short text"
    cropped, was_cropped = crop_text_to_budget(text, max_tokens=1000)

    assert cropped == text
    assert was_cropped is False


def test_crop_text_to_budget_crops_from_start() -> None:
    lines = [f"line {i}" for i in range(100)]
    text = "\n".join(lines)
    cropped, was_cropped = crop_text_to_budget(text, max_tokens=50)

    assert was_cropped is True
    assert "omitted" in cropped


def test_crop_text_to_budget_preserves_match_line() -> None:
    lines = [f"line {i}" for i in range(100)]
    text = "\n".join(lines)
    cropped, was_cropped = crop_text_to_budget(text, max_tokens=50, match_line=50)

    assert was_cropped is True
    # The match line should be in the cropped text
    assert "line 49" in cropped  # match_line=50 is 0-indexed 49


def test_crop_text_to_budget_deterministic() -> None:
    lines = [f"line {i}" for i in range(50)]
    text = "\n".join(lines)

    first = crop_text_to_budget(text, max_tokens=30)
    second = crop_text_to_budget(text, max_tokens=30)

    assert first == second


def test_crop_text_to_budget_short_text_unchanged() -> None:
    text = "hello world"
    cropped, was_cropped = crop_text_to_budget(text, max_tokens=1000)

    assert cropped == text
    assert was_cropped is False
