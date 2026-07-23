"""SQLite engine and transaction ownership."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from typing import cast

from sqlalchemy import Engine, event
from sqlalchemy.engine import URL, create_engine
from sqlalchemy.orm import Session, sessionmaker

from monas_lens.config import Settings


class Database:
    """Own the SQLAlchemy engine and short-lived sessions."""

    def __init__(self, settings: Settings) -> None:
        if settings.database_path is None:
            raise ValueError("database_path must be configured")
        url = URL.create("sqlite+pysqlite", database=str(settings.database_path))
        timeout_seconds = settings.sqlite_busy_timeout_ms / 1_000
        self.engine = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": timeout_seconds},
            future=True,
        )
        _configure_sqlite(self.engine, settings.sqlite_busy_timeout_ms)
        self._session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
            class_=Session,
        )

    @contextmanager
    def session(self) -> Generator[Session]:
        session = self._session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()


def _configure_sqlite(engine: Engine, busy_timeout_ms: int) -> None:
    def set_pragmas(dbapi_connection: object, _connection_record: object) -> None:
        connection = cast(sqlite3.Connection, dbapi_connection)
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={busy_timeout_ms:d}")
        finally:
            cursor.close()

    event.listen(engine, "connect", set_pragmas)
