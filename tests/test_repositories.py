from pathlib import Path

import pytest
from sqlalchemy import func, select

from monas_lens.config import Settings
from monas_lens.db.models import RepositoryModel
from monas_lens.db.session import Database
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.repositories import RepositoryService


def test_repository_registration_is_idempotent(
    database: Database, settings: Settings, tmp_path: Path
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    service = RepositoryService(database, settings)

    first = service.add(repository_root)
    second = service.add(repository_root / ".")

    assert first.id == second.id
    assert second.is_active
    assert len(service.list()) == 1


def test_only_one_repository_can_be_active(
    database: Database, settings: Settings, tmp_path: Path
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    service = RepositoryService(database, settings)

    first = service.add(first_root)
    second = service.add(second_root)

    assert service.get(first.id).is_active is False
    assert service.get(second.id).is_active is True
    with database.session() as session:
        active_count = session.scalar(
            select(func.count())
            .select_from(RepositoryModel)
            .where(RepositoryModel.is_active.is_(True))
        )
    assert active_count == 1


def test_removing_repository_preserves_source(
    database: Database, settings: Settings, tmp_path: Path
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    source = repository_root / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")
    service = RepositoryService(database, settings)
    repository = service.add(repository_root)

    removed = service.remove(repository.id)

    assert removed.id == repository.id
    assert source.read_text(encoding="utf-8") == "value = 1\n"
    with pytest.raises(MonasLensError) as error:
        service.get(repository.id)
    assert error.value.code is ErrorCode.REPOSITORY_NOT_FOUND
