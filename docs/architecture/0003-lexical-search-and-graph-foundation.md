# ADR 0003 — Lexical search and graph foundation

Status: Accepted

## Context

Phase 2 stores deterministic files, symbols, syntax-aware chunks, and unresolved syntax facts.
Phase 3 must make those records searchable and later resolve conservative repository-local
relationships. Search must remain incremental, offline, repository-scoped, and safe for arbitrary
user queries.

## Decision

- Use SQLite FTS5 for Community lexical search.
- Store a normalized `search_documents` projection linked to repositories and files by foreign
  keys.
- Use an external-content FTS5 table with insert, update, and delete triggers.
- Replace a file's search documents in the same transaction as its structural records.
- Backfill existing Phase 2 records during migration `0003_search_index`.
- Index paths, symbol names, qualified names, signatures, chunk source, docstrings, and unresolved
  fact targets.
- Run exact symbol lookup before FTS ranking and deduplicate by entity identity.
- Convert user input to bounded quoted prefix terms. Raw FTS query syntax is not accepted.
- Preserve underscores as identifier characters and split dots so member names remain searchable.
- Materialize repository-local relationships and bounded resolution diagnostics in migration
  `0004_relationship_graph`.
- Normalize language-specific facts into module, symbol, and configuration targets before
  resolution.
- Resolve candidates through deterministic tiers: exact module path, import binding, receiver
  scope, same-file symbol, and repository-unique symbol.
- Persist no edge when a tier is ambiguous. Record unresolved, ambiguous, and unsupported
  outcomes without copying configuration values or secrets.
- Derive stable relationship IDs from repository, relation kind, and source/target identities;
  keep the originating fact, strategy, and confidence as evidence.
- Refresh facts in changed files plus inbound facts whose normalized dependency keys intersect
  renamed, added, or deleted path/symbol keys.
- Preserve the previous graph when a replacement fails, matching structural last-known-good
  behavior.

## Consequences

- Existing Phase 2 databases become searchable without a full rebuild.
- A successful one-file replacement updates structural and lexical records atomically.
- Foreign-key cascades and FTS triggers remove deleted repository/file records.
- Lexical storage duplicates selected structural text, trading disk space for deterministic local
  query latency.
- FTS5 availability is a runtime prerequisite for migration 0003.
- Graph traversal is bounded, cycle-safe, deterministic, and repository-scoped.
- Basic call resolution is intentionally conservative and is not whole-program or runtime-aware.
- Semantic retrieval, hybrid ranking, task resolution, and MCP remain outside this decision.
