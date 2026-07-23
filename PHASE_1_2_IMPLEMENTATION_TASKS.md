# Monas Lens — Phase 1–2 Implementation Backlog

Status: Ready for execution  
Source: `Monas_Lens_Full_Plan_v2.md`  
Baseline: Greenfield workspace; only `.monascode/.cron-lock` currently exists.

## Goal

Deliver an installable Python 3.12 Community package that can:

1. initialize local application state;
2. register and select one active repository;
3. expose deterministic CLI and health diagnostics;
4. scan repository files safely while respecting ignore rules;
5. parse Python, JavaScript, TypeScript, and Dart with Tree-sitter;
6. persist normalized files, symbols, syntax facts, and syntax-aware chunks;
7. incrementally re-index only added, changed, and deleted files; and
8. pass formatting, linting, type checking, unit tests, integration tests, and package smoke tests.

Phase 2 is complete only when a second unchanged index run performs zero parses and a one-file edit replaces only that file's structural records.

## Confirmed Constraints

- Runtime: Python 3.12.
- API foundation: FastAPI.
- Validation and settings: Pydantic v2.
- Metadata store: SQLite.
- Parser: Tree-sitter.
- Initial languages: Python, JavaScript, TypeScript, and Dart.
- Quality gates: Ruff formatting, Ruff lint, Pyright, and pytest.
- Local-first: repository source must never leave the machine.
- Community supports one active repository.
- Phase 1–2 must not implement FTS5 retrieval, graph traversal, Qdrant, embeddings, reranking, MCP tools, Pro features, licensing, billing, SePay, or Team features.

## Architecture Decisions

These decisions should be recorded as short ADRs before implementation starts.

| Area | Decision |
|---|---|
| Package layout | Use `src/monas_lens/` with tests under `tests/`. |
| CLI | Use Typer with stable commands, explicit exit codes, and optional `--json` output. |
| API | Use a side-effect-free FastAPI application factory. Health endpoints are diagnostic foundations, not a requirement for users to run a web server. |
| Settings | Use Pydantic Settings with precedence: CLI override, environment, local config, defaults. |
| Database | Use synchronous SQLAlchemy 2 and Alembic over SQLite; enable foreign keys, WAL mode, and a busy timeout. |
| Repository identity | Store a generated repository ID and a unique canonical absolute path. Keep exactly one active repository in Community. |
| Structural identity | Use deterministic SHA-256 keys derived from repository-relative path, language, symbol kind, qualified name, and disambiguator. |
| Source paths | Persist normalized POSIX-style repository-relative paths; never persist user-controlled paths as executable shell text. |
| Ignore engine | Implement Git-style matching with nested `.gitignore`, negation, directory rules, and explicit default exclusions. |
| Symlinks | Skip symlinks in Phase 2 and report the skip count; never traverse outside the registered root. |
| Parser boundary | Hide Tree-sitter and grammar package APIs behind a language adapter registry. Pin compatible versions after a four-language smoke spike. |
| Failed parses | Preserve the last known-good structural records, record the new observed hash and parse error, and mark the file stale. |
| Incremental writes | Parse outside the transaction, then atomically replace one file's structural records. |
| Concurrent indexing | Permit one indexing run per repository using a cross-platform file lock. |
| Phase 3 preparation | Persist unresolved syntax facts such as imports and calls; do not resolve them into graph edges yet. |

## Scope

### In Scope

- Project and package bootstrap.
- Runtime configuration and application-data paths.
- Structured logging and domain errors.
- SQLite connection management and migrations.
- Repository add, list, select, remove, and status operations.
- CLI shell and JSON output contracts.
- FastAPI liveness and readiness checks.
- Safe repository walking, ignore rules, language detection, binary/generated-file filtering, and hashing.
- Tree-sitter runtime adapters and four language extractors.
- Normalized symbol, chunk, and unresolved syntax-fact contracts.
- Incremental indexing, failure isolation, stale-record handling, and index-run metrics.
- Unit, integration, packaging, and cross-platform CI checks.

### Out of Scope

- File watching or a background indexing daemon.
- SQLite FTS5 search and ranking.
- Resolved import, call, test, or configuration graphs.
- Semantic embeddings, Ollama, Qdrant, and reranking.
- Task resolution, context bundles, confidence scoring, and token estimation.
- MCP stdio and coding-agent integrations.
- Patch impact analysis.
- Pro engine, telemetry dashboard, licensing, payment, and cloud services.

