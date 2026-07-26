"""Deterministic compression for bounded command output."""

from __future__ import annotations

import re
from collections.abc import Sequence

from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.mcp.contracts import CommandKind, CommandOutputSummary

_MAX_INPUT_CHARS = 200_000
_MIN_OUTPUT_CHARS = 256
_MAX_OUTPUT_CHARS = 50_000
_PRIORITY_LINE = re.compile(
    r"(?:\berror\b|\bfailed?\b|\bfailure\b|\bexception\b|traceback|\bwarning\b|"
    r"\bsummary\b|\bpassed\b|\bskipped\b|\bexpected\b|\bactual\b|^\s*[EFW]\s+)",
    re.IGNORECASE,
)


def compress_command_output(
    output: str,
    *,
    command_kind: CommandKind | str = CommandKind.AUTO,
    max_output_chars: int = 12_000,
) -> CommandOutputSummary:
    """Keep failures, summaries, and boundary context while collapsing noise."""

    try:
        selected_kind = CommandKind(command_kind)
    except ValueError as exc:
        raise MonasLensError(
            ErrorCode.MCP_REQUEST_INVALID,
            "The command output kind is not supported.",
        ) from exc
    if not _MIN_OUTPUT_CHARS <= max_output_chars <= _MAX_OUTPUT_CHARS:
        raise MonasLensError(
            ErrorCode.MCP_REQUEST_INVALID,
            "The command output budget is outside the supported bounds.",
            details={"minimum": _MIN_OUTPUT_CHARS, "maximum": _MAX_OUTPUT_CHARS},
        )

    original_lines = output.count("\n") + (1 if output else 0)
    input_truncated = len(output) > _MAX_INPUT_CHARS
    bounded = output[:_MAX_INPUT_CHARS].replace("\r\n", "\n").replace("\r", "\n")
    collapsed, repeated_lines = _collapse_repeated_lines(bounded.splitlines())
    selected_indices = _select_lines(collapsed)
    rendered = _render_selection(collapsed, selected_indices)
    content, output_truncated = _crop_rendered(rendered, max_output_chars)
    selected_lines = sum(not line.startswith("[... ") for line in content.splitlines())
    omitted_lines = max(original_lines - selected_lines - repeated_lines, 0)
    return CommandOutputSummary(
        command_kind=selected_kind,
        content=content,
        original_lines=original_lines,
        selected_lines=selected_lines,
        omitted_lines=omitted_lines,
        repeated_lines_collapsed=repeated_lines,
        truncated=input_truncated or output_truncated or omitted_lines > 0,
    )


def _collapse_repeated_lines(lines: Sequence[str]) -> tuple[tuple[str, ...], int]:
    if not lines:
        return (), 0
    collapsed: list[str] = []
    repeated = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        end = index + 1
        while end < len(lines) and lines[end] == line:
            end += 1
        count = end - index
        collapsed.append(line)
        if count > 1:
            collapsed.append(f"[previous line repeated {count - 1} time(s)]")
            repeated += count - 1
        index = end
    return tuple(collapsed), repeated


def _select_lines(lines: Sequence[str]) -> tuple[int, ...]:
    if len(lines) <= 80:
        return tuple(range(len(lines)))
    selected = set(range(min(8, len(lines))))
    selected.update(range(max(len(lines) - 12, 0), len(lines)))
    for index, line in enumerate(lines):
        if _PRIORITY_LINE.search(line):
            selected.update(range(max(index - 1, 0), min(index + 2, len(lines))))
    return tuple(sorted(selected))


def _render_selection(lines: Sequence[str], indices: Sequence[int]) -> tuple[str, ...]:
    rendered: list[str] = []
    previous = -1
    for index in indices:
        if previous >= 0 and index > previous + 1:
            rendered.append(f"[... {index - previous - 1} line(s) omitted ...]")
        rendered.append(lines[index])
        previous = index
    return tuple(rendered)


def _crop_rendered(lines: Sequence[str], max_chars: int) -> tuple[str, bool]:
    content = "\n".join(lines)
    if len(content) <= max_chars:
        return content, False
    suffix = "\n[output truncated to configured character budget]"
    available = max(max_chars - len(suffix), 0)
    cropped = content[:available]
    if "\n" in cropped:
        cropped = cropped.rsplit("\n", 1)[0]
    return f"{cropped}{suffix}"[:max_chars], True
