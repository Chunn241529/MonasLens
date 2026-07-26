# ADR 0004 — Context Compiler contracts

Status: Accepted

## Context

Phase 3 provides deterministic, repository-scoped exact/FTS search and conservative relationship
graph queries. Phase 4 must compile those records into focused context for coding tasks while
remaining local-only, bounded, inspectable, and independent of semantic models or MCP transport.

Natural-language tasks can be ambiguous, concurrent retrieval can complete in arbitrary order, and
model-agnostic token counts are estimates. The compiler therefore needs stable contracts that keep
ranking separate from confidence and expose degraded results rather than guessing.

## Decision

- Add a read-only `monas_lens.retrieval` package over the existing structural, search, and graph
  projections. Phase 4 adds no database migration.
- Use immutable Pydantic contracts for requests, task resolutions, candidates, evidence, ranks,
  confidence, token estimates, budgets, snippets, diagnostics, validation suggestions, and bundles.
- Parse external requests through a public validation boundary that maps invalid task/focus input
  to `context_request_invalid` and invalid token limits to `context_budget_invalid`.
- Keep existing `SearchService` and `GraphService` response contracts unchanged.
- Retrieve in two bounded stages: concurrent lexical seed discovery followed by concurrent graph
  fan-out from at most three primary seeds.
- Give every worker an independent database session. Merge only after collection, then sort and
  deduplicate by stable identities so completion order cannot affect output.
- Preserve roadmap evidence weights for exact symbol, graph, lexical, test, and semantic signals.
  Semantic evidence remains disabled and zero in Phase 4; enabled weights are normalized over
  `0.90`. Direct graph/test evidence keeps its full source confidence and depth-two evidence uses
  a `0.50` decay. Explicit user focus closes at most `0.05` of remaining score headroom and is a
  stable tie-break; inferred focus receives no boost.
- Keep candidate rank and request confidence as separate values. Confidence below `0.80` permits
  one bounded widening pass and then returns an explicit degraded result if uncertainty remains.
- Version confidence formula `1.0` with component weights `0.40` primary-target certainty, `0.25`
  independent evidence-family agreement, `0.20` leading-target separation, and `0.15`
  task-relevant role coverage. Version the primary certainty table separately, treat candidates
  within `0.05` score as ambiguous unless explicit focus distinguishes the leader, and require a
  `0.20` margin for full separation. Unavailable optional channels subtract `0.05`; truncated Git
  context subtracts `0.025`.
- On low confidence, widen only unresolved primary seeds and missing task roles at graph depth two.
  Filter identities already returned, preserve repository and candidate caps, rerank once, and do
  not loop or guess if the final result remains degraded.
- Materialize source from indexed chunks, deduplicate by content hash, and allocate role-capped
  snippets under an explicitly estimated token budget.
- Identify the estimator and mark the dependency-free default as inexact. Reserve configurable
  safety and response-envelope capacity.
- Represent validation commands as argument arrays. Read optional Git diff context with fixed
  arguments, no shell, repository-rooted execution, and bounded output.
- Log stage counts and durations only. Do not log task text, source, snippets, configuration values,
  diffs, context bundles, or absolute repository paths.

## Consequences

- Phase 5 can wrap the Python service with MCP without importing CLI code or redesigning bundle
  schemas.
- Existing Phase 2 and Phase 3 data remains compatible and read-only during context compilation.
- Disabled or failed optional retrieval channels lower confidence and add diagnostics instead of
  silently changing ranking behavior.
- Deterministic contracts and stable tie-breaks make repeatable JSON and golden tests possible.
- A model-agnostic token budget is honest but approximate; callers must inspect estimator metadata.
- Semantic retrieval, external expansion, patch-impact analysis, persistence, and telemetry remain
  outside this decision.
