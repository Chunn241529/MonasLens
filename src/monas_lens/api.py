"""FastAPI application factory and diagnostic endpoints."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status

from monas_lens import __version__
from monas_lens.config import Settings, load_settings
from monas_lens.db.session import Database
from monas_lens.health import HealthReport, liveness_report, readiness_report


def create_app(settings: Settings | None = None) -> FastAPI:
    selected_settings = settings or load_settings()
    database = Database(selected_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        yield
        database.dispose()

    app = FastAPI(title="Monas Lens", version=__version__, lifespan=lifespan)
    app.state.settings = selected_settings
    app.state.database = database

    def live() -> HealthReport:
        return liveness_report()

    def ready(response: Response) -> HealthReport:
        report = readiness_report(selected_settings, database)
        if not report.ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return report

    app.add_api_route(
        "/health/live",
        live,
        methods=["GET"],
        response_model=HealthReport,
    )
    app.add_api_route(
        "/health/ready",
        ready,
        methods=["GET"],
        response_model=HealthReport,
    )
    return app
