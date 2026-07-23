# Phase 1–2 Validation

## Delivered

Phase 1:

- Python 3.12 package, CLI entry point, dependency lock, and Windows/Linux CI.
- Validated settings, safe path helpers, structured logging, and stable error codes.
- SQLite connection ownership, WAL, foreign keys, busy timeout, and reversible Alembic migrations.
- Repository registration, activation, listing, status, and metadata-only removal.
- FastAPI liveness and readiness diagnostics.

Phase 2:

- Deterministic scanner with nested `.gitignore`, negation, default exclusions, generated and
  binary filtering, size limits, SHA-256 hashing, and symlink rejection.
- Bundled Tree-sitter parsing for Python, JavaScript, TypeScript, TSX, and Dart.
- Normalized symbols, unresolved syntax facts, exact ranges, and syntax-aware chunks.
- Atomic per-file persistence and cascade deletion.
- Incremental add, update, delete, full rebuild, failed-file retry, and last-known-good recovery.
- Per-repository locking, run state, counters, duration, stale-file reporting, and JSON CLI output.

## Exit checks

Run:

```console
uv sync --locked --all-groups
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv build
```

Behavioral checks:

- First mixed-language index parses every eligible file.
- Second unchanged index parses zero files.
- One changed file reparses only that file.
- Deleted source cascades to its symbols, chunks, and facts.
- Invalid UTF-8 records a failure while preserving the previous indexed hash and records.
- Retry and recovery clear stale state after valid source returns.
- A concurrent second index receives a stable repository-lock error.
- The built wheel installs in an isolated environment and exposes `monas-lens`.

## Local self-index baseline

Measured on the development machine on 2026-07-23:

| Metric | Full rebuild | Unchanged follow-up |
|---|---:|---:|
| Eligible source files | 43 | 43 |
| Parsed files | 43 | 0 |
| Unchanged files | 0 | 43 |
| Failed or stale files | 0 | 0 |
| Duration | 744.971 ms | 92.879 ms |

Persisted structural records:

- 315 symbols;
- 288 chunks; and
- 1,798 unresolved syntax facts.

This is a local development baseline, not a cross-machine performance guarantee.

## Deferred

- File-watcher daemon.
- SQLite FTS5 and relationship graph resolution.
- Task resolver, ranking, context bundles, confidence gate, and token analytics.
- Qdrant, Ollama embeddings, and reranking.
- MCP stdio and coding-agent integration.
- Patch impact analysis.
- Pro, licensing, payment, and Team functionality.
