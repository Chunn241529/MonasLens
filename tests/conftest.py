from collections.abc import Iterator
from pathlib import Path

import pytest

from monas_lens.config import Settings, ensure_runtime_directories
from monas_lens.db.migration import upgrade_database
from monas_lens.db.session import Database


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "state")


@pytest.fixture
def database(settings: Settings) -> Iterator[Database]:
    ensure_runtime_directories(settings)
    selected_database = Database(settings)
    upgrade_database(selected_database.engine)
    try:
        yield selected_database
    finally:
        selected_database.dispose()
