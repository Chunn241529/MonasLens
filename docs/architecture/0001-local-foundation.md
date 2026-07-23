# ADR 0001 — Local application foundation

Status: Accepted

## Context

Monas Lens Community needs an installable local application that can evolve from CLI diagnostics
into MCP stdio without requiring users to run a web server or Docker. Local metadata must be
migratable, recoverable, and isolated from repository source.

## Decision

- Package Monas Lens as a Python 3.12 `src`-layout project.
- Use Typer for stable CLI commands and optional JSON output.
- Use a side-effect-free FastAPI application factory for diagnostic endpoints.
- Load configuration with this precedence: explicit overrides, environment, TOML, defaults.
- Store local state in platform-specific application-data directories.
- Use synchronous SQLAlchemy 2 with SQLite, WAL, foreign keys, and a busy timeout.
- Use Alembic for reversible schema migrations.
- Allow multiple registered repositories but exactly one active Community repository.
- Treat registered repository source as read-only.

## Consequences

- Importing the package does not create files, connect to a database, bind a port, or start work.
- `monas-lens init` is the explicit local-state creation boundary.
- CLI commands can later be reused behind MCP without changing database ownership.
- SQLite is sufficient for the single-user local workload and requires no external service.
