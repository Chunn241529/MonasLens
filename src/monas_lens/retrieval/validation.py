"""Conservative display-only validation command suggestions."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import cast

from monas_lens.retrieval.contracts import (
    CandidateRole,
    ContextSnippet,
    ValidationCommand,
)

_MAX_MANIFEST_BYTES = 1_048_576


def suggest_validation_commands(
    repository_root: Path,
    snippets: Sequence[ContextSnippet],
) -> tuple[ValidationCommand, ...]:
    """Suggest display-only commands from fixed manifests and selected test paths."""

    root = repository_root.resolve(strict=False)
    if not root.is_dir():
        return ()
    test_paths_by_language: dict[str, set[str]] = {}
    for snippet in snippets:
        if snippet.role is not CandidateRole.TEST:
            continue
        relative_path = normalize_repository_relative_path(snippet.relative_path)
        if relative_path is None or len(relative_path) > 500:
            continue
        test_paths_by_language.setdefault(snippet.language, set()).add(relative_path)

    commands: list[ValidationCommand] = []
    python_paths = sorted(test_paths_by_language.get("python", ()))
    if python_paths and _has_python_manifest(root):
        arguments = (
            ("uv", "run", "pytest", *python_paths)
            if (root / "uv.lock").is_file()
            else ("python", "-m", "pytest", *python_paths)
        )
        commands.append(
            ValidationCommand(
                label="Run selected Python tests",
                arguments=arguments[:64],
            )
        )

    node_paths = sorted(
        path
        for language in ("javascript", "typescript", "tsx")
        for path in test_paths_by_language.get(language, ())
    )
    if node_paths and _package_manifest_has_test_script(root):
        commands.append(_node_validation_command(root, node_paths))

    dart_paths = sorted(test_paths_by_language.get("dart", ()))
    if dart_paths and (root / "pubspec.yaml").is_file():
        commands.append(
            ValidationCommand(
                label="Run selected Dart tests",
                arguments=("dart", "test", *dart_paths)[:64],
            )
        )
    return tuple(commands)


def suggest_repository_validation_commands(
    repository_root: Path,
    languages: Sequence[str],
) -> tuple[ValidationCommand, ...]:
    """Suggest repository-level validation commands for changed languages."""

    root = repository_root.resolve(strict=False)
    if not root.is_dir():
        return ()
    selected_languages = frozenset(languages)
    commands: list[ValidationCommand] = []
    if "python" in selected_languages and _has_python_manifest(root):
        arguments = (
            ("uv", "run", "pytest") if (root / "uv.lock").is_file() else ("python", "-m", "pytest")
        )
        commands.append(ValidationCommand(label="Run Python tests", arguments=arguments))
    if selected_languages & {"javascript", "typescript", "tsx"} and (
        _package_manifest_has_test_script(root)
    ):
        commands.append(_node_validation_command(root, ()))
    if "dart" in selected_languages and (root / "pubspec.yaml").is_file():
        commands.append(ValidationCommand(label="Run Dart tests", arguments=("dart", "test")))
    return tuple(commands)


def normalize_repository_relative_path(value: str) -> str | None:
    """Normalize a path only when it cannot escape the repository root."""

    normalized = value.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    windows_absolute = len(normalized) >= 2 and normalized[1] == ":"
    if (
        not normalized
        or "\x00" in normalized
        or path.is_absolute()
        or windows_absolute
        or ".." in path.parts
    ):
        return None
    return path.as_posix()


def _has_python_manifest(repository_root: Path) -> bool:
    return any(
        (repository_root / name).is_file()
        for name in ("pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg")
    )


def _package_manifest_has_test_script(repository_root: Path) -> bool:
    path = repository_root / "package.json"
    try:
        if not path.is_file() or path.stat().st_size > _MAX_MANIFEST_BYTES:
            return False
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    manifest = cast(dict[str, object], payload)
    scripts = manifest.get("scripts")
    if not isinstance(scripts, dict):
        return False
    test_script = cast(dict[str, object], scripts).get("test")
    return isinstance(test_script, str) and bool(test_script.strip())


def _node_validation_command(
    repository_root: Path,
    test_paths: Sequence[str],
) -> ValidationCommand:
    if (repository_root / "pnpm-lock.yaml").is_file():
        arguments = ("pnpm", "test", "--", *test_paths)
    elif (repository_root / "yarn.lock").is_file():
        arguments = ("yarn", "test", *test_paths)
    elif (repository_root / "bun.lock").is_file() or (repository_root / "bun.lockb").is_file():
        arguments = ("bun", "run", "test", "--", *test_paths)
    else:
        arguments = ("npm", "test", "--", *test_paths)
    return ValidationCommand(
        label="Run selected JavaScript tests",
        arguments=arguments[:64],
    )
