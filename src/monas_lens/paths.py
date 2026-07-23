"""Safe filesystem path helpers."""

from pathlib import Path

from monas_lens.errors import ErrorCode, MonasLensError


def canonical_directory(value: str | Path) -> Path:
    """Return an existing directory as a canonical absolute path."""
    raw_path = Path(value).expanduser()
    try:
        resolved = raw_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise MonasLensError(
            ErrorCode.INVALID_PATH,
            "The repository path does not exist or cannot be resolved.",
            details={"path": str(raw_path)},
        ) from exc
    if not resolved.is_dir():
        raise MonasLensError(
            ErrorCode.INVALID_PATH,
            "The repository path must be a directory.",
            details={"path": str(resolved)},
        )
    return resolved


def normalized_relative_path(root: Path, candidate: Path) -> str:
    """Return a POSIX relative path, rejecting paths outside ``root``."""
    try:
        resolved_root = root.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=True)
        relative = resolved_candidate.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise MonasLensError(
            ErrorCode.PATH_OUTSIDE_REPOSITORY,
            "The source path is outside the registered repository.",
        ) from exc
    return relative.as_posix()


def path_is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return False
    return True
