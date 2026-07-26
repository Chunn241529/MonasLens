# AGENTS.md — Monas Lens

## Project Overview

Monas Lens is a **local-first repository intelligence tool for AI coding agents**. It scans source repositories, parses them with Tree-sitter to extract structural information (symbols, chunks, syntax facts), builds a relationship graph (imports, calls, inheritance), provides FTS5-based search, and compiles task-aware context for downstream AI agents. The CLI (`monas-lens`) is the primary interface; a FastAPI server exists for health endpoints only.

## Essential Commands

All commands use **uv** as the package manager. The project targets **Python 3.12** exclusively.

```bash
# Install dependencies (locked)
uv sync --locked --all-groups

# Run the CLI locally
uv run monas-lens --help
uv run python -m monas_lens --help
uv run monas-lens context resolve "Explain ContextCompiler.resolve" --no-git-diff --json
uv run monas-lens mcp

# Quality checks (mirrors CI exactly)
uv run ruff format --check .    # formatting
uv run ruff check .             # linting
uv run ruff format .            # auto-fix formatting
uv run pyright                  # type checking (strict mode)

# Tests (85% branch coverage minimum enforced)
uv run pytest                          # full suite
uv run pytest tests/test_search.py     # single file
uv run pytest -k "test_name"           # by pattern
uv run pytest --no-cov                 # skip coverage (faster iteration)

# Build package
uv build
```

## Architecture

### Data Flow Pipeline

```
Repository on disk
    → Scanner (filesystem walk + gitignore + language detection)
    → Parser (Tree-sitter extraction → symbols, chunks, syntax facts)
    → StructuralStore (SQLite persistence via SQLAlchemy)
    → GraphBuilder (normalize facts → resolve relationships → relationship table)
    → SearchService (SQLite FTS5 projection over symbols + chunks)
    → GraphService / Retrieval (query-time traversal + context compilation)
```

### Key Modules

