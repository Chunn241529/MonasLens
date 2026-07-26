"""Deterministic task resolver for context compilation.

Pure, deterministic parsing of task text into retrieval queries.
No filesystem, database, network, or LLM access.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from monas_lens.retrieval.contracts import (
    RetrievalDiagnostic,
    TaskAction,
    TaskResolution,
)

MAX_LEXICAL_QUERIES = 6
MAX_EXTRACTED_IDENTIFIERS = 20
MAX_QUOTED_PHRASES = 5
MAX_PATH_CANDIDATES = 10

# Qualified identifiers: Word.Word[.Word...] (dotted, starts with letter/underscore)
_QUALIFIED_IDENTIFIER = re.compile(
    r"(?<![.\w])([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)(?![.\w])"
)

# Single identifiers: standalone words that look like code identifiers
_IDENTIFIER = re.compile(r"(?<![.\w/\\])([A-Za-z_][A-Za-z0-9_]{1,63})(?![.\w/\\])")

# Quoted phrases: "text" or 'text'
_QUOTED_PHRASE = re.compile(r"""(?:"([^"]{1,200})"|'([^']{1,200})')""")

# Relative paths: has path separator and extension
_WINDOWS_PATH = re.compile(
    r"(?<![.\w])([A-Za-z_][A-Za-z0-9_]*(?:[/\\][A-Za-z0-9_]+)*[/\\][A-Za-z0-9_]+\.[A-Za-z]{1,10})(?![.\w])"
)
_POSIX_PATH = re.compile(r"(?<![.\w])([A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*\.[A-Za-z]{1,10})(?![.\w])")

# Action keywords (case-insensitive)
# Order within each tuple: more specific patterns first
_ACTION_PATTERNS: dict[TaskAction, tuple[re.Pattern[str], ...]] = {
    TaskAction.DIAGNOSE: (
        re.compile(r"\b(?:diagnose|debug|investigate|troubleshoot)\b", re.I),
        re.compile(
            r"\b(?:find\s+(?:the\s+)?(?:bug|error|issue|problem|crash|failure|root\s+cause))\b",
            re.I,
        ),
        re.compile(
            r"\b(?:why\s+(?:is|does|did|does|are|was|were|can't|won't|doesn't|isn't))\b", re.I
        ),
        re.compile(
            r"\b(?:what(?:'s|\s+is)\s+wrong|broken|failing|doesn't\s+work|not\s+working)\b", re.I
        ),
        re.compile(r"\b(?:traceback|stack\s+trace|segfault)\b", re.I),
    ),
    TaskAction.CHANGE: (
        re.compile(r"\b(?:fix|patch|repair|correct|resolve)\b", re.I),
        re.compile(r"\b(?:add|implement|create|write|introduce|insert)\b", re.I),
        re.compile(r"\b(?:remove|delete|drop|strip|eliminate)\b", re.I),
        re.compile(r"\b(?:update|modify|change|edit|adjust)\b", re.I),
    ),
    TaskAction.REFACTOR: (
        re.compile(
            r"\b(?:refactor|restructure|reorganize|rename|move|extract|inline|simplify|clean\s*up|improve)\b",
            re.I,
        ),
    ),
    TaskAction.TEST: (
        re.compile(
            r"\b(?:add|write|create|implement)\s+(?:a\s+)?(?:test|tests|spec|specs)\b", re.I
        ),
        re.compile(r"\b(?:test|spec|coverage|assert|verify|validate)\b", re.I),
        re.compile(r"\b(?:check|ensure)\s+(?:that|the|this|it)\b", re.I),
    ),
    TaskAction.EXPLAIN: (
        re.compile(r"\b(?:explain|describe|document|summarize|overview)\b", re.I),
        re.compile(r"\b(?:how\s+does|what\s+does|walk\s+me\s+through)\b", re.I),
    ),
}

# Words to skip when building lexical queries
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "must",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "because",
        "but",
        "and",
        "or",
        "if",
        "while",
        "about",
        "up",
        "down",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "him",
        "his",
        "she",
        "her",
        "they",
        "them",
        "their",
        "which",
        "what",
        "who",
        "whom",
        "get",
        "set",
        "let",
        "make",
        "use",
        "using",
        "used",
        "also",
        "need",
        "want",
        "like",
        "please",
        "help",
        "try",
        "something",
        "anything",
        "everything",
        "code",
        "file",
        "function",
        "method",
        "class",
        "module",
        "part",
        "way",
        "thing",
    }
)