## Definition of Ready

A task is ready when:

- all dependencies listed for it are complete;
- its data and command contracts are documented;
- acceptance tests are identified;
- no unresolved architecture decision changes its public contract; and
- fixture inputs needed by the task are available.

## Definition of Done

Every task must:

- include production implementation with no placeholders;
- include unit or integration tests for success, failure, and relevant edge cases;
- avoid unrelated changes;
- use typed public interfaces;
- emit actionable errors without leaking source content or secrets;
- update user or developer documentation when it changes a command or contract; and
- pass `ruff format --check .`, `ruff check .`, `pyright`, and `pytest`.

Task sizes are relative: S is localized, M spans one component, and L spans multiple collaborating components.

---

## Phase 1 — Foundation

### P1-01 — Bootstrap the Community package

Size: M  
Dependencies: None

Deliverables:

- Create `pyproject.toml` for Python 3.12 with runtime and development dependency groups.
- Create the `src/monas_lens/` package, version module, CLI entry point, and test layout.
- Configure Ruff, Pyright, pytest, coverage, and build metadata.
- Add `.gitignore`, `.env.example`, Apache-2.0 license, and a minimal README.
- Add Windows and Linux CI jobs for Python 3.12.

Acceptance criteria:

- A wheel and source distribution build successfully.
- Installing the wheel in a clean environment exposes `monas-lens --version`.
- Importing `monas_lens` causes no filesystem, database, parser, or network side effects.
- All four mandatory quality commands run from the repository root.

### P1-02 — Implement settings and safe path resolution

Size: M  
Dependencies: P1-01

Deliverables:

- Define typed settings for application data, database, logging, active repository, scanner limits, and parser options.
- Resolve platform-specific user data and cache directories.
- Support environment overrides with the `MONAS_LENS_` prefix.
- Add canonical-path and repository-relative-path helpers.
- Reject nonexistent roots, non-directories, NUL bytes, and paths that escape a registered repository.

Acceptance criteria:

- Settings precedence is deterministic and covered by tests.
- Windows drive-letter casing and path separators normalize consistently.
- Relative source paths cannot escape the repository root.
- Diagnostics can show effective non-secret settings without dumping environment variables.

### P1-03 — Add domain errors and structured logging

Size: S  
Dependencies: P1-01

Deliverables:

- Define a small domain error hierarchy with stable machine-readable error codes.
- Configure human-readable console logs and structured JSON logs.
- Attach an operation ID to repository and indexing operations.
- Redact repository source, environment values, and secrets from logs.
- Map domain errors to CLI exit codes and future API error responses.

Acceptance criteria:

- Expected user errors do not print Python tracebacks by default.
- `--debug` enables tracebacks without changing exit codes.
- Tests verify error codes and redaction behavior.

### P1-04 — Create SQLite infrastructure and migrations

Size: M  
Dependencies: P1-01, P1-02, P1-03

Deliverables:

- Implement connection/session ownership and transaction helpers.
- Enable `PRAGMA foreign_keys=ON`, WAL mode, and a configured busy timeout.
- Add Alembic migration execution to initialization.
- Create `repositories` and `index_runs` tables.
- Add uniqueness for canonical repository paths and indexes for common status queries.

Minimum repository fields:

- `id`, `canonical_path`, `display_name`, `is_active`, `is_git_repository`;
- `index_state`, `last_indexed_at`, `last_error_code`;
- `created_at`, `updated_at`.

Acceptance criteria:

- Fresh database creation and upgrade from an earlier migration are tested.
- Foreign-key enforcement and transaction rollback are tested.
- More than one active repository cannot be committed.
- Database setup is idempotent.

### P1-05 — Implement repository registration

Size: M  
Dependencies: P1-02, P1-04

Deliverables:

- Add repository service methods: add, list, get, activate, remove, and status.
- Canonicalize paths before uniqueness checks.
- Detect Git metadata without requiring Git for the structural index.
- Make re-adding the same canonical path idempotent.
- Prevent removal while an index operation holds the repository lock.

Acceptance criteria:

- Adding the same path through equivalent path spellings returns one repository.
- Activating one repository deactivates the previous repository atomically.
- Removing a repository deletes only Monas Lens metadata, never source files.
- Missing, unreadable, and moved repository roots return distinct actionable errors.

### P1-06 — Build the CLI foundation

Size: M  
Dependencies: P1-03, P1-05

