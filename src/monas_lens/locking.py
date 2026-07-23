"""Cross-platform per-repository index locking."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from filelock import FileLock, Timeout

from monas_lens.config import Settings
from monas_lens.errors import ErrorCode, MonasLensError


def repository_lock_path(settings: Settings, repository_id: str) -> str:
    return str(settings.locks_dir / f"{repository_id}.lock")


@contextmanager
def repository_lock(settings: Settings, repository_id: str) -> Generator[None]:
    lock = FileLock(repository_lock_path(settings, repository_id))
    try:
        with lock.acquire(timeout=settings.index_lock_timeout_seconds):
            yield
    except Timeout as exc:
        raise MonasLensError(
            ErrorCode.REPOSITORY_LOCKED,
            "Another index operation is already running for this repository.",
        ) from exc


def repository_is_locked(settings: Settings, repository_id: str) -> bool:
    lock = FileLock(repository_lock_path(settings, repository_id))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return True
    else:
        lock.release()
        return False
