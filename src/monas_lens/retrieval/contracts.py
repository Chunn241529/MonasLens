"""Immutable contracts for Phase 4 context compilation."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.graph.contracts import RelationKind

CONTEXT_SCHEMA_VERSION = "1.1"
MIN_CONTEXT_TOKENS = 256
MAX_CONTEXT_TOKENS = 100_000
MAX_TASK_CHARS = 4_000
MAX_FOCUS_TARGETS = 10
MAX_FOCUS_TARGET_CHARS = 500

Score = Annotated[float, Field(ge=0, le=1)]
ShortText = Annotated[str, Field(min_length=1, max_length=500)]
Identifier = Annotated[str, Field(min_length=1, max_length=512)]
RelativePath = Annotated[str, Field(min_length=1, max_length=4_096)]


class TaskAction(StrEnum):
    DIAGNOSE = "diagnose"
    CHANGE = "change"
    REFACTOR = "refactor"
    TEST = "test"
    EXPLAIN = "explain"
    UNKNOWN = "unknown"


class CandidateRole(StrEnum):
    PRIMARY = "primary"
    CALLER = "caller"
    DEPENDENCY = "dependency"
    INTERFACE = "interface"
    IMPLEMENTATION = "implementation"
    SCHEMA = "schema"
    CONFIGURATION = "configuration"
    TEST = "test"
    GIT_DIFF = "git_diff"


class EvidenceKind(StrEnum):
    EXACT = "exact"
    LEXICAL = "lexical"
    GRAPH = "graph"
    TEST = "test"


class EntityType(StrEnum):
    FILE = "file"
    SYMBOL = "symbol"
    CHUNK = "chunk"
    FACT = "fact"
    GIT_DIFF = "git_diff"


class ConfidenceStatus(StrEnum):
    ACCEPTED = "accepted"
    DEGRADED = "degraded"


class FreshnessStatus(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"


class NextActionKind(StrEnum):
    NONE = "none"
    EXPAND = "expand"
    REFRESH_INDEX = "refresh_index"
    MANUAL_FALLBACK = "manual_fallback"


class NextActionReason(StrEnum):
    ACCEPTED = "accepted"
    MISSING_PRIMARY = "missing_primary"
    AMBIGUOUS_PRIMARY = "ambiguous_primary"
    MISSING_ROLES = "missing_roles"
    STALE_INDEX = "stale_index"
    TRUNCATED = "truncated"
    RETRIEVAL_UNAVAILABLE = "retrieval_unavailable"


class ConfidenceReason(StrEnum):
    UNIQUE_TARGET = "unique_target"
    EXPLICIT_FOCUS = "explicit_focus"
    EVIDENCE_AGREEMENT = "evidence_agreement"
    LOW_SEPARATION = "low_separation"
    AMBIGUOUS_TARGET = "ambiguous_target"
    MISSING_PRIMARY = "missing_primary"
    MISSING_ROLES = "missing_roles"
    RETRIEVAL_DEGRADED = "retrieval_degraded"
    WIDENED = "widened"


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class RetrievalDiagnosticCode(StrEnum):
    INPUT_DISCARDED = "input_discarded"
    TARGET_UNSUPPORTED = "target_unsupported"
    SEARCH_UNAVAILABLE = "search_unavailable"
    GRAPH_UNAVAILABLE = "graph_unavailable"
    GIT_UNAVAILABLE = "git_unavailable"
    GIT_TRUNCATED = "git_truncated"
    INDEX_STALE = "index_stale"
    ROLE_MISSING = "role_missing"
    BUDGET_OMITTED = "budget_omitted"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TaskContextRequest(ContractModel):
    task: Annotated[str, Field(min_length=1, max_length=MAX_TASK_CHARS)]
    repository: str | Path | None = None
    focus_targets: Annotated[tuple[str, ...], Field(max_length=MAX_FOCUS_TARGETS)] = ()
    max_tokens: Annotated[
        int | None,
        Field(ge=MIN_CONTEXT_TOKENS, le=MAX_CONTEXT_TOKENS),
    ] = None
    include_git_diff: bool = True

    @field_validator("task")
    @classmethod
    def validate_task(cls, value: str) -> str:
        normalized = value.strip()
        if not any(character.isalnum() for character in normalized):
            raise ValueError("Task must contain at least one letter or number.")
        return normalized

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, value: str | Path | None) -> str | Path | None:
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                raise ValueError("Repository must not be empty.")
            return normalized
        return value

    @field_validator("focus_targets", mode="before")
    @classmethod
    def normalize_focus_targets(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            raw_targets: tuple[object, ...] = (value,)
        elif isinstance(value, (list, tuple)):
            raw_targets = tuple(cast(list[object] | tuple[object, ...], value))
        else:
            raise ValueError("Focus targets must be a string, list, or tuple.")
        selected: list[str] = []
        for raw_target in raw_targets:
            if not isinstance(raw_target, str):
                raise ValueError("Focus targets must be strings.")
            target = raw_target.strip()
            if not target or not any(character.isalnum() for character in target):
                raise ValueError("Focus targets must contain a letter or number.")
            if len(target) > MAX_FOCUS_TARGET_CHARS:
                raise ValueError(
                    f"Focus targets must not exceed {MAX_FOCUS_TARGET_CHARS} characters."
                )
            if target not in selected:
                selected.append(target)
        if len(selected) > MAX_FOCUS_TARGETS:
            raise ValueError(f"At most {MAX_FOCUS_TARGETS} focus targets are allowed.")
        return tuple(selected)


class RetrievalDiagnostic(ContractModel):
    code: RetrievalDiagnosticCode
    severity: DiagnosticSeverity
    message: ShortText
    role: CandidateRole | None = None


class TaskResolution(ContractModel):
    normalized_task: Annotated[str, Field(min_length=1, max_length=MAX_TASK_CHARS)]
    action: TaskAction = TaskAction.UNKNOWN
    qualified_identifiers: tuple[Identifier, ...] = ()
    identifiers: tuple[Identifier, ...] = ()
    path_candidates: tuple[RelativePath, ...] = ()
    quoted_phrases: tuple[ShortText, ...] = ()
    lexical_queries: tuple[ShortText, ...] = ()
    explicit_focus_targets: tuple[Identifier, ...] = ()
    diagnostics: tuple[RetrievalDiagnostic, ...] = ()


class RetrievalEvidence(ContractModel):
    kind: EvidenceKind
    query: ShortText
    seed_id: Identifier | None = None
    relation_kind: RelationKind | None = None
    distance: Annotated[int | None, Field(ge=1, le=2)] = None
    source_score: Score
    explanation: ShortText

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> Self:
        relationship_evidence = self.kind in {EvidenceKind.GRAPH, EvidenceKind.TEST}
        if relationship_evidence and (self.relation_kind is None or self.distance is None):
            raise ValueError("Graph and test evidence require a relation and distance.")
        if not relationship_evidence and (
            self.relation_kind is not None or self.distance is not None
        ):
            raise ValueError("Exact and lexical evidence cannot contain graph fields.")
        if self.kind is EvidenceKind.TEST and self.relation_kind is not RelationKind.TESTED_BY:
            raise ValueError("Test evidence requires the tested_by relation.")
        if self.kind is EvidenceKind.GRAPH and self.relation_kind is RelationKind.TESTED_BY:
            raise ValueError("The tested_by relation must use test evidence.")
        return self


class RetrievalCandidate(ContractModel):
    repository_id: Identifier
    entity_type: EntityType
    entity_id: Identifier
    relative_path: RelativePath
    language: Annotated[str, Field(min_length=1, max_length=32)]
    kind: Annotated[str, Field(min_length=1, max_length=64)]
    name: Annotated[str | None, Field(max_length=255)] = None
    qualified_name: Annotated[str | None, Field(max_length=2_000)] = None
    start_line: Annotated[int, Field(ge=1)]
    end_line: Annotated[int, Field(ge=1)]
    role_hints: Annotated[tuple[CandidateRole, ...], Field(min_length=1, max_length=8)]
    evidence: Annotated[tuple[RetrievalEvidence, ...], Field(min_length=1, max_length=32)]
    retrieval_ordinal: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        _validate_line_range(self.start_line, self.end_line)
        return self

    @property
    def identity(self) -> tuple[str, EntityType, str]:
        return (self.repository_id, self.entity_type, self.entity_id)


class ScoreComponents(ContractModel):
    exact: Score = 0
    lexical: Score = 0
    graph: Score = 0
    test: Score = 0
    semantic: Score = 0

    @field_validator("semantic")
    @classmethod
    def semantic_is_disabled(cls, value: float) -> float:
        if value != 0:
            raise ValueError("Semantic evidence is disabled in Phase 4.")
        return value


class RankedCandidate(ContractModel):
    candidate: RetrievalCandidate
    components: ScoreComponents
    score: Score
    explicit_focus: bool = False
    rank: Annotated[int, Field(ge=1)]


class ConfidenceComponents(ContractModel):
    primary_target_certainty: Score
    evidence_agreement: Score
    separation: Score
    role_coverage: Score


class ConfidenceResult(ContractModel):
    initial_confidence: Score
    final_confidence: Score
    threshold: Score = 0.80
    status: ConfidenceStatus
    expansion_count: Annotated[int, Field(ge=0, le=1)] = 0
    initial_components: ConfidenceComponents
    final_components: ConfidenceComponents
    reason_codes: tuple[ConfidenceReason, ...] = ()
    missing_roles: tuple[CandidateRole, ...] = ()

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        accepted = self.final_confidence >= self.threshold
        if accepted != (self.status is ConfidenceStatus.ACCEPTED):
            raise ValueError("Confidence status must match the configured threshold.")
        if self.expansion_count == 0 and (
            self.initial_confidence != self.final_confidence
            or self.initial_components != self.final_components
        ):
            raise ValueError("Confidence cannot change without an expansion.")
        return self


class TokenEstimate(ContractModel):
    estimator_name: ShortText
    estimator_version: ShortText
    is_exact: bool
    characters: Annotated[int, Field(ge=0)]
    utf8_bytes: Annotated[int, Field(ge=0)]
    estimated_tokens: Annotated[int, Field(ge=0)]


class RoleTokenUsage(ContractModel):
    role: CandidateRole
    estimated_tokens: Annotated[int, Field(ge=0)]
    item_count: Annotated[int, Field(ge=0)]


class ContextBudget(ContractModel):
    requested_tokens: Annotated[int, Field(ge=MIN_CONTEXT_TOKENS, le=MAX_CONTEXT_TOKENS)]
    reserved_tokens: Annotated[int, Field(ge=0)]
    used_tokens: Annotated[int, Field(ge=0)]
    remaining_tokens: Annotated[int, Field(ge=0)]
    pre_budget_tokens: Annotated[int, Field(ge=0)]
    estimated_tokens_saved: Annotated[int, Field(ge=0)]
    reduction_ratio: Score
    role_usage: tuple[RoleTokenUsage, ...] = ()
    omitted_items: Annotated[int, Field(ge=0)] = 0
    cropped: bool = False

    @model_validator(mode="after")
    def validate_accounting(self) -> Self:
        if self.reserved_tokens + self.used_tokens + self.remaining_tokens != self.requested_tokens:
            raise ValueError("Reserved, used, and remaining tokens must equal the request budget.")
        expected_saved = max(self.pre_budget_tokens - self.used_tokens, 0)
        if self.estimated_tokens_saved != expected_saved:
            raise ValueError("Estimated token savings do not match pre-budget and used tokens.")
        if sum(item.estimated_tokens for item in self.role_usage) > self.used_tokens:
            raise ValueError("Per-role usage cannot exceed total used tokens.")
        roles = [item.role for item in self.role_usage]
        if len(roles) != len(set(roles)):
            raise ValueError("Per-role token usage must contain unique roles.")
        return self


class ContextSourceReference(ContractModel):
    entity_type: EntityType
    entity_id: Identifier
    relative_path: RelativePath
    start_line: Annotated[int, Field(ge=1)]
    end_line: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        _validate_line_range(self.start_line, self.end_line)
        return self


class ContextSnippet(ContractModel):
    role: CandidateRole
    roles: tuple[CandidateRole, ...] = ()
    evidence: tuple[RetrievalEvidence, ...] = ()
    relative_path: RelativePath
    language: Annotated[str, Field(min_length=1, max_length=32)]
    kind: Annotated[str, Field(min_length=1, max_length=64)]
    start_line: Annotated[int, Field(ge=1)]
    end_line: Annotated[int, Field(ge=1)]
    content: Annotated[str, Field(min_length=1)]
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    provenance: Annotated[tuple[ContextSourceReference, ...], Field(min_length=1)]
    rank_score: Score
    token_estimate: TokenEstimate
    cropped: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        _validate_line_range(self.start_line, self.end_line)
        roles = self.roles or (self.role,)
        if self.role not in roles:
            raise ValueError("Primary snippet role must be present in roles.")
        object.__setattr__(self, "roles", tuple(dict.fromkeys(roles)))
        return self


class NextAction(ContractModel):
    kind: NextActionKind = NextActionKind.NONE
    reason: NextActionReason = NextActionReason.ACCEPTED


class ValidationCommand(ContractModel):
    label: ShortText
    arguments: Annotated[tuple[ShortText, ...], Field(min_length=1, max_length=64)]
    working_directory: str = "."

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any("\x00" in argument or "\n" in argument or "\r" in argument for argument in value):
            raise ValueError("Command arguments cannot contain control separators.")
        return value

    @field_validator("working_directory")
    @classmethod
    def validate_working_directory(cls, value: str) -> str:
        normalized = value.strip().replace("\\", "/")
        path = PurePosixPath(normalized)
        windows_absolute = len(normalized) >= 2 and normalized[1] == ":"
        if not normalized or path.is_absolute() or windows_absolute or ".." in path.parts:
            raise ValueError("Working directory must be repository-relative.")
        return normalized


class ContextBundle(ContractModel):
    schema_version: Literal["1.1"] = CONTEXT_SCHEMA_VERSION
    repository_id: Identifier
    resolution: TaskResolution
    primary_targets: Annotated[tuple[RankedCandidate, ...], Field(max_length=10)] = ()
    confidence: ConfidenceResult
    internal_widening_occurred: bool
    snippets: tuple[ContextSnippet, ...]
    budget: ContextBudget
    diagnostics: tuple[RetrievalDiagnostic, ...] = ()
    freshness: FreshnessStatus = FreshnessStatus.UNKNOWN
    freshness_changed_paths: tuple[RelativePath, ...] = ()
    validation_commands: tuple[ValidationCommand, ...] = ()
    truncated: bool = False
    next_action: NextAction = NextAction()
    recommended_focus_target: str | None = None
    recommended_missing_roles: tuple[CandidateRole, ...] = ()

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        widened = self.confidence.expansion_count > 0
        if self.internal_widening_occurred != widened:
            raise ValueError("Bundle widening state must match confidence expansion count.")
        if any(
            target.candidate.repository_id != self.repository_id for target in self.primary_targets
        ):
            raise ValueError("Primary targets must belong to the bundle repository.")
        if sum(snippet.token_estimate.estimated_tokens for snippet in self.snippets) > (
            self.budget.used_tokens
        ):
            raise ValueError("Snippet token estimates cannot exceed used budget tokens.")
        if self.freshness is FreshnessStatus.STALE and not self.freshness_changed_paths:
            raise ValueError("Stale freshness must identify at least one changed path.")
        if self.freshness is not FreshnessStatus.STALE and self.freshness_changed_paths:
            raise ValueError("Only stale freshness can include changed paths.")
        return self


def parse_task_context_request(
    value: TaskContextRequest | Mapping[str, Any],
    *,
    max_tokens_limit: int,
) -> TaskContextRequest:
    """Validate an external request and apply the configured token default."""
    try:
        request = (
            value
            if isinstance(value, TaskContextRequest)
            else TaskContextRequest.model_validate(value)
        )
    except ValidationError as exc:
        fields = sorted(
            {str(error["loc"][0]) for error in exc.errors(include_input=False) if error["loc"]}
        )
        code = (
            ErrorCode.CONTEXT_BUDGET_INVALID
            if fields == ["max_tokens"]
            else ErrorCode.CONTEXT_REQUEST_INVALID
        )
        raise MonasLensError(
            code,
            "The context request is invalid.",
            details={"fields": fields},
        ) from exc

    if not MIN_CONTEXT_TOKENS <= max_tokens_limit <= MAX_CONTEXT_TOKENS:
        raise ValueError("Configured context token limit is outside supported bounds.")
    selected_tokens = request.max_tokens or max_tokens_limit
    if selected_tokens > max_tokens_limit:
        raise MonasLensError(
            ErrorCode.CONTEXT_BUDGET_INVALID,
            "The requested context budget exceeds the configured limit.",
            details={"max_tokens": max_tokens_limit},
        )
    return request.model_copy(update={"max_tokens": selected_tokens})


def _validate_line_range(start_line: int, end_line: int) -> None:
    if end_line < start_line:
        raise ValueError("End line must not precede start line.")
