"""Token estimation and budget allocation for context compilation.

Provides a pluggable TokenEstimator protocol and a deterministic,
dependency-free default heuristic estimator.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from monas_lens.retrieval.contracts import (
    CandidateRole,
    ContextBudget,
    RoleTokenUsage,
    TokenEstimate,
)

ESTIMATOR_NAME = "heuristic"
ESTIMATOR_VERSION = "1.0.0"

# Safety margin: reserve this fraction of the total budget
SAFETY_MARGIN_RATIO = 0.10

# Response envelope: reserve this many tokens for the response wrapper
RESPONSE_ENVELOPE_TOKENS = 256

# Default role caps from the roadmap
DEFAULT_MAX_PRIMARY_TARGETS = 3
DEFAULT_MAX_DEPENDENCY_SNIPPETS = 6
DEFAULT_MAX_CALLER_SNIPPETS = 6
DEFAULT_MAX_TEST_SNIPPETS = 4
DEFAULT_MAX_GIT_ENTRIES = 5


@runtime_checkable
class TokenEstimatorProtocol(Protocol):
    """Protocol for pluggable token estimators."""

    @property
    def name(self) -> str:
        """Estimator name."""
        ...

    @property
    def version(self) -> str:
        """Estimator version."""
        ...

    @property
    def is_exact(self) -> bool:
        """Whether this estimator provides exact token counts."""
        ...

    def estimate(self, text: str) -> TokenEstimate:
        """Estimate token usage for the given text."""
        ...


class HeuristicTokenEstimator:
    """Deterministic, dependency-free heuristic token estimator.

    Uses a simple heuristic: 1 token ≈ 4 characters for code,
    with adjustments for whitespace and line structure.
    Reports is_exact=False.
    """

    @property
    def name(self) -> str:
        return ESTIMATOR_NAME

    @property
    def version(self) -> str:
        return ESTIMATOR_VERSION

    @property
    def is_exact(self) -> bool:
        return False

    def estimate(self, text: str) -> TokenEstimate:
        """Estimate token usage using a deterministic heuristic.

        Heuristic: ~1 token per 4 characters, with a minimum of 1 token
        per line. This is a reasonable approximation for code and prose.
        """
        characters = len(text)
        utf8_bytes = len(text.encode("utf-8"))

        if characters == 0:
            return TokenEstimate(
                estimator_name=self.name,
                estimator_version=self.version,
                is_exact=self.is_exact,
                characters=0,
                utf8_bytes=0,
                estimated_tokens=0,
            )

        # Count lines for minimum token estimation
        line_count = text.count("\n") + 1

        # Base estimate: ~1 token per 4 characters
        char_estimate = max(characters // 4, 1)

        # Use the maximum of character-based and line-based estimates
        estimated_tokens = max(char_estimate, line_count)

        return TokenEstimate(
            estimator_name=self.name,
            estimator_version=self.version,
            is_exact=self.is_exact,
            characters=characters,
            utf8_bytes=utf8_bytes,
            estimated_tokens=estimated_tokens,
        )


def create_default_estimator() -> HeuristicTokenEstimator:
    """Create the default heuristic token estimator."""
    return HeuristicTokenEstimator()


@dataclass(frozen=True, slots=True)
class BudgetAllocation:
    """Result of budget allocation across roles."""

    budget: ContextBudget
    role_usage: tuple[RoleTokenUsage, ...]
    primary_tokens: int
    dependency_tokens: int
    caller_tokens: int
    test_tokens: int
    git_tokens: int
    omitted_items: int
    cropped: bool


def allocate_budget(
    requested_tokens: int,
    *,
    estimator: TokenEstimatorProtocol | None = None,
    safety_margin_ratio: float = SAFETY_MARGIN_RATIO,
    response_envelope_tokens: int = RESPONSE_ENVELOPE_TOKENS,
    max_primary_targets: int = DEFAULT_MAX_PRIMARY_TARGETS,
    max_dependency_snippets: int = DEFAULT_MAX_DEPENDENCY_SNIPPETS,
    max_caller_snippets: int = DEFAULT_MAX_CALLER_SNIPPETS,
    max_test_snippets: int = DEFAULT_MAX_TEST_SNIPPETS,
    max_git_entries: int = DEFAULT_MAX_GIT_ENTRIES,
    role_token_estimates: Sequence[tuple[CandidateRole, int]] | None = None,
) -> ContextBudget:
    """Allocate token budget across roles.

    Args:
        requested_tokens: Total requested token budget.
        estimator: Token estimator to use (default: heuristic).
        safety_margin_ratio: Fraction of budget to reserve as safety margin.
        response_envelope_tokens: Tokens reserved for response wrapper.
        max_primary_targets: Maximum primary target snippets.
        max_dependency_snippets: Maximum dependency snippets.
        max_caller_snippets: Maximum caller snippets.
        max_test_snippets: Maximum test snippets.
        max_git_entries: Maximum git diff entries.
        role_token_estimates: Pre-computed (role, token_count) pairs.

    Returns:
        ContextBudget with allocation details.
    """
    if estimator is None:
        estimator = create_default_estimator()

    # Calculate reserved tokens
    safety_margin = int(requested_tokens * safety_margin_ratio)
    reserved = min(safety_margin + response_envelope_tokens, requested_tokens)

    # Available tokens for content
    available = requested_tokens - reserved

    # Apply role caps
    role_caps = {
        CandidateRole.PRIMARY: max_primary_targets,
        CandidateRole.DEPENDENCY: max_dependency_snippets,
        CandidateRole.CALLER: max_caller_snippets,
        CandidateRole.TEST: max_test_snippets,
        CandidateRole.GIT_DIFF: max_git_entries,
    }

    # Allocate tokens per role
    role_usage: list[RoleTokenUsage] = []
    used_tokens = 0
    omitted_items = 0
    cropped = False

    if role_token_estimates is not None:
        # Group by role and apply caps
        role_counts: dict[CandidateRole, list[int]] = {}
        for role, token_count in role_token_estimates:
            if role not in role_counts:
                role_counts[role] = []
            role_counts[role].append(token_count)

        for role in (
            CandidateRole.PRIMARY,
            CandidateRole.INTERFACE,
            CandidateRole.SCHEMA,
            CandidateRole.CONFIGURATION,
            CandidateRole.DEPENDENCY,
            CandidateRole.CALLER,
            CandidateRole.TEST,
            CandidateRole.GIT_DIFF,
        ):
            if role not in role_counts:
                continue

            items = role_counts[role]
            cap = role_caps.get(role, len(items))

            # Sort by token count (ascending) to fit more items
            items_sorted = sorted(items)

            role_tokens = 0
            items_used = 0
            for token_count in items_sorted:
                if items_used >= cap:
                    omitted_items += len(items_sorted) - items_used
                    break
                if used_tokens + role_tokens + token_count > available:
                    omitted_items += len(items_sorted) - items_used
                    cropped = True
                    break
                role_tokens += token_count
                items_used += 1

            if role_tokens > 0:
                role_usage.append(
                    RoleTokenUsage(
                        role=role,
                        estimated_tokens=role_tokens,
                        item_count=items_used,
                    )
                )
                used_tokens += role_tokens

    # Calculate remaining
    remaining = available - used_tokens

    # Calculate pre-budget tokens (total if no budget limit)
    pre_budget_tokens = sum(token_count for _, token_count in (role_token_estimates or []))

    # Calculate savings
    estimated_tokens_saved = max(pre_budget_tokens - used_tokens, 0)

    # Calculate reduction ratio
    reduction_ratio = estimated_tokens_saved / pre_budget_tokens if pre_budget_tokens > 0 else 0.0

    return ContextBudget(
        requested_tokens=requested_tokens,
        reserved_tokens=reserved,
        used_tokens=used_tokens,
        remaining_tokens=remaining,
        pre_budget_tokens=pre_budget_tokens,
        estimated_tokens_saved=estimated_tokens_saved,
        reduction_ratio=reduction_ratio,
        role_usage=tuple(role_usage),
        omitted_items=omitted_items,
        cropped=cropped,
    )


def crop_text_to_budget(
    text: str,
    *,
    max_tokens: int,
    estimator: TokenEstimatorProtocol | None = None,
    match_line: int | None = None,
) -> tuple[str, bool]:
    """Crop text to fit within a token budget.

    Crops at line boundaries around the matched line when possible.
    Returns (cropped_text, was_cropped).
    """
    if estimator is None:
        estimator = create_default_estimator()

    estimate = estimator.estimate(text)
    if estimate.estimated_tokens <= max_tokens:
        return text, False

    lines = text.split("\n")
    if not lines:
        return text, False

    # If we have a match line, crop around it
    if match_line is not None and 1 <= match_line <= len(lines):
        # Try to keep context around the match
        center = match_line - 1  # 0-indexed
        start = max(0, center - 2)
        end = min(len(lines), center + 3)

        # Expand until we hit the budget
        while start > 0 or end < len(lines):
            candidate = "\n".join(lines[start:end])
            candidate_estimate = estimator.estimate(candidate)
            if candidate_estimate.estimated_tokens <= max_tokens:
                # Try to expand
                expanded = False
                if start > 0:
                    new_start = start - 1
                    new_candidate = "\n".join(lines[new_start:end])
                    new_estimate = estimator.estimate(new_candidate)
                    if new_estimate.estimated_tokens <= max_tokens:
                        start = new_start
                        expanded = True
                if end < len(lines):
                    new_end = end + 1
                    new_candidate = "\n".join(lines[start:new_end])
                    new_estimate = estimator.estimate(new_candidate)
                    if new_estimate.estimated_tokens <= max_tokens:
                        end = new_end
                        expanded = True
                if not expanded:
                    break
            else:
                # Shrink
                if end - start <= 1:
                    break
                if start < center:
                    start += 1
                else:
                    end -= 1

        cropped_text = "\n".join(lines[start:end])
        if start > 0:
            cropped_text = f"# ... ({start} lines omitted) ...\n{cropped_text}"
        if end < len(lines):
            cropped_text = f"{cropped_text}\n# ... ({len(lines) - end} lines omitted) ..."
        return cropped_text, True

    # No match line - crop from start
    result_lines: list[str] = []
    current_tokens = 0
    for line in lines:
        line_estimate = estimator.estimate(line + "\n")
        if current_tokens + line_estimate.estimated_tokens > max_tokens:
            break
        result_lines.append(line)
        current_tokens += line_estimate.estimated_tokens

    if len(result_lines) < len(lines):
        cropped_text = "\n".join(result_lines)
        cropped_text = f"{cropped_text}\n# ... ({len(lines) - len(result_lines)} lines omitted) ..."
        return cropped_text, True

    return text, False
