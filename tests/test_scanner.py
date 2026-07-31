from pathlib import Path

import pytest

from monas_lens.config import Settings
from monas_lens.indexing.contracts import Language
from monas_lens.indexing.scanner import RepositoryScanner, detect_language, hash_file


def test_language_detection() -> None:
    assert detect_language(Path("service.py")) is Language.PYTHON
    assert detect_language(Path("component.jsx")) is Language.JAVASCRIPT
    assert detect_language(Path("service.ts")) is Language.TYPESCRIPT
    assert detect_language(Path("component.tsx")) is Language.TSX
    assert detect_language(Path("service.dart")) is Language.DART
    assert detect_language(Path("service.go")) is Language.GO
    assert detect_language(Path("README.md")) is None


def test_scanner_respects_nested_ignore_and_filters(tmp_path: Path, settings: Settings) -> None:
    repository = tmp_path / "repository"
    nested = repository / "packages"
    nested.mkdir(parents=True)
    (repository / ".gitignore").write_text(
        "ignored.py\nbuild/\n",
        encoding="utf-8",
    )
    (nested / ".gitignore").write_text(
        "*.ts\n!keep.ts\n",
        encoding="utf-8",
    )
    (repository / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (repository / "ignored.py").write_text("ignored = True\n", encoding="utf-8")
    (repository / "binary.py").write_bytes(b"value = 1\x00")
    (repository / "generated.g.dart").write_text(
        "// generated code\n",
        encoding="utf-8",
    )
    (repository / "unsupported.md").write_text("# title\n", encoding="utf-8")
    (nested / "drop.ts").write_text("export const drop = 1;\n", encoding="utf-8")
    (nested / "keep.ts").write_text("export const keep = 1;\n", encoding="utf-8")
    build = repository / "build"
    build.mkdir()
    (build / "artifact.js").write_text("export const artifact = 1;\n", encoding="utf-8")

    scanner = RepositoryScanner(settings)
    result = scanner.scan(repository)

    assert [candidate.relative_path for candidate in result.files] == [
        "main.py",
        "packages/keep.ts",
    ]
    assert result.files[0].language is Language.PYTHON
    assert result.skip_counts["gitignored"] == 2
    assert result.skip_counts["ignored_directory"] == 1
    assert result.skip_counts["binary"] == 1
    assert result.skip_counts["unsupported"] >= 1


def test_scanner_skips_oversized_and_symlinked_files(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("outside = True\n", encoding="utf-8")
    (repository / "large.py").write_text("x" * 2048, encoding="utf-8")
    try:
        (repository / "link.py").symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is unavailable on this platform.")
    settings = Settings(data_dir=tmp_path / "state", max_file_size_bytes=1024)

    result = RepositoryScanner(settings).scan(repository)

    assert result.files == ()
    assert result.skip_counts["oversized"] == 1
    assert result.skip_counts["symlink"] == 1


def test_hash_file_is_content_based(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text("value = 1\n", encoding="utf-8")
    first_hash = hash_file(source, 4)

    source.touch()
    second_hash = hash_file(source, 4)
    source.write_text("value = 2\n", encoding="utf-8")

    assert first_hash == second_hash
    assert hash_file(source, 4) != first_hash