| Module | Responsibility |
|---|---|
| `cli.py` | Typer CLI with subcommands: `init`, `doctor`, `repo`, `index`, `search`, `graph` |
| `config.py` | `Settings` model (Pydantic). Precedence: CLI flags > `MONAS_LENS_*` env vars > TOML config > defaults |
| `repositories.py` | `RepositoryService` — register/activate/list repositories. One active repo at a time (SQLite partial unique index) |
| `indexing/scanner.py` | `RepositoryScanner` — deterministic filesystem walk, respects `.gitignore` layers, skips binary/oversized/generated files |
| `indexing/service.py` | `IndexService` — orchestrates scan → parse → store → graph refresh. Incremental: only re-parses files whose content hash changed |
| `indexing/store.py` | `StructuralStore` — atomic upsert/delete of files, symbols, chunks, facts, search documents |
| `indexing/identity.py` | `stable_id()` — deterministic SHA-256 IDs from content parts. Used everywhere for primary keys |
| `parsing/base.py` | `TreeSitterAdapter` abstract base — shared Tree-sitter traversal, symbol/fact extraction, chunk building |
| `parsing/languages.py` | Language-specific adapters: `PythonAdapter`, `JavaScriptAdapter`, `TypeScriptAdapter`, `TsxAdapter`, `DartAdapter` |
| `parsing/registry.py` | `ParserRegistry` — lazy-loads Tree-sitter grammars via `tree-sitter-language-pack` |
| `graph/builder.py` | `GraphBuilder` — incremental graph construction from syntax facts. Resolves imports/calls/inheritance to file/symbol endpoints |
| `graph/normalization.py` | Language-aware normalization of import paths and symbol references |
| `graph/service.py` | `GraphService` — cycle-safe BFS traversal for `neighbors` and `traverse` queries |
| `search/service.py` | `SearchService` — exact symbol name match + FTS5 lexical search with BM25 ranking |
| `retrieval/contracts.py` | Phase 4 context compilation contracts (TaskContextRequest, ContextBundle, etc.) |
| `retrieval/resolver.py` | `resolve_task()` — deterministic task parsing, action classification, query planning |
| `retrieval/retriever.py` | `ParallelRetriever` — bounded concurrent lexical/graph retrieval and targeted widening |
| `retrieval/ranker.py` | Deterministic evidence scoring, identity deduplication, and stable candidate ranking |
| `retrieval/confidence.py` | Versioned confidence scoring, missing-role detection, and one-pass widening gate |
| `retrieval/token_estimator.py` | `HeuristicTokenEstimator` — dependency-free token estimation, budget allocation, cropping |
| `retrieval/bundle.py` | `ContextBundleBuilder` — indexed-chunk materialization, content deduplication, role-aware budget selection, and deterministic bundle assembly |
| `retrieval/compiler.py` | `ContextCompiler` — Phase 4 orchestration entry point: resolve, retrieve, confidence/widen, materialize, budget, bundle |
| `retrieval/validation.py` | Conservative manifest-based validation suggestions represented as display-only argument arrays |
| `mcp/server.py` | FastMCP stdio transport exposing the four read-only Community tools |
| `mcp/service.py` | Transport-independent MCP tool facade over the Context Compiler, impact analyzer, and output compressor |
| `mcp/impact.py` | Bounded current-diff impact analysis over indexed symbols and relationships |
| `mcp/compression.py` | Deterministic bounded command-output compression preserving failures and summaries |
| `db/session.py` | `Database` — owns SQLAlchemy engine, short-lived sessions, SQLite WAL mode + foreign keys |
| `db/migration.py` | Programmatic Alembic migrations (no `alembic` CLI needed) |
| `db/models.py` | SQLAlchemy models: `RepositoryModel`, `FileModel`, `SymbolModel`, `ChunkModel`, `SyntaxFactModel`, `SearchDocumentModel`, `RelationshipModel`, `ResolutionDiagnosticModel`, `IndexRunModel` |
| `errors.py` | `MonasLensError` with stable `ErrorCode` enum. CLI maps error codes to exit codes |
| `locking.py` | File-based per-repository lock (`filelock`) prevents concurrent index operations |
| `health.py` | Liveness/readiness checks used by FastAPI endpoints and `doctor` command |

### Database

- **SQLite** with WAL journal mode and foreign keys enabled (set per-connection via PRAGMA events)
- **Alembic** for schema migrations, invoked programmatically (not via CLI)
- Migrations live in `src/monas_lens/db/migrations/versions/`
- Database file defaults to `{data_dir}/monas_lens.db`

### Supported Languages

Python, JavaScript, TypeScript, TSX, Dart. Extension mapping in `indexing/scanner.py:22-34`.

## Code Patterns and Conventions

### Type Safety

- **Pyright strict mode** — all code must pass `pyright` with `typeCheckingMode = "strict"`
- All public models use `ConfigDict(frozen=True)` (immutable Pydantic models)
- Dataclasses use `frozen=True, slots=True`
- `from __future__ import annotations` at the top of every module

### Error Handling

- All domain errors use `MonasLensError(ErrorCode.XXX, "message", details={...})`
- Error codes are stable strings from `ErrorCode` enum — never change existing values
- CLI maps error codes to numeric exit codes in `_EXIT_CODES` dict (`cli.py:49-62`)
- JSON error output goes to **stderr** (not stdout); normal JSON output goes to **stdout**

### CLI Output

- Every command supports `--json` for machine-readable output
- Human-readable output uses `typer.echo()`, JSON uses `json.dumps()` to stdout
- `_emit()` helper handles both modes; `_command_errors()` context manager catches `MonasLensError` and formats errors

### Session/Database Pattern

```python
# Always use context manager, always dispose engine when done
with database.session() as session:
    # work with session
    session.commit()  # explicit commit on success
# session auto-rollback on exception, auto-close on exit
```

### ID Generation