Deliverables:

- Implement:
  - `monas-lens init`
  - `monas-lens doctor`
  - `monas-lens repo add <path>`
  - `monas-lens repo list`
  - `monas-lens repo use <id-or-path>`
  - `monas-lens repo remove <id-or-path>`
  - `monas-lens repo status`
- Support human-readable and `--json` output.
- Document stable exit codes for validation, not found, conflict, lock, database, and internal failures.

Acceptance criteria:

- Every command has CLI-runner tests for success and failure.
- JSON output conforms to typed response models and contains no incidental log text.
- `init` is safe to run repeatedly.
- Destructive metadata removal requires `--yes` when a terminal is non-interactive.

### P1-07 — Add the FastAPI application and health checks

Size: S  
Dependencies: P1-03, P1-04

Deliverables:

- Implement a `create_app(settings)` application factory.
- Add `/health/live` for process liveness.
- Add `/health/ready` for settings, writable application state, database connectivity, and migration state.
- Return typed Pydantic response models and operation IDs.

Acceptance criteria:

- Importing or constructing the app does not bind a port or launch background work.
- Liveness remains independent of repository availability.
- Readiness fails with a non-2xx response and stable reason code when storage or migration checks fail.
- API tests cover healthy and unhealthy states.

### P1-08 — Close the Phase 1 quality gate

Size: M  
Dependencies: P1-01 through P1-07

Deliverables:

- Add a clean-environment installation smoke test.
- Add CLI-to-database integration tests.
- Document installation, initialization, repository registration, health diagnostics, and local data locations.
- Record the approved Phase 2 database and parser contracts as ADRs.

Phase 1 exit criteria:

- A new user can install, initialize, register a repository, select it, and run diagnostics.
- Repeated initialization and registration are idempotent.
- Database migration and rollback tests pass.
- Windows and Linux CI pass all mandatory quality checks.
- No Phase 2 parser dependency is imported by a Phase 1 command.

---

## Phase 2 — Structural Index

### P2-01 — Define structural-index contracts and schema

Size: M  
Dependencies: P1-04, P1-08

Deliverables:

- Add migrations for `files`, `symbols`, `chunks`, and `syntax_facts`.
- Define typed immutable extraction contracts separate from ORM models.
- Add cascade behavior from repository to files and from files to structural records.
- Store both `observed_hash` and `indexed_hash` to represent stale last-known-good data.

Minimum file fields:

- repository ID, normalized relative path, language, byte size, modification time;
- observed hash, indexed hash, encoding, parse status, parse error code;
- indexed timestamp and structural record counts.

Minimum symbol fields:

- deterministic ID, file ID, language, kind, name, qualified name, signature;
- parameters, return type, docstring summary, export visibility;
- start/end byte and start/end line.

Minimum chunk fields:

- deterministic ID, file ID, optional symbol ID, kind, source text, content hash;
- start/end byte and start/end line;
- deterministic structural summary metadata.

Minimum syntax-fact fields:

- deterministic ID, file ID, optional source symbol ID, fact kind;
- unresolved target text, source range, and typed metadata.

Acceptance criteria:

- Constraints reject duplicate structural identities within a file.
- Deleting a file cascades to all structural records.
- Migration downgrade/upgrade is tested against fixture data.
- ORM models do not leak into parser interfaces.

### P2-02 — Implement ignore and source-safety policy

Size: L  
Dependencies: P1-02

Deliverables:

- Implement root and nested `.gitignore` rules, comments, escaped characters, negation, anchored patterns, and directory-only patterns.
- Always exclude `.git`, Monas Lens local state, common dependency trees, build outputs, minified files, generated files, and configured exclusions.
- Detect binary files using a bounded content probe plus extension hints.
- Skip symlinks and record why each path was excluded.
- Apply configurable maximum file size before loading full contents.

Acceptance criteria:

- Golden tests cover nested ignore files and re-inclusion with negation.
- Ignore outcomes match Git behavior for the supported fixture cases.
- A symlink to a file outside the repository is never opened.
- Binary, oversized, generated, dependency, and supported source files are classified deterministically.

### P2-03 — Build the repository scanner and language detector

Size: L  
Dependencies: P2-02

Deliverables:

- Walk the registered root without following symlinks.
- Produce normalized, deterministically ordered file candidates.
- Detect Python, JavaScript, TypeScript/TSX, and Dart from explicit extension maps.
- Stream SHA-256 hashing without loading entire files into memory.
- Emit scan counters for visited, eligible, ignored, binary, oversized, unsupported, and failed files.

