# Monas Lens — Phase 3 Search and Graph Backlog

Status: Delivered in the current working tree  
Source: `Monas_Lens_Full_Plan_v2.md`  
Baseline: Phase 1–2 commit `a651e11`

## Goal

Deliver deterministic local lexical retrieval and a conservative relationship graph over the
existing structural index. Phase 3 is complete when a user can find exact symbols and ranked
source matches, traverse resolved import/call/type/test/configuration relationships, and update
both indexes incrementally without reprocessing unchanged files.

## Assumptions

- Phase 2 structural identities, source ranges, and last-known-good behavior remain stable.
- Python's bundled SQLite must expose FTS5; no external search service is introduced.
- Syntax facts remain the source of truth. A graph edge is a reproducible derived record.
- Ambiguous facts remain unresolved instead of selecting a low-confidence target.
- Search and graph operations remain repository-scoped and local-only.

## Scope

### In scope

- Exact symbol lookup.
- SQLite FTS5 over paths, names, qualified names, signatures, fact targets, and syntax-aware
  source chunks.
- Import, basic call, inheritance, implementation, test-source, and configuration links.
- Deterministic graph edges with resolution evidence and confidence.
- Incremental projection replacement and graph rebuilding for directly affected files.
- Typed Python services, CLI commands, JSON contracts, migrations, tests, and performance
  baselines.

### Out of scope

- Embeddings, Qdrant, semantic search, and reranking.
- Task resolution, context bundles, confidence-gate orchestration, and token estimation.
- MCP tools and coding-agent integrations.
- Git-history relations and probabilistic whole-program call analysis.
- Background watching, Pro features, telemetry, licensing, and billing.

## Architecture decisions

- Store searchable records in a normalized `search_documents` projection with foreign keys to
  repositories and files.
- Use an external-content FTS5 table maintained by SQLite triggers. Replace a file's search
  documents in the same transaction as its structural records.
- Backfill the FTS projection during migration so an existing Phase 2 database is searchable
  without a forced reparse.
- Treat exact symbol matches as higher priority than lexical matches.
- Compile user queries into bounded quoted prefix terms; never accept raw FTS syntax.
- Materialize graph edges from syntax facts in a separate migration. Preserve the originating
  fact ID, normalized target, resolution strategy, and confidence.
- Resolve only deterministic unique targets. Record ambiguous and unresolved outcomes as
  diagnostics, not speculative edges.

## Roadmap

### P3-01 — Record contracts and create the lexical schema

Status: Delivered in the current working tree  
Dependencies: Phase 2 exit gate

Deliverables:

- Add ADR 0003.
- Add reversible migration `0003_search_index`.
- Create `search_documents`, its indexes, FTS5 external-content table, and synchronization
  triggers.
- Backfill files, symbols, chunks, and syntax facts already stored by Phase 2.

Exit criteria:

- Fresh upgrade reaches `0003_search_index`.
- Downgrade to `0002_structural_index` and re-upgrade both succeed.
- Existing structural records become searchable after upgrade.
- Repository/file deletion cascades remove lexical records.

### P3-02 — Maintain the lexical projection incrementally

Status: Delivered in the current working tree  
Dependencies: P3-01

Deliverables:

- Project file paths, symbols, chunks, and fact targets into search documents.
- Replace the projection inside `StructuralStore.replace_file`.
- Preserve the previous projection when parsing or persistence fails.
- Remove documents when a source file is deleted.

Exit criteria:

- A one-file update removes old terms and exposes new terms.
- A deleted file produces no search results.
- A no-op index run writes no projection rows.
- A failed replacement rolls back structural and lexical records together.

### P3-03 — Add exact and FTS search surfaces

Status: Delivered in the current working tree  
Dependencies: P3-01, P3-02

Deliverables:

- Add immutable search response models and `SearchService`.
- Search exact symbol names/qualified names before FTS5.
- Add deterministic repository-scoped ranking, deduplication, snippets, and result limits.
- Add `monas-lens search <query> [--repository] [--limit] [--json]`.
- Add stable validation errors for empty, punctuation-only, oversized, and invalid-limit input.

Exit criteria:

- Exact qualified-name lookup is the first result.
- Source terms find the owning syntax-aware chunk.
- Results never cross repository boundaries.
- Human and JSON outputs are clean and deterministic.

### P3-04 — Normalize resolvable syntax facts

Status: Delivered in the current working tree  
Dependencies: P3-03

Deliverables:

- Define language-specific normalizers for import, call, inheritance, implementation, test, and
  configuration targets.
- Separate module/path candidates from symbol candidates.
- Preserve raw target text and emit bounded diagnostics for unsupported or ambiguous syntax.
- Add golden fixtures for Python, JavaScript, TypeScript, TSX, and Dart.

