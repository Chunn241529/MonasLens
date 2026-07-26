# Monas Lens

Monas Lens is a local-first repository intelligence and safety layer for AI coding agents.
It is designed to find focused repository context while keeping source code on the developer's
machine.

> Less context. Better code.

## Project status

Monas Lens Community is in pre-alpha development. Phases 1–4 provide the local application
foundation, incremental structural index, deterministic FTS5 search, conservative relationship
graph, and task-aware Context Compiler. The Phase 5 internal MCP baseline is available over stdio;
Pro features are not available.

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
uv run monas-lens search normalize_value
uv run monas-lens graph neighbors normalize_value
uv run monas-lens graph traverse normalize_value --depth 2 --relations calls,tested_by
uv run monas-lens context resolve "Explain GraphService.neighbors" --no-git-diff
uv run monas-lens mcp
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

The Community edition provides:

- a local repository scanner;
- Tree-sitter structural extraction;
- SQLite metadata, exact-symbol lookup, and ranked lexical search;
- a conservative import, call, type, test, and configuration relationship graph;
- a local MCP server; and
- focused context retrieval for coding agents.

The structural index targets Python, JavaScript, TypeScript, TSX, and Dart.

The index currently extracts:

- modules, classes, interfaces, functions, methods, constructors, constants, and tests;
- signatures, parameters, return types, docstrings, exports, and exact source ranges;
- unresolved import, call, inheritance, implementation, route, decorator, and test facts; and
- syntax-aware function, method, class, test, and deterministic module-summary chunks.

The Phase 3 graph resolves only unique repository-local targets. Use `graph neighbors` for one
hop or `graph traverse` for bounded breadth-first traversal. Both support `--direction`,
`--relations`, repository selection, result caps, and `--json`.

Files are hashed with SHA-256. Unchanged files are not reparsed, changed files are replaced
atomically, deleted files are removed, and a failed parse preserves the last known-good records.

The Context Compiler is available through `monas-lens context resolve`. It returns deterministic
JSON with ranked primary targets, bounded relationship context, confidence evidence, estimated
token accounting, relevant Git hunks, and display-only validation argument arrays.

The internal MCP server exposes four read-only tools over stdio:

- `resolve_task_context` (mandatory first discovery call);
- `expand_context` (one explicit missing relationship, returning only new content hashes);
- `analyze_patch_impact` (bounded current-diff structural impact); and
- `compress_command_output` (bounded test/build/compiler/linter/diff summaries).

See [Phase 5 internal setup](docs/PHASE_5_INTERNAL_SETUP.md) for Codex and Claude Code
configuration. MCP clients must start the server as a subprocess; do not run it behind FastAPI or
expose a network port.

See [the Phase 1–2 implementation backlog](PHASE_1_2_IMPLEMENTATION_TASKS.md),
[the Phase 3 backlog](PHASE_3_IMPLEMENTATION_TASKS.md),
[the Phase 4 backlog](PHASE_4_IMPLEMENTATION_TASKS.md), and
[the Phase 5 backlog](PHASE_5_IMPLEMENTATION_TASKS.md).

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
- FTS5 search currently covers paths, symbols, signatures, source chunks, and unresolved syntax
  facts.
- Graph resolution covers deterministic imports, basic calls, inheritance, implementation,
  test-source, and supported configuration-key links; dynamic dispatch and whole-program call
  analysis are intentionally out of scope.
- MCP currently supports local stdio only; no remote HTTP transport, OAuth, or background daemon.
- Patch impact is bounded to the current Git diff and conservative indexed relationships.
- Embeddings, semantic/hybrid retrieval ranking, persistent discovery-call state, and Pro features
  are not implemented.

## License

Monas Lens Community is licensed under the [Apache License 2.0](LICENSE).
