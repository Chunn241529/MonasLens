from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from monas_lens.config import Settings
from monas_lens.db.models import SymbolModel
from monas_lens.db.session import Database
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.indexing.contracts import ParseStatus
from monas_lens.indexing.scanner import RepositoryScanner
from monas_lens.indexing.service import IndexService
from monas_lens.indexing.store import StructuralStore
from monas_lens.indexing.version import CURRENT_EXTRACTOR_VERSION
from monas_lens.locking import repository_lock
from monas_lens.parsing.registry import ParserRegistry
from monas_lens.repositories import RepositoryService


def create_mixed_repository(root: Path) -> None:
    root.mkdir()
    (root / "service.py").write_text(
        "class Service:\n    def run(self, value: int) -> str:\n        return str(value)\n",
        encoding="utf-8",
    )
    (root / "service.js").write_text(
        "export class Service { run(value) { return value; } }\n",
        encoding="utf-8",
    )
    (root / "service.ts").write_text(
        "export interface Service { run(value: number): string; }\n",
        encoding="utf-8",
    )
    (root / "component.tsx").write_text(
        "export const Component = () => <div />;\n",
        encoding="utf-8",
    )
    (root / "service.dart").write_text(
        "class Service { String run(int value) => value.toString(); }\n",
        encoding="utf-8",
    )


def test_incremental_index_add_update_delete_and_full_rebuild(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    create_mixed_repository(repository_root)
    repository = RepositoryService(database, settings).add(repository_root)
    service = IndexService(database, settings)

    first = service.build()
    with database.session() as session:
        initial_symbol_ids = set(session.scalars(select(SymbolModel.id)).all())
    second = service.build()
    with database.session() as session:
        second_symbol_ids = set(session.scalars(select(SymbolModel.id)).all())

    assert first.scanned_files == 5
    assert first.parsed_files == 5
    assert first.failed_files == 0
    assert second.parsed_files == 0
    assert second.unchanged_files == 5
    assert initial_symbol_ids == second_symbol_ids

    (repository_root / "service.py").write_text(
        "class Service:\n    def run(self, value: int) -> str:\n        return f'value={value}'\n",
        encoding="utf-8",
    )
    updated = service.build()

    assert updated.parsed_files == 1
    assert updated.unchanged_files == 4

    (repository_root / "service.js").unlink()
    deleted = service.build()

    assert deleted.deleted_files == 1
    assert deleted.parsed_files == 0
    status = service.status(repository.id)
    assert status.files == 4
    assert status.symbols > 0
    assert status.chunks > 0
    assert status.facts > 0

    rebuilt = service.build(full=True)

    assert rebuilt.parsed_files == 4
    assert rebuilt.failed_files == 0


def test_failed_parse_preserves_last_known_good_records(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    source = repository_root / "service.py"
    source.write_text("def run() -> int:\n    return 1\n", encoding="utf-8")
    repository = RepositoryService(database, settings).add(repository_root)
    service = IndexService(database, settings)
    store = StructuralStore(database)

    first = service.build()
    before = store.files(repository.id)["service.py"]
    source.write_bytes(b"def run():\n    return \xff\n")
    failed = service.build()
    stale = store.files(repository.id)["service.py"]

    assert first.parsed_files == 1
    assert failed.failed_files == 1
    assert stale.parse_status is ParseStatus.STALE
    assert stale.indexed_hash == before.indexed_hash
    assert stale.observed_hash != stale.indexed_hash
    assert stale.indexed_extractor_version == CURRENT_EXTRACTOR_VERSION
    assert stale.symbol_count == before.symbol_count

    skipped = service.build()
    retried = service.build(retry_failed=True)

    assert skipped.parsed_files == 0
    assert skipped.stale_files == 1
    assert retried.failed_files == 1

    source.write_text("def run() -> int:\n    return 2\n", encoding="utf-8")
    recovered = service.build()

    assert recovered.parsed_files == 1
    assert recovered.stale_files == 0


def test_repository_lock_rejects_concurrent_index(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "service.py").write_text("value = 1\n", encoding="utf-8")
    repository = RepositoryService(database, settings).add(repository_root)
    service = IndexService(database, settings)

    with (
        repository_lock(settings, repository.id),
        pytest.raises(MonasLensError) as error,
    ):
        service.build()

    assert error.value.code is ErrorCode.REPOSITORY_LOCKED


def test_file_replacement_is_atomic(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    source_path = repository_root / "service.py"
    source_path.write_text("def run() -> int:\n    return 1\n", encoding="utf-8")
    repository = RepositoryService(database, settings).add(repository_root)
    service = IndexService(database, settings)
    store = StructuralStore(database)
    service.build()
    counts_before = store.counts(repository.id)

    candidate = RepositoryScanner(settings).scan(repository_root).files[0]
    extraction = ParserRegistry().extract(
        candidate.language,
        candidate.relative_path,
        source_path.read_bytes(),
    )
    duplicate = replace(
        extraction,
        symbols=(extraction.symbols[0], extraction.symbols[0]),
    )

    with pytest.raises(IntegrityError):
        store.replace_file(repository.id, candidate, duplicate)

    assert store.counts(repository.id) == counts_before
