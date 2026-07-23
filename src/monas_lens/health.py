"""Application liveness and readiness diagnostics."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from monas_lens.config import Settings
from monas_lens.db.migration import database_is_current, database_revision
from monas_lens.db.session import Database


class CheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    ok: bool
    detail: str


class HealthReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok", "not_ready"]
    checks: tuple[CheckResult, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ok"


def liveness_report() -> HealthReport:
    return HealthReport(
        status="ok",
        checks=(CheckResult(name="process", ok=True, detail="running"),),
    )


def readiness_report(settings: Settings, database: Database) -> HealthReport:
    checks = [
        CheckResult(
            name="data_directory",
            ok=settings.data_dir.is_dir() and os.access(settings.data_dir, os.R_OK | os.W_OK),
            detail=str(settings.data_dir),
        )
    ]
    try:
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        current, expected = database_revision(database.engine)
        checks.append(
            CheckResult(
                name="database",
                ok=database_is_current(database.engine),
                detail=f"revision={current or 'none'}, expected={expected or 'none'}",
            )
        )
    except SQLAlchemyError:
        checks.append(CheckResult(name="database", ok=False, detail="connection failed"))
    ready = all(check.ok for check in checks)
    return HealthReport(status="ok" if ready else "not_ready", checks=tuple(checks))
