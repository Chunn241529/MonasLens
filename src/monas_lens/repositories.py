"""Repository registration and selection."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from monas_lens.config import Settings
from monas_lens.db.models import IndexState, RepositoryModel
from monas_lens.db.session import Database
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.locking import repository_is_locked
from monas_lens.paths import canonical_directory


class RepositoryRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    canonical_path: Path
    display_name: str
    is_active: bool
    is_git_repository: bool
    index_state: str
    last_indexed_at: datetime | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime


class RepositoryService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self._database = database
        self._settings = settings

    def add(self, path: str | Path, *, activate: bool = True) -> RepositoryRecord:
        canonical = canonical_directory(path)
        canonical_value = str(canonical)
        with self._database.session() as session:
            existing = session.scalar(
                select(RepositoryModel).where(RepositoryModel.canonical_path == canonical_value)
            )
            if existing is not None:
                if activate and not existing.is_active:
                    self._activate_model(session, existing)
                session.commit()
                return _record(existing)

            if activate:
                session.execute(update(RepositoryModel).values(is_active=False))
            model = RepositoryModel(
                id=str(uuid4()),
                canonical_path=canonical_value,
                display_name=canonical.name,
                is_active=activate,
                is_git_repository=(canonical / ".git").exists(),
                index_state=IndexState.PENDING.value,
            )
            session.add(model)
            session.commit()
            return _record(model)

    def list(self) -> list[RepositoryRecord]:
        with self._database.session() as session:
            repositories = session.scalars(
                select(RepositoryModel).order_by(
                    RepositoryModel.is_active.desc(), RepositoryModel.created_at
                )
            ).all()
            return [_record(repository) for repository in repositories]

    def active(self) -> RepositoryRecord:
        with self._database.session() as session:
            model = session.scalar(
                select(RepositoryModel).where(RepositoryModel.is_active.is_(True))
            )
            if model is None:
                raise MonasLensError(
                    ErrorCode.REPOSITORY_NOT_FOUND,
                    "No active repository is configured.",
                )
            return _record(model)

    def get(self, identifier: str | Path) -> RepositoryRecord:
        with self._database.session() as session:
            return _record(self._find(session, identifier))

    def activate(self, identifier: str | Path) -> RepositoryRecord:
        with self._database.session() as session:
            model = self._find(session, identifier)
            self._activate_model(session, model)
            session.commit()
            return _record(model)

    def remove(self, identifier: str | Path) -> RepositoryRecord:
        with self._database.session() as session:
            model = self._find(session, identifier)
            if repository_is_locked(self._settings, model.id):
                raise MonasLensError(
                    ErrorCode.REPOSITORY_LOCKED,
                    "The repository is currently being indexed.",
                )
            record = _record(model)
            session.delete(model)
            session.commit()
            return record

    @staticmethod
    def _activate_model(session: Session, model: RepositoryModel) -> None:
        session.execute(update(RepositoryModel).values(is_active=False))
        model.is_active = True

    @staticmethod
    def _find(session: Session, identifier: str | Path) -> RepositoryModel:
        value = str(identifier)
        model = session.scalar(select(RepositoryModel).where(RepositoryModel.id == value))
        if model is not None:
            return model

        try:
            canonical_value = str(canonical_directory(value))
        except MonasLensError:
            canonical_value = str(Path(value).expanduser().resolve(strict=False))
        model = session.scalar(
            select(RepositoryModel).where(RepositoryModel.canonical_path == canonical_value)
        )
        if model is None:
            raise MonasLensError(
                ErrorCode.REPOSITORY_NOT_FOUND,
                "The requested repository is not registered.",
                details={"identifier": value},
            )
        return model


def _record(model: RepositoryModel) -> RepositoryRecord:
    return RepositoryRecord(
        id=model.id,
        canonical_path=Path(model.canonical_path),
        display_name=model.display_name,
        is_active=model.is_active,
        is_git_repository=model.is_git_repository,
        index_state=model.index_state,
        last_indexed_at=model.last_indexed_at,
        last_error_code=model.last_error_code,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
