"""Tests for the deterministic Task Resolver."""

from __future__ import annotations

import json

from monas_lens.retrieval.contracts import TaskAction
from monas_lens.retrieval.resolver import resolve_task


def test_resolve_task_extracts_qualified_identifiers() -> None:
    resolution = resolve_task("Fix Parser.run method")

    assert "Parser.run" in resolution.qualified_identifiers
    assert resolution.normalized_task == "Fix Parser.run method"


def test_resolve_task_extracts_single_identifiers() -> None:
    resolution = resolve_task("Update the UserService class")

    # "Update" and "UserService" should be identifiers, not stop words
    assert "UserService" in resolution.identifiers


def test_resolve_task_extracts_paths() -> None:
    resolution = resolve_task("Fix the bug in src/parser.py")

    assert "src/parser.py" in resolution.path_candidates


def test_resolve_task_extracts_windows_paths() -> None:
    resolution = resolve_task("Fix the bug in src\\parser.py")

    assert "src/parser.py" in resolution.path_candidates


def test_resolve_task_extracts_quoted_phrases() -> None:
    resolution = resolve_task('Fix the "connection timeout" error')

    assert "connection timeout" in resolution.quoted_phrases


def test_resolve_task_extracts_single_quoted_phrases() -> None:
    resolution = resolve_task("Fix the 'connection timeout' error")

    assert "connection timeout" in resolution.quoted_phrases


def test_resolve_task_classifies_diagnose_action() -> None:
    cases = [
        "Debug the crash in Parser",
        "Find the bug in the connection handler",
        "Investigate the error in production",
        "The application is broken",
        "What's wrong with the parser?",
    ]
    for task in cases:
        resolution = resolve_task(task)
        assert resolution.action is TaskAction.DIAGNOSE, f"Failed for: {task}"


def test_resolve_task_classifies_change_action() -> None:
    cases = [
        "Fix the null pointer in Parser",
        "Remove the deprecated method",
        "Update the configuration values",
        "Implement the new validation logic",
    ]
    for task in cases:
        resolution = resolve_task(task)
        assert resolution.action is TaskAction.CHANGE, f"Failed for: {task}"


def test_resolve_task_classifies_refactor_action() -> None:
    cases = [
        "Refactor the database connection pool",
        "Extract the validation logic into a separate module",
        "Rename the old method to follow conventions",
        "Simplify the complex conditional",
    ]
    for task in cases:
        resolution = resolve_task(task)
        assert resolution.action is TaskAction.REFACTOR, f"Failed for: {task}"


def test_resolve_task_classifies_test_action() -> None:
    cases = [
        "Add tests for the Parser class",
        "Verify the edge cases in the validator",
        "Check the coverage for the service module",
    ]
    for task in cases:
        resolution = resolve_task(task)
        assert resolution.action is TaskAction.TEST, f"Failed for: {task}"


def test_resolve_task_classifies_explain_action() -> None:
    cases = [
        "Explain how the graph builder works",
        "Describe the indexing pipeline",
        "What does the resolver module do?",
    ]
    for task in cases:
        resolution = resolve_task(task)
        assert resolution.action is TaskAction.EXPLAIN, f"Failed for: {task}"


def test_resolve_task_classifies_unknown_action() -> None:
    resolution = resolve_task("Parser.run")
    assert resolution.action is TaskAction.UNKNOWN


def test_resolve_task_ambiguous_input_resolves_to_strongest_signal() -> None:
    # "Why is the test failing?" has both diagnostic ("why", "failing") and test ("test") signals
    # The resolver picks the first matching action in priority order
    resolution = resolve_task("Why is the test failing?")
    # "test" matches TEST before "why" matches DIAGNOSE
    assert resolution.action is TaskAction.TEST


def test_resolve_task_is_deterministic() -> None:
    task = "Fix Parser.run in src/parser.py with 'timeout error'"
    first = resolve_task(task)
    second = resolve_task(task)

    assert first.model_dump_json() == second.model_dump_json()


def test_resolve_task_preserves_casing() -> None:
    resolution = resolve_task("Fix MyService.DoWork method")

    assert "MyService.DoWork" in resolution.qualified_identifiers
    assert "MyService" not in resolution.identifiers  # part of qualified


def test_resolve_task_normalizes_whitespace() -> None:
    resolution = resolve_task("  Fix   Parser.run  method  ")

    assert resolution.normalized_task == "Fix   Parser.run  method"


def test_resolve_task_separates_explicit_focus() -> None:
    resolution = resolve_task(
        "Fix the parser",
        focus_targets=["src/parser.py", "Parser.run"],
    )

    assert resolution.explicit_focus_targets == ("src/parser.py", "Parser.run")


def test_resolve_task_deduplicates_focus_targets() -> None:
    resolution = resolve_task(
        "Fix the parser",
        focus_targets=["src/parser.py", "src/parser.py", "Parser.run"],
    )

    assert resolution.explicit_focus_targets == ("src/parser.py", "Parser.run")


def test_resolve_task_handles_empty_focus() -> None:
    resolution = resolve_task("Fix the parser", focus_targets=[])

    assert resolution.explicit_focus_targets == ()


def test_resolve_task_builds_lexical_queries() -> None:
    resolution = resolve_task("Fix Parser.run timeout error")

    # Should include qualified identifier and meaningful identifiers
    assert "Parser.run" in resolution.lexical_queries


def test_resolve_task_limits_lexical_queries() -> None:
    # Create a task with many identifiers
    task = "Fix alpha bravo charlie delta echo foxtrot golf hotel india juliet"
    resolution = resolve_task(task)

    assert len(resolution.lexical_queries) <= 6


def test_resolve_task_handles_unicode() -> None:
    resolution = resolve_task("Fix the パーサー モジュール")

    assert resolution.normalized_task == "Fix the パーサー モジュール"


def test_resolve_task_handles_mixed_prose_and_code() -> None:
    resolution = resolve_task(
        "The function Parser.parse() in src/parser.py throws a ValueError "
        "when called with empty input"
    )

    assert "Parser.parse" in resolution.qualified_identifiers
    assert "src/parser.py" in resolution.path_candidates


def test_resolve_task_handles_error_messages() -> None:
    resolution = resolve_task(
        'Fix the "ValueError: invalid literal for int()" error in converter.py'
    )

    assert "ValueError: invalid literal for int()" in resolution.quoted_phrases
    assert "converter.py" in resolution.path_candidates


def test_resolve_task_no_diagnostics_for_valid_input() -> None:
    resolution = resolve_task("Fix Parser.run")

    assert resolution.diagnostics == ()


def test_resolve_task_json_deterministic() -> None:
    """Verify that JSON serialization is deterministic."""
    task = "Fix Parser.run in src/parser.py"
    resolution = resolve_task(task)

    json1 = json.dumps(resolution.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    json2 = json.dumps(resolution.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    assert json1 == json2


def test_resolve_task_multiple_qualified_identifiers() -> None:
    resolution = resolve_task("Refactor Parser.run to use Service.validate")

    assert "Parser.run" in resolution.qualified_identifiers
    assert "Service.validate" in resolution.qualified_identifiers


def test_resolve_task_paths_with_directories() -> None:
    resolution = resolve_task("Fix the bug in src/core/parser.py")

    assert "src/core/parser.py" in resolution.path_candidates


def test_resolve_task_extracts_identifiers_from_code_context() -> None:
    resolution = resolve_task("The calculateTotal function is broken")

    assert "calculateTotal" in resolution.identifiers