Exit criteria:

- Normalization is deterministic and does not depend on filesystem traversal order.
- Alias, relative-import, member-call, and qualified-type cases are covered.
- Unsupported syntax creates no guessed target.

### P3-05 — Create and build the relationship graph

Status: Delivered in the current working tree  
Dependencies: P3-04

Deliverables:

- Add reversible graph migration with relationship and resolution-diagnostic tables.
- Resolve repository-local files and symbols using exact path/name indexes.
- Materialize `imports`, `calls`, `inherits`, and `implements` edges.
- Store originating fact, source/target identity, strategy, confidence, and metadata.
- Rebuild only relations affected by changed/deleted files and inbound candidate changes.

Exit criteria:

- Unique targets resolve; ambiguous targets remain diagnostics.
- Edge IDs are stable across unchanged runs and unrelated line shifts.
- Deleted or renamed targets remove stale inbound edges.
- Last-known-good structural data keeps its previous graph when a reparse fails.

### P3-06 — Derive test and configuration links

Status: Delivered in the current working tree  
Dependencies: P3-05

Deliverables:

- Derive `tested_by` links from test symbols, test declarations, imports, and calls.
- Add conservative configuration-key extraction for supported source forms.
- Derive `configured_by` links only when a unique key/target can be proven.

Exit criteria:

- Test links point from production symbols to relevant test symbols.
- Same-name tests in unrelated modules do not create cross-module edges.
- Configuration values or secrets are never copied into diagnostics.

### P3-07 — Add graph query and inspection surfaces

Status: Delivered in the current working tree  
Dependencies: P3-05, P3-06

Deliverables:

- Add typed neighbor and bounded traversal services.
- Add relation-kind filters, direction, maximum depth, and result caps.
- Add CLI graph inspection and machine-readable JSON output.
- Expose graph counts and unresolved/ambiguous diagnostics in index status.

Exit criteria:

- Traversal is cycle-safe, deterministic, repository-scoped, and bounded.
- Default traversal completes within the Phase 3 performance target.
- Invalid depth, direction, and relation filters return stable errors.

### P3-08 — Close the Phase 3 release gate

Status: Delivered in the current working tree  
Dependencies: P3-01 through P3-07

Deliverables:

- Add mixed-language end-to-end search and graph fixtures.
- Add migration, rollback, fault-injection, repository-isolation, and package smoke tests.
- Benchmark exact lookup, FTS ranking, incremental projection refresh, edge building, and
  one-hop traversal.
- Update user documentation, known limitations, recovery guidance, and validation evidence.

Phase 3 exit criteria:

- Exact symbol lookup and FTS ranking are deterministic.
- Import, basic call, type, test, and configuration links pass golden tests.
- Incremental changes refresh only affected lexical and graph records.
- Ambiguity never produces a guessed edge.
- Full quality, packaging, isolated-wheel, and Windows/Linux CI gates pass.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| SQLite runtime lacks FTS5 | Initialization cannot create the lexical index | Fail during migration with an actionable diagnostic and test packaged runtimes. |
| FTS tokenization hides code identifiers | Expected code terms return no result | Preserve underscores, split member dots, and keep exact symbol lookup separate. |
| Migration leaves existing indexes unsearchable | Users must reparse everything | Backfill the projection from Phase 2 tables inside migration 0003. |
| Same-name symbols create false graph edges | Context expansion becomes misleading | Resolve only unique scoped candidates and persist ambiguity diagnostics. |
| Target deletion leaves inbound edges | Traversal returns stale context | Track target dependencies and rebuild inbound affected relations. |
| Search projection diverges from structural rows | Results point to stale lines | Replace both projections in the same per-file transaction. |

## Validation

- Unit: query compiler, ranking/deduplication, target normalization, candidate resolution, graph
  traversal.
- Integration: migration backfill, triggers, atomic replacement, cascade deletion, repository
  isolation, last-known-good recovery.
- End-to-end: mixed-language first build, no-op build, update, delete, rename, parse failure,
  recovery, search, and graph traversal.
- Packaging: isolated wheel installation with FTS5 capability and offline fixture indexing.
- Performance: exact lookup, FTS query, graph build, and one-hop traversal against the recorded
  self-index baseline.

## Recommended execution order

`P3-01 → P3-02 → P3-03 → P3-04 → P3-05 → P3-06 → P3-07 → P3-08`

Phase 3 is complete in the current working tree. The next roadmap step is Phase 4 Context
Compiler: Task Resolver, Parallel Retriever, Ranker, Confidence Gate, Context Bundle, and Token
Estimator. Create and approve a dedicated Phase 4 backlog before implementation. See
`docs/PHASE_3_VALIDATION.md` for the Phase 3 release-gate evidence.