Acceptance criteria:

- Scanner output is stable across repeated runs.
- A per-file permission or read error is reported without aborting the scan.
- Hashes change when content changes and do not depend on modification time.
- Tests cover empty repositories, deep trees, Unicode paths, long paths, and mixed-language fixtures.

### P2-04 — Create the Tree-sitter adapter registry

Size: M  
Dependencies: P1-01

Deliverables:

- Define a runtime-independent `LanguageAdapter` interface.
- Load a pinned parser and grammar per supported language.
- Normalize Tree-sitter byte and point ranges into shared value objects.
- Add grammar compatibility checks and a `doctor` parser diagnostic.
- Permit error-tolerant trees while surfacing `has_error` and error-node counts.

Acceptance criteria:

- All four grammars parse a minimal fixture in a clean installation.
- Grammar loading is lazy and has no import-time model or network work.
- An unavailable grammar fails only that language and returns a stable error code.
- Parser API/version drift is isolated to the adapter layer.

### P2-05 — Implement Python structural extraction

Size: L  
Dependencies: P2-04, P2-08

Deliverables:

- Extract modules, classes, functions, async functions, methods, imports, constants, parameters, return annotations, decorators, and docstrings.
- Derive qualified names from lexical nesting.
- Identify test functions/classes and common route decorators as typed metadata.
- Capture unresolved call, inheritance, decorator, and import facts.

Acceptance criteria:

- Fixtures cover nested functions, async methods, decorated functions, aliases, relative imports, type annotations, multiline signatures, and syntax errors.
- Extracted ranges slice back to the intended UTF-8 source bytes.
- Qualified names and deterministic IDs remain stable when unrelated lines are inserted.
- Partial syntax errors do not create ranges outside the source buffer.

### P2-06 — Implement JavaScript and TypeScript extraction

Size: L  
Dependencies: P2-04, P2-08

Deliverables:

- Extract functions, arrow functions assigned to names, classes, methods, constructors, constants, imports, exports, and calls.
- Extract TypeScript interfaces, type aliases, enums, parameter types, and return types.
- Support `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`, `.tsx`, `.mts`, and `.cts`.
- Identify common test declarations and route-call patterns as typed metadata.

Acceptance criteria:

- Fixtures cover ESM, CommonJS, default/named exports, overload declarations, generics, JSX/TSX, async functions, and anonymous callbacks.
- TypeScript overloads have deterministic disambiguators.
- Export and call facts preserve unresolved target text for Phase 3.
- Malformed source is isolated to the affected file.

### P2-07 — Implement Dart structural extraction

Size: L  
Dependencies: P2-04, P2-08

Deliverables:

- Extract libraries, classes, mixins, extensions, enums, top-level functions, methods, constructors, constants, imports, exports, and part directives.
- Capture parameter and return types, annotations, inheritance, implementation, and call facts.
- Identify common test declarations and route annotations as typed metadata.

Acceptance criteria:

- Fixtures cover named constructors, factory constructors, extensions, mixins, async functions, null-safety types, imports with aliases, and part files.
- Qualified names and source ranges are deterministic.
- Unsupported new syntax produces a file-level diagnostic without aborting the index run.

### P2-08 — Normalize symbols, signatures, and deterministic IDs

Size: M  
Dependencies: P2-01, P2-04

Deliverables:

- Define shared symbol kinds and language-specific extension metadata.
- Normalize qualified names, signatures, parameter lists, return types, and docstring summaries.
- Generate deterministic IDs and disambiguate overloads or same-name declarations.
- Define canonical ordering for symbols and syntax facts.

Acceptance criteria:

- IDs are stable across process runs and unrelated line shifts.
- Moving a symbol to another file intentionally changes its ID.
- Same-name declarations in one scope do not collide.
- Contract tests run against every language adapter.

### P2-09 — Implement syntax-aware chunking

Size: L  
Dependencies: P2-05, P2-06, P2-07, P2-08

Deliverables:

- Create chunks for functions, methods, small classes, test cases, deterministic module summaries, and meaningful configuration-like sections found in supported source.
- Preserve exact source ranges and symbol ownership.
- Split oversized classes or functions only at valid child-node boundaries.
- Deduplicate chunks by content hash within a repository.
- Do not add arbitrary text overlap.

