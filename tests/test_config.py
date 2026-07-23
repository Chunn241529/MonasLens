from pathlib import Path

import pytest

from monas_lens.config import Settings, ensure_runtime_directories, load_settings
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.paths import (
    canonical_directory,
    normalized_relative_path,
    path_is_within,
)


def test_settings_precedence(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "[monas_lens]\n"
        f'data_dir = "{(tmp_path / "toml").as_posix()}"\n'
        "max_file_size_bytes = 2048\n",
        encoding="utf-8",
    )

    settings = load_settings(
        config_file=config_file,
        environ={"MONAS_LENS_MAX_FILE_SIZE_BYTES": "4096"},
        overrides={"max_file_size_bytes": 8192},
    )

    assert settings.data_dir == (tmp_path / "toml").resolve()
    assert settings.max_file_size_bytes == 8192


def test_missing_explicit_config_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(MonasLensError) as error:
        load_settings(config_file=tmp_path / "missing.toml", environ={})

    assert error.value.code is ErrorCode.CONFIGURATION_INVALID


def test_runtime_directories_are_created(settings: Settings) -> None:
    ensure_runtime_directories(settings)

    assert settings.data_dir.is_dir()
    assert settings.locks_dir.is_dir()
    assert settings.database_path is not None
    assert settings.database_path.parent.is_dir()


def test_safe_relative_path_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    source = root / "src" / "module.py"
    outside = tmp_path / "outside.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n", encoding="utf-8")
    outside.write_text("value = 2\n", encoding="utf-8")

    assert canonical_directory(root) == root.resolve()
    assert normalized_relative_path(root, source) == "src/module.py"
    assert path_is_within(root, source)
    assert not path_is_within(root, outside)

    with pytest.raises(MonasLensError) as error:
        normalized_relative_path(root, outside)

    assert error.value.code is ErrorCode.PATH_OUTSIDE_REPOSITORY