def resolve_task(
    task: str,
    *,
    focus_targets: Sequence[str] = (),
) -> TaskResolution:
    """Parse task text into a deterministic retrieval resolution.

    Pure and deterministic: same input always produces byte-equivalent output.
    No filesystem, database, network, or LLM access.
    Preserves original identifier casing.
    """
    normalized = task.strip()
    diagnostics: list[RetrievalDiagnostic] = []

    # Extract components
    qualified_identifiers = _extract_qualified_identifiers(normalized)
    identifiers = _extract_identifiers(normalized, qualified_identifiers)
    path_candidates = _extract_paths(normalized)
    quoted_phrases = _extract_quoted_phrases(normalized)
    action = _classify_action(normalized)
    lexical_queries = _build_lexical_queries(
        normalized,
        qualified_identifiers,
        identifiers,
        path_candidates,
        quoted_phrases,
    )

    # Separate explicit focus from inferred
    explicit_focus = _resolve_focus_targets(focus_targets, diagnostics)

    return TaskResolution(
        normalized_task=normalized,
        action=action,
        qualified_identifiers=tuple(qualified_identifiers),
        identifiers=tuple(identifiers),
        path_candidates=tuple(path_candidates),
        quoted_phrases=tuple(quoted_phrases),
        lexical_queries=tuple(lexical_queries),
        explicit_focus_targets=tuple(explicit_focus),
        diagnostics=tuple(diagnostics),
    )


def _extract_qualified_identifiers(text: str) -> list[str]:
    """Extract dotted qualified identifiers like Module.Class.method."""
    seen: set[str] = set()
    result: list[str] = []
    for match in _QUALIFIED_IDENTIFIER.finditer(text):
        value = match.group(1)
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result[:MAX_EXTRACTED_IDENTIFIERS]


def _extract_identifiers(
    text: str,
    qualified_identifiers: Sequence[str],
) -> list[str]:
    """Extract single identifiers, excluding parts of qualified identifiers."""
    # Collect all parts of qualified identifiers to exclude
    qualified_parts: set[str] = set()
    for qi in qualified_identifiers:
        for part in qi.split("."):
            qualified_parts.add(part)

    seen: set[str] = set()
    result: list[str] = []
    for match in _IDENTIFIER.finditer(text):
        value = match.group(1)
        # Skip if it's a part of a qualified identifier we already extracted
        if value in qualified_parts:
            continue
        # Skip common English words that happen to match identifier pattern
        if value.lower() in _STOP_WORDS:
            continue
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result[:MAX_EXTRACTED_IDENTIFIERS]


def _extract_paths(text: str) -> list[str]:
    """Extract relative file paths from task text."""
    seen: set[str] = set()
    result: list[str] = []

    # Try Windows-style paths first (backslash or forward slash)
    for match in _WINDOWS_PATH.finditer(text):
        value = match.group(1).replace("\\", "/")
        if value not in seen:
            seen.add(value)
            result.append(value)

    # Try POSIX-style paths
    for match in _POSIX_PATH.finditer(text):
        value = match.group(1)
        if value not in seen:
            seen.add(value)
            result.append(value)

    return result[:MAX_PATH_CANDIDATES]


def _extract_quoted_phrases(text: str) -> list[str]:
    """Extract quoted phrases from task text."""
    seen: set[str] = set()
    result: list[str] = []
    for match in _QUOTED_PHRASE.finditer(text):
        # Group 1 is double-quoted, group 2 is single-quoted
        value = match.group(1) if match.group(1) is not None else match.group(2)
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result[:MAX_QUOTED_PHRASES]


def _classify_action(text: str) -> TaskAction:
    """Classify the requested action conservatively.

    Order matters: TEST and REFACTOR are checked before CHANGE because
    their keywords are more specific (e.g., "Add tests" is TEST, not CHANGE).
    """
    # Check in priority order: specific actions first
    for action in (
        TaskAction.EXPLAIN,
        TaskAction.REFACTOR,
        TaskAction.TEST,
        TaskAction.DIAGNOSE,
        TaskAction.CHANGE,
    ):
        patterns = _ACTION_PATTERNS[action]
        for pattern in patterns:
            if pattern.search(text):
                return action
    return TaskAction.UNKNOWN


def _build_lexical_queries(
    text: str,
    qualified_identifiers: Sequence[str],
    identifiers: Sequence[str],
    path_candidates: Sequence[str],
    quoted_phrases: Sequence[str],
) -> list[str]:
    """Build bounded lexical queries from extracted components."""
    queries: list[str] = []
    seen: set[str] = set()

    # Qualified identifiers are high-signal queries
    for qi in qualified_identifiers:
        if qi not in seen:
            seen.add(qi)
            queries.append(qi)

    # Quoted phrases are exact-match queries
    for phrase in quoted_phrases:
        if phrase not in seen and len(phrase) <= 200:
            seen.add(phrase)
            queries.append(phrase)

    # Add meaningful identifiers as queries
    for ident in identifiers:
        if ident not in seen and len(ident) >= 3:
            seen.add(ident)
            queries.append(ident)

    return queries[:MAX_LEXICAL_QUERIES]


def _resolve_focus_targets(
    focus_targets: Sequence[str],
    diagnostics: list[RetrievalDiagnostic],
) -> list[str]:
    """Resolve and validate explicit focus targets."""
    seen: set[str] = set()
    result: list[str] = []
    for target in focus_targets:
        normalized = target.strip()
        if not normalized:
            continue
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result