Acceptance criteria:

- No chunk starts or ends in the middle of a UTF-8 code point.
- Chunk ranges are nested within the owning file and, when applicable, symbol.
- Repeated identical source produces one stored content identity without losing file ownership.
- Golden tests verify boundaries for all four languages.

### P2-10 — Implement atomic structural persistence

Size: L  
Dependencies: P2-01, P2-08, P2-09

Deliverables:

- Add a repository abstraction that atomically replaces one file's symbols, chunks, and syntax facts.
- Parse and validate extraction results before opening the write transaction.
- Preserve last-known-good records when parsing or validation fails.
- Delete structural records for files confirmed absent.
- Batch inserts without mixing records from different file transactions.

Acceptance criteria:

- Injected failures roll back the complete file update.
- Readers never observe half-replaced structural records.
- Re-indexing identical extraction output creates no duplicate rows.
- Deleting a source file removes all dependent records.

### P2-11 — Build the incremental indexing orchestrator

Size: L  
Dependencies: P2-03, P2-04, P2-10

Deliverables:

- Implement index states used in this phase: `pending`, `scanning`, `parsing`, `ready`, and `failed`.
- Compare scan results with stored observed/indexed hashes.
- Plan added, modified, unchanged, deleted, retryable-failed, and unsupported files.
- Parse only added, modified, and explicitly retried files.
- Track run duration, counts, skip reasons, parser errors, and the last fatal error.
- Acquire a per-repository cross-platform lock.

Acceptance criteria:

- The second unchanged run parses zero files and writes no structural rows.
- Editing one file reparses and replaces only that file.
- Deleting one file removes only that file's records.
- A failed file retains last-known-good records and is visibly stale.
- One file failure does not prevent other changed files from being committed.
- A concurrent second run exits with a stable lock-conflict error.

### P2-12 — Add indexing CLI commands and output contracts

Size: M  
Dependencies: P1-06, P2-11

Deliverables:

- Implement:
  - `monas-lens index build [<repository>]`
  - `monas-lens index build --full`
  - `monas-lens index retry-failed`
  - `monas-lens index status [<repository>]`
- Add progress output for terminals and clean JSON summaries for agents.
- Support interruption and return a non-zero exit code while preserving committed file updates.

Acceptance criteria:

- JSON output includes repository ID, run ID, state, counts, duration, stale-file count, and errors.
- `--full` reparses all eligible files without creating duplicates.
- Ctrl+C releases the repository lock and records an interrupted run.
- CLI tests cover no active repository, locked repository, partial errors, and successful no-op runs.

### P2-13 — Harden failure recovery and resource use

Size: M  
Dependencies: P2-11, P2-12

Deliverables:

- Bound file reads, parser inputs, batch sizes, and stored diagnostic lengths.
- Handle unreadable files, invalid UTF-8, files changing during hashing, deleted-during-scan files, SQLite busy errors, and disk-full failures.
- Ensure file handles, parser objects, sessions, and locks are released on every exit path.
- Never include full source text in errors or logs.

Acceptance criteria:

- Fault-injection tests cover each failure class.
- A file modified between scan and parse is deferred or retried, never committed under the wrong hash.
- Fatal storage failures mark the run failed without corrupting the previous index.
- Resource cleanup tests pass on Windows and Linux.

### P2-14 — Add end-to-end structural-index tests

Size: L  
Dependencies: P2-05 through P2-13

Deliverables:

- Create a small mixed-language fixture repository with golden structural output.
- Add end-to-end tests for first index, no-op re-index, one-file update, deletion, rename, ignore-rule change, parse failure, recovery, and full rebuild.
- Verify database constraints and cross-table counts.
- Add a wheel-install smoke test that indexes the fixture repository.

Acceptance criteria:

- Golden output is deterministic across repeated runs.
- Rename behavior is explicitly delete-plus-add; history correlation is deferred.
- Ignore-rule changes rescan affected paths.
- Package smoke tests require no network access and do not require Ollama, Qdrant, or an MCP client.

### P2-15 — Establish performance baselines and close Phase 2

Size: M  
Dependencies: P2-14

Deliverables:

- Add repeatable scanner, hash, parser, persistence, and no-op indexing benchmarks.
- Record CPU, peak memory, file counts, source bytes, symbols, chunks, and wall-clock duration.
- Document supported extensions, exclusions, known grammar limitations, local storage schema, and recovery commands.
- Produce a Phase 2 validation report.

