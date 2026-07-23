from pathlib import Path

from sqlalchemy import text

from monas_lens.config import Settings, ensure_runtime_directories
from monas_lens.db.migration import (
    database_is_current,
    database_revision,
    downgrade_database,
    upgrade_database,
)
from monas_lens.db.session import Database


def test_fresh_database_upgrades_to_head(settings: Settings) -> None:
    ensure_runtime_directories(settings)
    database = Database(settings)
    try:
        assert not database_is_current(database.engine)

        upgrade_database(database.engine)
        current, expected = database_revision(database.engine)

        assert current == expected == "0002_structural_index"
        assert database_is_current(database.engine)
    finally:
        database.dispose()


def test_sqlite_pragmas_are_enabled(database: Database) -> None:
    with database.engine.connect() as connection:
        foreign_keys = connection.scalar(text("PRAGMA foreign_keys"))
        journal_mode = connection.scalar(text("PRAGMA journal_mode"))

    assert foreign_keys == 1
    assert str(journal_mode).lower() == "wal"


def test_structural_migration_can_downgrade_and_upgrade(settings: Settings) -> None:
    ensure_runtime_directories(settings)
    database = Database(settings)
    try:
        upgrade_database(database.engine)
        downgrade_database(database.engine, "0001_foundation")
        current, _expected = database_revision(database.engine)
        assert current == "0001_foundation"

        upgrade_database(database.engine)
        current, expected = database_revision(database.engine)
        assert current == expected == "0002_structural_index"
    finally:
        database.dispose()


def test_session_rolls_back_on_error(database: Database, tmp_path: Path) -> None:
    from monas_lens.repositories import RepositoryService

    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    service = RepositoryService(
        database,
        Settings(data_dir=tmp_path / "state"),
    )
    repository = service.add(repository_root)

    with database.session() as session:
        session.execute(
            text("UPDATE repositories SET display_name = 'changed' WHERE id = :id"),
            {"id": repository.id},
        )
        session.rollback()

    assert service.get(repository.id).display_name == "repository"
