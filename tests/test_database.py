from pathlib import Path

from sqlalchemy import select, text

from monas_lens.config import Settings, ensure_runtime_directories
from monas_lens.db.migration import (
    database_is_current,
    database_revision,
    downgrade_database,
    upgrade_database,
)
from monas_lens.db.models import FileModel
from monas_lens.db.session import Database
from monas_lens.indexing.service import IndexService
from monas_lens.indexing.version import CURRENT_EXTRACTOR_VERSION
from monas_lens.repositories import RepositoryService


def test_fresh_database_upgrades_to_head(settings: Settings) -> None:
    ensure_runtime_directories(settings)
    database = Database(settings)
    try:
        assert not database_is_current(database.engine)

        upgrade_database(database.engine)
        current, expected = database_revision(database.engine)

        assert current == expected == "0005_extractor_version"
        assert database_is_current(database.engine)
    finally:
        database.dispose()


def test_sqlite_pragmas_are_enabled(database: Database) -> None:
    with database.engine.connect() as connection:
        foreign_keys = connection.scalar(text("PRAGMA foreign_keys"))
        journal_mode = connection.scalar(text("PRAGMA journal_mode"))

    assert foreign_keys == 1
    assert str(journal_mode).lower() == "wal"


def test_graph_migration_can_downgrade_and_upgrade(settings: Settings) -> None:
    ensure_runtime_directories(settings)
    database = Database(settings)
    try:
        upgrade_database(database.engine)
        downgrade_database(database.engine, "0003_search_index")
        current, _expected = database_revision(database.engine)
        assert current == "0003_search_index"

        upgrade_database(database.engine)
        current, expected = database_revision(database.engine)
        assert current == expected == "0005_extractor_version"
    finally:
        database.dispose()


def test_upgraded_index_reparses_old_extractor_output_once(
    settings: Settings,
    tmp_path: Path,
) -> None:
    ensure_runtime_directories(settings)
    database = Database(settings)
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "service.py").write_text(
        "def run() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    try:
        upgrade_database(database.engine)
        repository = RepositoryService(database, settings).add(repository_root)
        service = IndexService(database, settings)
        assert service.build(repository.id).parsed_files == 1

        downgrade_database(database.engine, "0004_relationship_graph")
        upgrade_database(database.engine)

        with database.session() as session:
            stored_version = session.scalar(select(FileModel.indexed_extractor_version))
        assert stored_version is None

        upgraded = service.build(repository.id)
        unchanged = service.build(repository.id)

        assert upgraded.parsed_files == 1
        assert unchanged.parsed_files == 0
        with database.session() as session:
            stored_version = session.scalar(select(FileModel.indexed_extractor_version))
        assert stored_version == CURRENT_EXTRACTOR_VERSION
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
