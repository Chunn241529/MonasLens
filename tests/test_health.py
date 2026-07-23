from pathlib import Path

import httpx
import pytest

from monas_lens.api import create_app
from monas_lens.config import Settings, ensure_runtime_directories
from monas_lens.db.migration import upgrade_database
from monas_lens.db.session import Database


@pytest.mark.anyio
async def test_liveness_does_not_require_initialized_storage(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "missing"))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.anyio
async def test_readiness_reports_database_revision(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "state")
    ensure_runtime_directories(settings)
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unavailable = await client.get("/health/ready")
    assert unavailable.status_code == 503

    database = Database(settings)
    try:
        upgrade_database(database.engine)
    finally:
        database.dispose()

    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ready = await client.get("/health/ready")

    assert ready.status_code == 200
    assert ready.json()["status"] == "ok"
