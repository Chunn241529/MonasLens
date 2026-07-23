"""Programmatic Alembic migration helpers."""

from __future__ import annotations

from importlib.resources import files

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine


def alembic_config() -> Config:
    config = Config()
    migration_path = files("monas_lens.db").joinpath("migrations")
    config.set_main_option("script_location", str(migration_path))
    return config


def upgrade_database(engine: Engine) -> None:
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def downgrade_database(engine: Engine, revision: str) -> None:
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, revision)


def database_revision(engine: Engine) -> tuple[str | None, str | None]:
    config = alembic_config()
    expected = ScriptDirectory.from_config(config).get_current_head()
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    return current, expected


def database_is_current(engine: Engine) -> bool:
    current, expected = database_revision(engine)
    return current is not None and current == expected
