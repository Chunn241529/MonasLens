"""Safe deterministic repository scanning."""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath

from pathspec.gitignore import GitIgnoreSpec

from monas_lens.config import Settings
from monas_lens.indexing.contracts import (
    FileCandidate,
    Language,
    ScanIssue,
    ScanResult,
)
from monas_lens.paths import normalized_relative_path

_LANGUAGE_BY_EXTENSION = {
    ".py": Language.PYTHON,
    ".pyi": Language.PYTHON,
    ".js": Language.JAVASCRIPT,
    ".jsx": Language.JAVASCRIPT,
    ".mjs": Language.JAVASCRIPT,
    ".cjs": Language.JAVASCRIPT,
    ".ts": Language.TYPESCRIPT,
    ".mts": Language.TYPESCRIPT,
    ".cts": Language.TYPESCRIPT,
    ".tsx": Language.TSX,
    ".dart": Language.DART,
}

_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".dart_tool",
        ".git",
        ".hg",
        ".monascode",
        ".mypy_cache",
        ".next",
        ".nox",
        ".nuxt",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "target",
        "vendor",
        "venv",
    }
)

_GENERATED_SUFFIXES = (
    ".freezed.dart",
    ".g.dart",
    ".gen.dart",
    ".generated.dart",
    ".min.js",
)


@dataclass(frozen=True, slots=True)
class _IgnoreLayer:
    base_path: PurePosixPath
    spec: GitIgnoreSpec


class IgnoreMatcher:
    """Evaluate ordered root and nested Git ignore rules."""

    def __init__(self, layers: tuple[_IgnoreLayer, ...] = ()) -> None:
        self._layers = layers

    def with_file(self, base_path: str, ignore_file: Path) -> IgnoreMatcher:
        try:
            lines = ignore_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return self
        layer = _IgnoreLayer(
            base_path=PurePosixPath(base_path),
            spec=GitIgnoreSpec.from_lines(lines),
        )
        return IgnoreMatcher((*self._layers, layer))

    def is_ignored(self, relative_path: str, *, is_directory: bool) -> bool:
        candidate = PurePosixPath(relative_path)
        ignored = False
        for layer in self._layers:
            try:
                layer_relative = candidate.relative_to(layer.base_path)
            except ValueError:
                continue
            value = layer_relative.as_posix()
            if is_directory:
                value = f"{value}/"
            result = layer.spec.check_file(value)
            if result.include is not None:
                ignored = result.include
        return ignored


class RepositoryScanner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def scan(self, root: Path) -> ScanResult:
        root = root.resolve(strict=True)
        files: list[FileCandidate] = []
        issues: list[ScanIssue] = []
        skips: Counter[str] = Counter()
        visited_files = 0

        def visit(directory: Path, matcher: IgnoreMatcher) -> None:
            nonlocal visited_files
            directory_relative = "" if directory == root else directory.relative_to(root).as_posix()
            matcher = matcher.with_file(directory_relative, directory / ".gitignore")
            try:
                entries = sorted(os.scandir(directory), key=lambda entry: entry.name.casefold())
            except OSError:
                issues.append(ScanIssue(directory_relative, "directory_unreadable"))
                return

            for entry in entries:
                entry_path = Path(entry.path)
                relative_path = entry_path.relative_to(root).as_posix()
                try:
                    if entry.is_symlink():
                        skips["symlink"] += 1
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name in _EXCLUDED_DIRECTORIES or matcher.is_ignored(
                            relative_path, is_directory=True
                        ):
                            skips["ignored_directory"] += 1
                            continue
                        visit(entry_path, matcher)
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        skips["non_regular"] += 1
                        continue
                except OSError:
                    issues.append(ScanIssue(relative_path, "entry_unreadable"))
                    continue

                visited_files += 1
                if matcher.is_ignored(relative_path, is_directory=False):
                    skips["gitignored"] += 1
                    continue
                language = detect_language(entry_path)
                if language is None:
                    skips["unsupported"] += 1
                    continue
                candidate = self._inspect_file(root, entry_path, relative_path, language)
                if isinstance(candidate, ScanIssue):
                    issues.append(candidate)
                    skips[candidate.code] += 1
                elif candidate is None:
                    skips["excluded"] += 1
                else:
                    files.append(candidate)

        visit(root, IgnoreMatcher())
        files.sort(key=lambda item: item.relative_path)
        return ScanResult(
            files=tuple(files),
            visited_files=visited_files,
            skip_counts=dict(sorted(skips.items())),
            issues=tuple(issues),
        )

    def _inspect_file(
        self,
        root: Path,
        path: Path,
        relative_path: str,
        language: Language,
    ) -> FileCandidate | ScanIssue | None:
        if is_generated_name(path.name):
            return None
        try:
            before = path.stat()
        except OSError:
            return ScanIssue(relative_path, "stat_failed")
        if before.st_size > self._settings.max_file_size_bytes:
            return ScanIssue(relative_path, "oversized")
        try:
            with path.open("rb") as source_stream:
                probe = source_stream.read(self._settings.binary_probe_bytes)
        except OSError:
            return ScanIssue(relative_path, "read_failed")
        if is_binary_probe(probe):
            return ScanIssue(relative_path, "binary")
        if is_generated_header(probe):
            return None
        try:
            content_hash = hash_file(path, self._settings.hash_chunk_bytes)
            after = path.stat()
        except OSError:
            return ScanIssue(relative_path, "read_failed")
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return ScanIssue(relative_path, "changed_during_scan")
        normalized = normalized_relative_path(root, path)
        return FileCandidate(
            absolute_path=path,
            relative_path=normalized,
            language=language,
            size_bytes=after.st_size,
            mtime_ns=after.st_mtime_ns,
            content_hash=content_hash,
        )


def detect_language(path: Path) -> Language | None:
    return _LANGUAGE_BY_EXTENSION.get(path.suffix.lower())


def is_binary_probe(probe: bytes) -> bool:
    return b"\x00" in probe


def is_generated_name(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith(_GENERATED_SUFFIXES)


def is_generated_header(probe: bytes) -> bool:
    header = probe[:512].decode("utf-8", errors="ignore").lower()
    return "@generated" in header or "generated code" in header or "do not edit" in header


def hash_file(path: Path, chunk_size: int) -> str:
    digest = sha256()
    with path.open("rb") as source_stream:
        while chunk := source_stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