Phase 2 exit criteria:

- Python, JavaScript, TypeScript, and Dart fixtures index successfully.
- Ignore, binary, generated-file, path containment, and symlink safety tests pass.
- A no-op run parses zero files.
- A one-file modification updates only that file's structural records.
- File deletion removes stale structural data.
- Parser failures are isolated and preserve last-known-good records.
- All quality gates pass on Windows and Linux.
- No Phase 3–10 dependency or feature is required at runtime.

---

## Recommended Pull Request Sequence

1. **PR-01 — Bootstrap:** P1-01 to P1-03.
2. **PR-02 — Local state:** P1-04 and P1-05.
3. **PR-03 — User surfaces:** P1-06 to P1-08.
4. **PR-04 — Scanner:** P2-01 to P2-04.
5. **PR-05 — Language extraction:** P2-05 to P2-09. Python, JavaScript/TypeScript, and Dart extractor work may proceed in parallel only after P2-08 contracts are frozen.
6. **PR-06 — Persistence and incremental indexing:** P2-10 to P2-13.
7. **PR-07 — Release gate:** P2-14 and P2-15.

Each pull request must be independently testable and must not depend on unmerged code from a later pull request.

## Critical Dependency Path

```text
P1-01
  -> P1-02/P1-03
  -> P1-04
  -> P1-05
  -> P1-06/P1-07
  -> P1-08
  -> P2-01/P2-02/P2-04
  -> P2-03/P2-08
  -> P2-05/P2-06/P2-07
  -> P2-09
  -> P2-10
  -> P2-11
  -> P2-12/P2-13
  -> P2-14
  -> P2-15
```

## Cross-Cutting Test Matrix

| Concern | Unit | Integration | End-to-end |
|---|---:|---:|---:|
| Settings and path containment | Required | Required | Smoke |
| Database migrations and rollback | Required | Required | Required |
| Repository registration | Required | Required | Required |
| CLI and JSON contracts | Required | Required | Required |
| Ignore semantics and symlink safety | Required | Required | Required |
| Scanner and hashing | Required | Required | Required |
| Four language adapters | Contract tests | Required | Required |
| Symbol IDs and chunk boundaries | Golden tests | Required | Required |
| Atomic replacement | Fault injection | Required | Required |
| Incremental planning | Required | Required | Required |
| Locking and interruption | Required | Required | Required |
| Packaging | N/A | Clean install | Wheel smoke |

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Tree-sitter Python bindings and language wheels expose incompatible APIs | All parsing can fail after dependency upgrades | Pin a proven compatibility set, isolate APIs behind adapters, and run a four-language clean-install smoke test. |
| Dart grammar lags current language syntax | Partial or failed extraction | Keep extraction error-tolerant, publish known limitations, and retain fixture coverage for supported syntax. |
| `.gitignore` behavior diverges from Git | Wrong files enter or leave the index | Use golden cases covering nested and negated rules and compare supported behavior with Git in tests. |
| Stable symbol IDs collide or churn on line edits | Phase 3 graph links become unreliable | Exclude line numbers from primary identity, add deterministic disambiguators, and contract-test unrelated line shifts. |
| A parse or write failure destroys the previous good index | Retrieval later returns missing context | Parse before transaction, replace one file atomically, and keep observed and indexed hashes separately. |
| Large repositories exhaust memory | Indexing becomes unusable | Stream walking and hashing, cap file size and diagnostics, and benchmark peak memory before Phase 3. |
| Windows path and lock semantics differ from Linux | Local-first launch fails for primary users | Run Windows and Linux CI, normalize canonical paths explicitly, and use a cross-platform lock abstraction. |
| Scope expands into retrieval or MCP prematurely | Structural contracts remain unstable | Enforce the out-of-scope list and require the Phase 2 exit gate before Phase 3 starts. |

## Rollback Strategy

- Keep every schema change in a reversible Alembic migration.
- Preserve source repositories as strictly read-only.
- Make repository removal delete only Monas Lens metadata.
- Keep last-known-good file records when a new parse fails.
- If a Phase 2 release is defective, reinstall the prior package and run its compatible migration downgrade or rebuild the local index from source.
- Treat local indexes as reproducible caches; never make them the sole store of user-authored data.

## First Concrete Step

Start P1-01 by initializing Git and the Python package skeleton, then land the quality toolchain before implementing settings, database, scanner, or parser behavior.
