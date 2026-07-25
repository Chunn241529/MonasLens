from pathlib import Path

import pytest

from monas_lens.config import Settings
from monas_lens.db.migration import downgrade_database, upgrade_database
from monas_lens.db.session import Database
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.indexing.service import IndexService
from monas_lens.repositories import RepositoryService
from monas_lens.search.service import SearchService


def _register_and_index(
    database: Database,
    settings: Settings,
    repository_root: Path,
) -> str:
    repository = RepositoryService(database, settings).add(repository_root)
    summary = IndexService(database, settings).build(repository.id)
    assert summary.failed_files == 0
    return repository.id


def test_exact_symbol_and_lexical_source_search(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "service.py").write_text(
        """
class Service:
    def normalize_value(self, raw_input: str) -> str:
        return raw_input.strip().lower()
""".lstrip(),
        encoding="utf-8",
    )
    repository_id = _register_and_index(database, settings, repository_root)
    service = SearchService(database, settings)

    exact = service.search("Service.normalize_value", repository_id)
    lexical = service.search("strip lower", repository_id)

    assert exact.results[0].match_type == "exact"
    assert exact.results[0].score > exact.results[-1].score
    assert exact.results[0].qualified_name == "Service.normalize_value"
    assert exact.results[0].relative_path == "service.py"
    assert any(result.entity_type == "chunk" for result in lexical.results)
    assert all(result.relative_path == "service.py" for result in lexical.results)


def test_search_projection_tracks_update_delete_and_repository_scope(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    first_root.mkdir()
    source_file = first_root / "service.py"
    source_file.write_text(
        "def calculate() -> str:\n    return 'legacy_token'\n",
        encoding="utf-8",
    )
    first_id = _register_and_index(database, settings, first_root)

    second_root = tmp_path / "second"
    second_root.mkdir()
    (second_root / "service.py").write_text(
        "def calculate() -> str:\n    return 'other_repository_token'\n",
        encoding="utf-8",
    )
    second_id = _register_and_index(database, settings, second_root)
    search = SearchService(database, settings)
    indexing = IndexService(database, settings)

    assert search.search("legacy_token", first_id).total > 0
    assert search.search("legacy_token", second_id).total == 0

    source_file.write_text(
        "def calculate() -> str:\n    return 'replacement_token'\n",
        encoding="utf-8",
    )
    update = indexing.build(first_id)

    assert update.parsed_files == 1
    assert search.search("legacy_token", first_id).total == 0
    assert search.search("replacement_token", first_id).total > 0

    source_file.unlink()
    deletion = indexing.build(first_id)

    assert deletion.deleted_files == 1
    assert search.search("replacement_token", first_id).total == 0


def test_search_migration_backfills_existing_structural_records(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "service.py").write_text(
        "def migrated_symbol() -> str:\n    return 'migration_search_token'\n",
        encoding="utf-8",
    )
    repository_id = _register_and_index(database, settings, repository_root)

    downgrade_database(database.engine, "0002_structural_index")
    upgrade_database(database.engine)

    response = SearchService(database, settings).search(
        "migration_search_token",
        repository_id,
    )

    assert response.total > 0
    assert any(result.entity_type == "chunk" for result in response.results)


@pytest.mark.parametrize(
    ("query", "limit"),
    [
        ("", 20),
        ("***", 20),
        ("x" * 501, 20),
        ("valid", 0),
        ("valid", 101),
    ],
)
def test_search_rejects_invalid_input(
    database: Database,
    settings: Settings,
    query: str,
    limit: int,
) -> None:
    service = SearchService(database, settings)

    with pytest.raises(MonasLensError) as raised:
        service.search(query, limit=limit)

    assert raised.value.code is ErrorCode.SEARCH_QUERY_INVALID
