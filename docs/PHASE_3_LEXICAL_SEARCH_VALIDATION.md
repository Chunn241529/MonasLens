# Phase 3 Lexical Search Validation

Validated: 2026-07-24  
Scope: P3-01 through P3-03 only

## Delivered

- Reversible Alembic migration `0003_search_index`.
- Foreign-keyed `search_documents` projection.
- SQLite FTS5 external-content index with insert/update/delete triggers.
- Migration backfill for existing Phase 2 files, symbols, chunks, and syntax facts.
- Atomic per-file lexical projection replacement.
- Exact symbol and qualified-name lookup.
- Ranked repository-scoped FTS search over paths, symbols, signatures, chunks, docstrings, and
  unresolved fact targets.
- Bounded query compilation that rejects raw FTS syntax.
- Typed Python response contracts and `monas-lens search` human/JSON output.

## Validation results

- Ruff format: passed, 47 files checked.
- Ruff lint: passed.
- Pyright: `0 errors`, `0 warnings`.
- Pytest: `48 passed`, `1 skipped`.
- Coverage: `87.65%`, above the required `85%`.
- `uv lock --check`: passed with 46 packages.
- `uv build`: source distribution and wheel built successfully.
- The built wheel installed in an isolated environment and exposed `monas-lens 0.1.0.dev0`.
- `git diff --check --no-ext-diff`: passed; Git reported only the existing Windows line-ending
  conversion warnings.

The skipped test is the existing symlink test on Windows, where the process cannot create a
symlink. It remains enabled on Linux CI.

## Behavioral checks

- Exact qualified-name lookup ranks before lexical results.
- Member calls remain searchable by the member segment because dots split FTS tokens.
- Underscored identifiers remain single searchable terms.
- Multi-term source search returns syntax-aware chunks.
- Search results are isolated by repository.
- A one-file update removes old terms and exposes new terms.
- File deletion removes associated lexical records.
- Downgrade to `0002_structural_index` and re-upgrade to `0003_search_index` succeed.
- Re-upgrade backfills existing structural records without reparsing source files.
- Invalid empty, punctuation-only, and out-of-range requests return
  `search_query_invalid`.

## Deferred

- Language-specific syntax-fact normalization.
- Import, call, inheritance, implementation, test, and configuration graph edges.
- Graph traversal and graph CLI inspection.
- Hybrid, semantic, and context-bundle ranking.
- Phase 3 performance baselines and isolated-wheel FTS workflow smoke test.