All primary keys use `stable_id(*parts)` from `indexing/identity.py` — deterministic SHA-256 hex digests. Never use UUIDs for entity IDs (UUIDs are only used for `IndexRunModel.id` and `RepositoryModel.id`).

### Testing Patterns

- Fixtures in `conftest.py`: `settings` (uses `tmp_path`), `database` (creates + migrates + disposes)
- CLI tests use `typer.testing.CliRunner` and set `MONAS_LENS_DATA_DIR` via `env` parameter
- Tests create temporary repositories with inline `write_text()` calls, never reference real repos
- Coverage: 85% branch minimum (`--cov-fail-under=85`), `__main__.py` and migration files excluded
- The `database` fixture handles full lifecycle — don't manually create/dispose in tests

### Ruff Configuration

- Line length: 100
- Selected rule sets: B (bugbear), E (pycodestyle), F (pyflakes), I (isort), PTH (pathlib), RUF (ruff-specific), SIM (simplify), UP (pyupgrade)
- `src` layout: source in `src/monas_lens/`, tests in `tests/`

## Gotchas

1. **SQLite partial unique index**: Only one repository can be `is_active = 1` at a time. The index is `ux_repositories_one_active` with `WHERE is_active = 1`. Activating a new repo deactivates all others first.

2. **Frozen Settings**: `Settings` model is `frozen=True`. To modify paths after construction (in the validator), use `object.__setattr__()` — see `config.py:73-74`.

3. **Graph incremental rebuild**: `GraphBuilder.refresh()` uses a key-based diffing strategy. It snapshots symbol/path keys before changes, then only re-resolves facts whose dependency keys overlap with changed paths. This is critical for performance — don't naively rebuild all relationships.

4. **Scanner ignores symlinks**: `RepositoryScanner` skips all symlinks unconditionally (`indexing/scanner.py:137`).

5. **Binary detection**: Files are probed with the first `binary_probe_bytes` (default 8192) for null bytes. Files containing `\x00` are skipped as binary.

6. **Generated file suffixes**: Files matching patterns like `*.g.dart`, `*.freezed.dart`, `*.min.js` are automatically excluded from indexing.

7. **Test detection**: Symbols whose names start with `test_`/`test` or end with `Test`/`Tests` get `metadata["is_test"] = True`. Test files get `TESTED_BY` relationships automatically.

8. **FTS5 search**: Search uses SQLite FTS5 with BM25 ranking. Exact symbol name matches always rank above FTS results. Query terms are prefixed with `"term"*` for prefix matching.

9. **CLI exit codes**: Not standard — exit code 2 = config/validation error, 3 = repo not found, 4 = locked, 5 = database issue, 6 = parser unavailable, 7 = index failed. See `cli.py:49-62`.

10. **Tree-sitter version pin**: `tree-sitter-language-pack==0.13.0` is pinned exactly. Upgrading may break parser initialization.

11. **`pathspec` for gitignore**: The scanner uses `pathspec.gitignore.GitIgnoreSpec` (not the system git binary) to evaluate `.gitignore` rules. Nested `.gitignore` files create stacked layers.

12. **Operation correlation**: All log output includes an `operation_id` (UUID) via `ContextVar`. Use `operation_context()` to set one for a block of work.

13. **Repository identifier flexibility**: Most commands accept either a repository UUID or a filesystem path as the `identifier` argument. The `_find()` method tries UUID first, then canonical path resolution.

14. **Alembic runs programmatically**: Don't invoke `alembic` CLI. Use `upgrade_database(engine)` / `downgrade_database(engine, revision)` from `db/migration.py`.

15. **MCP stdio owns stdout**: `monas-lens mcp` must write only protocol messages to stdout. Logs
    and startup failures belong on stderr; repository-backed tools use short-lived database
    lifecycles.

16. **MCP SDK major pin**: Keep `mcp>=1.27,<2` until a dedicated v2 migration is approved and
    validated. Do not relax the upper bound during routine dependency updates.
