# Monas Lens

Monas Lens is a local-first repository intelligence and safety layer for AI coding agents.
It is designed to find focused repository context while keeping source code on the developer's
machine.

> Less context. Better code.

## Project status

Monas Lens Community is in pre-alpha development. Phase 1 and Phase 2 provide the local
application foundation and incremental structural repository index. Search, graph retrieval,
MCP integration, and Pro features are not available yet.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/) for the development workflow

## Development setup

```console
uv sync --all-groups
uv run monas-lens --version
```

Initialize Monas Lens and build a structural index:

```console
uv run monas-lens init
uv run monas-lens repo add .
uv run monas-lens doctor
uv run monas-lens index build
uv run monas-lens index status
```

Every command that returns data supports `--json` for machine-readable output.

Run the mandatory quality checks:

```console
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv build
```

## Product scope

The Community edition will provide:

- a local repository scanner;
- Tree-sitter structural extraction;
- SQLite metadata and keyword search;
- a local MCP server; and
- focused context retrieval for coding agents.

The initial structural index targets Python, JavaScript, TypeScript, and Dart.

The index currently extracts:

- modules, classes, interfaces, functions, methods, constructors, constants, and tests;
- signatures, parameters, return types, docstrings, exports, and exact source ranges;
- unresolved import, call, inheritance, implementation, route, decorator, and test facts; and
- syntax-aware function, method, class, test, and deterministic module-summary chunks.

Files are hashed with SHA-256. Unchanged files are not reparsed, changed files are replaced
atomically, deleted files are removed, and a failed parse preserves the last known-good records.

See [the Phase 1–2 implementation backlog](PHASE_1_2_IMPLEMENTATION_TASKS.md) for the active
delivery plan.

For the latest implementation state, validation evidence, and next-session starting point, see
the [session handoff](docs/SESSION_HANDOFF.md).

## Privacy

Monas Lens is local-first. Community indexing and retrieval must not upload repository source,
indexes, prompts, diffs, test output, or agent conversations.

## Current limitations

- Source files must be UTF-8.
- Symlinks are skipped rather than followed.
- Route and test recognition is syntax-based and intentionally conservative.
- Indexing is command-driven; background file watching is not implemented.
- The bundled parser set is pinned for offline, reproducible installation.
- FTS5 search, graph resolution, embeddings, retrieval ranking, and MCP are Phase 3–5 work.

## License

Monas Lens Community is licensed under the [Apache License 2.0](LICENSE).
