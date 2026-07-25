# Phase 3 Search and Graph Validation

Validated: 2026-07-24  
Scope: P3-01 through P3-08

## Delivered

- Reversible migrations `0003_search_index` and `0004_relationship_graph`.
- Atomic SQLite FTS5 projection maintenance and migration backfill.
- Exact symbol lookup followed by bounded, repository-scoped lexical ranking.
- Deterministic normalization for Python, JavaScript, TypeScript, TSX, and Dart facts.
- Conservative `imports`, `calls`, `inherits`, `implements`, `tested_by`, and `configured_by`
  relationships.
- Explicit unresolved, ambiguous, and unsupported diagnostics instead of guessed edges.
- Dependency-key graph refresh for changed sources and affected inbound facts.
- Bounded, cycle-safe graph neighbors and traversal services with human and JSON CLI output.
- Mixed-language lifecycle tests and a repeatable search/graph benchmark.

## Quality and packaging gates

- Ruff format: passed, 58 files checked.
- Ruff lint: passed.
- Pyright strict mode: `0 errors`, `0 warnings`.
- Pytest: `81 passed`, `1 skipped`.
- Coverage: `89.76%`, above the required `85%`.
- `uv lock --check`: passed with 46 packages.
- `uv build`: source distribution and wheel built successfully.
- `git diff --check --no-ext-diff`: passed; Git reported only Windows line-ending conversion
  warnings.
- The wheel installed offline into a temporary isolated Python 3.12 environment.
- The isolated wheel initialized a database, indexed this repository, returned FTS results, and
  traversed a graph edge. That smoke run indexed 58 files and built 903 relationships.

The skipped test is the existing symlink test on Windows, where this process cannot create a
symlink. It remains enabled for Linux CI.

## Behavioral evidence

- Exact lookup and FTS ranking are deterministic and repository-scoped.
- Python, JavaScript, TypeScript, TSX, and Dart symbols are searchable from one mixed fixture.
- Unique import, basic call, inheritance, implementation, test, and configuration targets resolve.
- Ambiguous repository-wide symbols create diagnostics and no speculative edge.
- A no-op run reparses zero files and refreshes zero graph facts.
- A one-file update replaces lexical terms and refreshes its directly or inbound-affected graph
  facts.
- File rename and deletion remove stale lexical records and graph edges.
- Invalid UTF-8 preserves last-known-good structural, lexical, and graph records.
- Restoring valid source clears stale state and rebuilds the affected search and graph records.
- Graph queries remain isolated when repositories contain the same source symbol names.
- Traversal is deterministic, cycle-safe, relation-filtered, direction-aware, depth-bounded, and
  result-capped.
- Indexed-data downgrade through `0004` to `0002`, followed by upgrade to head, preserves
  structural data and backfills lexical records.

## Local benchmark

Run:

```console
uv run python benchmarks/phase3_search_graph.py --iterations 20
```

Measured on Windows 11 with Python 3.12.7 against the benchmark's deterministic seven-file
fixture:

| Operation | Median | p95 |
|---|---:|---:|
| Exact symbol lookup | 0.728 ms | 0.878 ms |
| FTS ranking | 0.652 ms | 0.729 ms |
| One-hop graph query | 1.969 ms | 2.190 ms |

Index measurements:

| Metric | Result |
|---|---:|
| Full index | 138.021 ms |
| Full graph build | 11.858 ms |
| One-file incremental index | 47.909 ms |
| Incremental graph refresh | 6.636 ms |
| Incrementally refreshed facts | 8 |
| Materialized relationships | 9 |

These measurements are a local regression baseline, not a cross-machine performance guarantee.

## Recovery guidance

- If `index status` reports `graph_dirty: true`, run `monas-lens index build`; a dirty graph
  triggers a full graph refresh without forcing unchanged source files to reparse.
- If a file is stale after a read or parse failure, fix the source and run `index build`.
  `index retry-failed` explicitly retries unchanged stale files.
- If the database is behind the packaged migration head, run `monas-lens init` to upgrade it.
- Use `index status --json` to inspect unresolved, ambiguous, and unsupported graph diagnostic
  counts.
- Ambiguous targets require source-level disambiguation or a more specific query; Monas Lens will
  not guess an edge.

## Known limitations

- Source files must be UTF-8, and symlinks are skipped.
- Import and call resolution is static, repository-local, and intentionally conservative.
- Dynamic dispatch, runtime module loading, generated dependency injection, and whole-program call
  analysis are not modeled.
- Test recognition and supported configuration access forms are syntax-based.
- Background watching, embeddings, semantic/hybrid ranking, context bundles, and MCP are deferred.
