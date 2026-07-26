"""Application settings and local configuration loading."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, Self, cast

from platformdirs import user_config_path, user_data_path
from pydantic import BaseModel, ConfigDict, Field, model_validator

from monas_lens.errors import ErrorCode, MonasLensError

ENV_PREFIX = "MONAS_LENS_"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


def default_data_dir() -> Path:
    return user_data_path("monas-lens", appauthor=False)


def default_config_file() -> Path:
    return user_config_path("monas-lens", appauthor=False) / "config.toml"


class Settings(BaseModel):
    """Validated runtime settings with no import-time filesystem effects."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    data_dir: Path = Field(default_factory=default_data_dir)
    database_path: Path | None = None
    log_level: LogLevel = LogLevel.INFO
    log_json: bool = False
    sqlite_busy_timeout_ms: int = Field(default=5_000, ge=100, le=120_000)
    max_file_size_bytes: int = Field(default=2_000_000, ge=1_024, le=100_000_000)
    binary_probe_bytes: int = Field(default=8_192, ge=256, le=1_000_000)
    hash_chunk_bytes: int = Field(default=1_048_576, ge=4_096, le=16_777_216)
    index_lock_timeout_seconds: float = Field(default=0.1, ge=0, le=300)
    context_max_task_chars: int = Field(default=4_000, ge=100, le=100_000)
    context_max_focus_targets: int = Field(default=10, ge=1, le=100)
    context_max_focus_target_chars: int = Field(default=500, ge=10, le=4_096)
    context_max_retrieval_queries: int = Field(default=12, ge=1, le=100)
    context_parallel_workers: int = Field(default=4, ge=1, le=32)
    context_max_candidates: int = Field(default=200, ge=10, le=5_000)
    context_max_retrieval_diagnostics: int = Field(default=32, ge=1, le=100)
    context_max_primary_targets: int = Field(default=3, ge=1, le=10)
    context_max_dependency_snippets: int = Field(default=6, ge=0, le=100)
    context_max_caller_snippets: int = Field(default=6, ge=0, le=100)
    context_max_test_snippets: int = Field(default=4, ge=0, le=100)
    context_max_git_entries: int = Field(default=5, ge=0, le=100)
    context_max_total_tokens: int = Field(default=12_000, ge=256, le=100_000)
    context_confidence_threshold: float = Field(default=0.80, ge=0, le=1)
    context_max_internal_expansions: int = Field(default=1, ge=0, le=1)
    context_initial_graph_depth: int = Field(default=1, ge=1, le=1)
    context_expanded_graph_depth: int = Field(default=2, ge=2, le=2)
    context_token_safety_margin: float = Field(default=0.10, ge=0, le=0.50)
    context_response_envelope_tokens: int = Field(default=256, ge=0, le=4_096)
    context_git_diff_timeout_seconds: float = Field(default=3.0, ge=0.1, le=30)
    context_git_diff_max_bytes: int = Field(default=262_144, ge=1_024, le=10_000_000)

    @model_validator(mode="after")
    def normalize_paths(self) -> Self:
        data_dir = self.data_dir.expanduser().resolve(strict=False)
        database_path = self.database_path or data_dir / "monas_lens.db"
        database_path = database_path.expanduser().resolve(strict=False)
        object.__setattr__(self, "data_dir", data_dir)
        object.__setattr__(self, "database_path", database_path)
        return self

    @property
    def locks_dir(self) -> Path:
        return self.data_dir / "locks"

    def public_dict(self) -> dict[str, Any]:
        return {
            "data_dir": str(self.data_dir),
            "database_path": str(self.database_path),
            "log_level": self.log_level.value,
            "log_json": self.log_json,
            "sqlite_busy_timeout_ms": self.sqlite_busy_timeout_ms,
            "max_file_size_bytes": self.max_file_size_bytes,
        }


def load_settings(
    *,
    config_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> Settings:
    """Load settings using CLI > environment > TOML > defaults precedence."""
    environment = environ if environ is not None else os.environ
    selected_config = config_file
    explicit_config = config_file is not None
    if selected_config is None and f"{ENV_PREFIX}CONFIG_FILE" in environment:
        selected_config = Path(environment[f"{ENV_PREFIX}CONFIG_FILE"])
        explicit_config = True
    selected_config = selected_config or default_config_file()

    values: dict[str, Any] = {}
    if selected_config.exists():
        values.update(_read_config_file(selected_config))
    elif explicit_config:
        raise MonasLensError(
            ErrorCode.CONFIGURATION_INVALID,
            "The requested configuration file does not exist.",
            details={"path": str(selected_config)},
        )

    for field_name in Settings.model_fields:
        env_name = f"{ENV_PREFIX}{field_name.upper()}"
        if env_name in environment:
            values[field_name] = environment[env_name]
    values.update(overrides or {})

    try:
        return Settings.model_validate(values)
    except ValueError as exc:
        raise MonasLensError(
            ErrorCode.CONFIGURATION_INVALID,
            "Monas Lens configuration is invalid.",
        ) from exc


def ensure_runtime_directories(settings: Settings) -> None:
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.locks_dir.mkdir(parents=True, exist_ok=True)
        if settings.database_path is not None:
            settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MonasLensError(
            ErrorCode.CONFIGURATION_INVALID,
            "Monas Lens cannot create its local data directories.",
        ) from exc


def _read_config_file(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as config_stream:
            payload = tomllib.load(config_stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise MonasLensError(
            ErrorCode.CONFIGURATION_INVALID,
            "The Monas Lens configuration file cannot be read.",
            details={"path": str(path)},
        ) from exc
    section = payload.get("monas_lens", payload)
    if not isinstance(section, dict):
        raise MonasLensError(
            ErrorCode.CONFIGURATION_INVALID,
            "The configuration root must be a TOML table.",
        )
    return cast(dict[str, Any], section)
