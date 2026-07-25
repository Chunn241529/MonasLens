# Monas Lens — Phase 4 Context Compiler Backlog

Status: Approved; P4-01 delivered in the current working tree
Source: `Monas_Lens_Full_Plan_v2.md`
Baseline: Phase 3 delivered in the current working tree

## Goal

Deliver a deterministic, local Context Compiler over the Phase 2 structural index and Phase 3
lexical/graph services. Phase 4 is complete when a bounded task request produces a repository-scoped
context bundle containing ranked primary definitions, callers, dependencies, interfaces,
configuration, tests, relevant working-tree diff hunks, validation suggestions, confidence
evidence, and an explicit estimated-token budget.

## Confirmed facts

- Phase 3 already provides immutable exact/FTS search responses with stable entity identities,
  source ranges, snippets, and scores.
- Phase 3 already provides bounded, cycle-safe graph neighbors/traversal with relation filters,
  edge confidence, and deterministic ordering.
- Structural chunks contain indexed source text and content hashes, so context assembly does not
  need to reread arbitrary source paths.
- The product roadmap sets a default maximum of three primary targets, six dependency snippets,
  six caller snippets, four test snippets, five Git entries, 12,000 estimated context tokens, and
  a confidence threshold of `0.80`.
- The product remains local-only. Repository source, task text, context bundles, Git diffs, and
  agent conversations must not be uploaded or written to logs.

## Assumptions

- Phase 4 consumes the current synchronous `SearchService` and `GraphService` through adapters; it
  does not change their public response models.
- Retrieval concurrency uses independent read sessions. Completion order must never affect the
  merged result order.
- Token counts are estimates because Phase 4 is model-agnostic. The response must identify the
  estimator and must not claim exact model-token accounting.
- Low confidence is returned explicitly after one bounded internal widening pass; it does not cause
  a guessed target or an unbounded retry loop.
- Current Git diff collection is optional and degradable. A non-Git repository or Git failure must
  not prevent indexed context from being returned.

## Scope

### In scope

- Typed request, task-resolution, candidate, evidence, ranking, confidence, budget, snippet,
  diagnostic, and context-bundle contracts.
- Deterministic task parsing for identifiers, qualified names, paths, quoted error text, keywords,
  requested action, and optional user-provided focus targets.
- Bounded two-stage retrieval over exact/FTS search and the existing relationship graph.
- Ranking and deduplication with inspectable score components and stable tie-breaks.
- A single confidence-driven retrieval widening pass.
- Indexed-chunk materialization, line-focused cropping, content-hash deduplication, role quotas, and
  estimated-token budgeting.
- Bounded current working-tree diff context and conservative validation-command suggestions.
- A Python service, CLI inspection command, JSON output, tests, benchmark, documentation, and
  package smoke validation.

### Out of scope

- Embeddings, Qdrant, Ollama, semantic search, reranking models, and hybrid vector ranking.
- MCP tools, MCP transport, coding-agent policy enforcement, and external `expand_context`.
- Patch-impact analysis, Git-history retrieval, `changed_with` relationships, and background
  watching.
- Persisting task requests, candidates, bundles, confidence, analytics, or caches.
- Editing source code, executing validation commands, or applying patches.
- Network access, telemetry, repository upload, Pro features, licensing, and billing.

## Architecture decisions to record in ADR 0004

- Add `src/monas_lens/retrieval/` as the Phase 4 package. Keep task resolution, retrieval, ranking,
  confidence, token estimation, bundle assembly, and orchestration as separate modules.
- Treat Phase 4 as a read-only projection over existing Phase 2/3 tables. No database migration is
  required.
- Use a two-stage retriever:
  1. Run bounded lexical queries concurrently and select at most three primary seeds.
  2. Fan out bounded caller, dependency, type, test, and configuration graph queries concurrently
     from those seeds.
- Isolate every worker behind a typed retriever interface and a fresh database session. A required
  lexical-channel failure fails the request with a stable error; an optional graph or Git failure
  returns a bounded diagnostic and lowers confidence.
- Merge worker results only after collection. Sort and deduplicate from stable identities, never
  future completion order.
- Preserve the roadmap ranking weights:

  | Evidence | Base weight |
  |---|---:|
  | Exact symbol | `0.35` |
  | Graph relationship | `0.25` |
  | Lexical match | `0.20` |
  | Test relationship | `0.10` |
  | Semantic similarity | `0.10` |

  Semantic similarity is disabled in Phase 4 and remains zero. Candidate rank scores are normalized
  over the enabled `0.90` weight total. `configured_by`, `inherits`, and `implements` are graph
  evidence; `tested_by` uses the test component. Ranking score and request confidence are distinct
  values.
- Materialize code snippets from indexed `ChunkModel.source_text`. Resolve symbols and graph nodes
  to their owning or narrowest containing chunks in batched repository-scoped queries.
- Deduplicate identical materialized content by content hash before token allocation. Keep the
  highest-ranked occurrence and retain all stable source references as provenance.
- Use a pluggable `TokenEstimator` protocol. Ship one deterministic, dependency-free heuristic
  estimator, report its name/version and `is_exact=false`, and reserve a safety margin when
  allocating the requested budget.
- Read the current Git diff only through a fixed-argument, no-shell subprocess rooted at the
  registered repository. Enforce timeout and byte/hunk caps; never interpolate task text into a
  command.
- Emit structured stage counts, warning codes, and durations without logging task text, source
  text, snippets, diffs, configuration values, or absolute repository paths.

## Contract baseline

### Request

`TaskContextRequest` is immutable and contains:

| Field | Type | Rule |
|---|---|---|
| `task` | `str` | Trimmed, non-empty, bounded to 4,000 characters. |
| `repository` | `str \| Path \| None` | Uses the active repository when omitted. |
| `focus_targets` | `tuple[str, ...]` | Optional explicit paths/symbols; maximum 10, each bounded. |
| `max_tokens` | `int \| None` | Defaults to configured 12,000; cannot exceed the configured cap. |
| `include_git_diff` | `bool` | Defaults to `true`; failure is degradable. |

Invalid task, focus, or budget input must use stable `CONTEXT_REQUEST_INVALID` or
`CONTEXT_BUDGET_INVALID` errors before starting worker tasks.

### Task resolution

`TaskResolution` is immutable and contains:

- normalized task text for retrieval only;
- requested action: `diagnose`, `change`, `refactor`, `test`, `explain`, or `unknown`;
- ordered, deduplicated qualified identifiers, identifiers, relative-path candidates, quoted
  phrases/error text, and lexical queries;
- explicit focus targets distinguished from inferred targets;
- bounded resolver diagnostics for discarded or unsupported input.

Resolution is pure and deterministic. It must not access the filesystem, database, network, an LLM,
or user environment variables. It must preserve original identifier casing and must not guess a
language solely from a natural-language word.

### Candidate and evidence

`RetrievalCandidate` is immutable and contains:

- repository ID, entity type, entity ID, relative path, language, kind, and indexed range;
- display name/qualified name when present;
- one or more immutable evidence records;
- candidate role hints: `primary`, `caller`, `dependency`, `interface`, `schema`, `configuration`,
  or `test`;
- stable retrieval ordinal derived from the plan, never wall-clock completion order.

Evidence records identify `exact`, `lexical`, `graph`, or `test`, the originating query/seed,
relation kind and distance when applicable, source score/confidence, and a bounded explanation.
They must not copy raw configuration values or secrets.

Candidate identity is `(repository_id, entity_type, entity_id)`. Merge evidence for duplicate
identities before ranking.

### Ranking

For each candidate, compute bounded signals in `[0, 1]`:

- exact: maximum exact-search score;
- lexical: maximum lexical-search score;
- graph: maximum non-test edge confidence multiplied by deterministic depth decay;
- test: maximum `tested_by` confidence multiplied by deterministic depth decay;
- semantic: `0` in Phase 4.

The normalized rank score is the weighted sum divided by the enabled weight total. Round only at the
serialized boundary. Stable tie-breaks are score descending, explicit focus before inferred focus,
role priority, relative path, start line, entity type, and entity ID. Tests must prove that shuffled
worker completion and input order produce byte-equivalent ranked JSON.

### Confidence gate

`ConfidenceResult` contains initial confidence, final confidence, threshold, status, expansion
count, component values, and ordered reason codes. Confidence components must cover:

- primary-target certainty;
- agreement across independent enabled evidence families;
- separation between the leading primary and alternatives;
- coverage of task-relevant roles.

The formula and certainty table are versioned constants with golden tests. Confidence `>= 0.80`
returns the first-pass selection. Confidence below `0.80` triggers exactly one widening pass that:

- retains the same repository and request budget;
- expands only unresolved seeds and missing roles;
- increases graph depth from one to at most two;
- returns only new candidates before merge/deduplication;
- reranks and recalculates confidence once.

If confidence remains below the threshold, return a `degraded` bundle with explicit missing roles and
reason codes. Never select an ambiguous target merely to raise confidence.

### Token estimate and budget

`TokenEstimate` contains estimator name/version, `is_exact`, text characters, UTF-8 bytes, and
estimated tokens. The default estimator must be deterministic for empty, ASCII, Unicode, long-line,
and mixed code/text inputs.

`ContextBudget` contains requested, reserved, used, and remaining estimated tokens; pre-budget
candidate tokens; estimated tokens saved; reduction ratio; per-role usage; omitted item counts; and
whether any snippet was cropped.

Budget allocation rules:

1. Reserve a documented safety margin and response-envelope allowance.
2. Select up to three ranked primary snippets first.
3. Add task-relevant interfaces/schemas/configuration and direct dependencies.
4. Add direct callers, then two to four relevant tests.
5. Add at most five relevant Git diff hunks.
6. Use stable role round-robin ordering within the remaining budget.
7. Crop oversized snippets only at line boundaries around the matched range, mark omissions, and
   recompute content hash and estimate.
8. Never exceed the requested estimated-token budget after envelope allowance.

Default role caps remain:

```yaml
max_primary_targets: 3
max_dependency_snippets: 6
max_caller_snippets: 6
max_test_snippets: 4
max_git_entries: 5
max_total_context_tokens: 12000
```

### Context bundle

`ContextBundle` is immutable and contains:

- schema version, repository ID, task resolution, and ordered primary targets;
- confidence result and whether internal widening occurred;
- ordered context snippets grouped by semantic role;
- snippet provenance, indexed source ranges, content hashes, score components, and token estimates;
- budget summary, truncation state, missing-role diagnostics, and retrieval diagnostics;
- suggested validation commands as display-only argument arrays, never executable shell strings.

Bundle JSON must be deterministic for unchanged repository state and identical input. Runtime
durations belong in structured logs/benchmark output, not in the deterministic bundle contract.

## Roadmap

### P4-01 — Record Context Compiler decisions and contracts

Status: Delivered in the current working tree
Dependencies: Phase 3 exit gate

Deliverables:

- Add ADR 0004 with the decisions and boundaries above.
- Add immutable contracts and enums under `src/monas_lens/retrieval/contracts.py`.
- Add stable context-related error codes and bounded settings defaults.
- Add public package exports without changing existing search/graph contracts.

Exit criteria:

- Contract JSON schemas are snapshot-tested and use no mutable defaults.
- Invalid task, focus, budget, confidence, relation, and role values fail with stable errors.
- Settings validate all caps and keep the roadmap defaults.
- No migration or new runtime dependency is introduced.

### P4-02 — Implement the deterministic Task Resolver

Status: Ready
Dependencies: P4-01

Deliverables:

- Normalize task whitespace without changing identifier or quoted-text casing.
- Extract explicit focus targets, qualified/member identifiers, paths, quoted errors, and bounded
  lexical terms.
- Classify requested action conservatively and generate ordered retrieval queries.
- Separate pure resolver logic from repository retrieval.

Exit criteria:

- Repeated input produces byte-equivalent resolution JSON.
- Empty, punctuation-only, oversized, and adversarial task input is rejected before retrieval.
- Mixed prose/code, Windows/POSIX paths, dotted identifiers, error messages, and Unicode have golden
  fixtures.
- Ambiguous prose remains `unknown` instead of being forced into an action or language.

### P4-03 — Add bounded two-stage parallel retrieval

Status: Blocked by P4-02
Dependencies: P4-01, P4-02

Deliverables:

- Add typed adapters for `SearchService`, `GraphService`, indexed chunk lookup, and optional Git
  diff lookup.
- Run stage-one lexical queries with a bounded worker pool and select at most three seeds.
- Run stage-two caller/dependency/interface/test/configuration graph branches concurrently.
- Cap query count, seeds, per-branch results, graph depth, total candidates, diagnostics, and
  subprocess output.
- Merge results deterministically and preserve all evidence for duplicate entities.

Exit criteria:

- Deliberately shuffled worker delays produce identical merged candidates and diagnostics.
- Each worker opens and closes its own database session; no session crosses a worker boundary.
- Candidate and graph results never cross repository boundaries.
- Optional graph/Git failure degrades cleanly; required lexical failure returns a stable error.
- Work-cap tests prove a crafted high-fan-out repository cannot cause unbounded queries or results.

### P4-04 — Rank and deduplicate candidates

Status: Blocked by P4-03
Dependencies: P4-01, P4-03

Deliverables:

- Compute inspectable evidence signals, enabled-weight normalization, graph depth decay, and stable
  tie-breaks.
- Boost only explicit user focus through a bounded documented component; never mutate source
  service scores.
- Deduplicate entity identities before ranking and content hashes after materialization.
- Expose score components without exposing source/configuration values.

Exit criteria:

- Exact unique symbols outrank lexical-only alternatives.
- Direct conservative graph evidence outranks otherwise equal depth-two evidence.
- Relevant `tested_by` evidence improves test candidates without promoting unrelated same-name
  tests.
- Disabled semantic evidence cannot change Phase 4 ordering.
- Shuffled evidence and candidate order produce byte-equivalent ranked results.

### P4-05 — Implement the Confidence Gate

Status: Blocked by P4-03 and P4-04
Dependencies: P4-03, P4-04

Deliverables:

- Implement the versioned confidence formula, certainty table, threshold decision, and reason codes.
- Identify missing roles and unresolved seeds from first-pass evidence.
- Perform at most one targeted depth-two/new-query widening pass and rerank.
- Return accepted or degraded confidence explicitly.

Exit criteria:

- A unique qualified-symbol task with coherent evidence clears the threshold.
- Ambiguous same-name targets do not clear the threshold.
- Low confidence invokes exactly one widening pass; high confidence invokes none.
- The widening pass returns only new candidates and never exceeds configured caps.
- Persistent low confidence returns a deterministic degraded result, not a guessed target or loop.

### P4-06 — Add token estimation and budget allocation

Status: Ready
Dependencies: P4-01

Deliverables:

- Add the estimator protocol and dependency-free default estimator.
- Add envelope/safety reserve, per-role accounting, token-savings metrics, and stable selection.
- Add line-aware cropping with explicit omission markers.
- Calibrate and document heuristic error against representative Python, JavaScript, TypeScript,
  TSX, Dart, JSON/YAML, Unicode prose, and Git diff fixtures.

Exit criteria:

- Estimates and allocation are deterministic across supported platforms.
- The serialized bundle estimate never exceeds its accepted request budget.
- Primary context is selected before supplemental context, and role caps are enforced.
- Cropping preserves the matched line, valid line bounds, provenance, and content hash integrity.
- Calibration reports error distribution honestly and never labels the heuristic exact.

### P4-07 — Build focused Context Bundles

Status: Blocked by P4-04 and P4-06
Dependencies: P4-03, P4-04, P4-06

Deliverables:

- Batch-resolve ranked entities to the narrowest indexed chunks.
- Assign and group primary, caller, dependency, interface, schema, configuration, and test roles.
- Deduplicate by content hash while retaining provenance.
- Collect bounded relevant working-tree diff hunks with a fixed-argument Git adapter.
- Suggest validation commands conservatively from indexed project manifests and selected tests;
  commands are data only and are never executed.
- Assemble deterministic, versioned bundle JSON under the accepted budget.

Exit criteria:

- Bundles contain focused indexed ranges rather than whole files.
- Identical chunks from multiple evidence paths appear once with merged provenance.
- Configuration relations never copy values into evidence, diagnostics, or logs.
- Git absence, timeout, non-zero exit, oversized output, and invalid paths are bounded diagnostics.
- Suggested commands use argument arrays, contain no task interpolation, and remain inside the
  registered repository scope.

### P4-08 — Orchestrate and expose the Context Compiler

Status: Blocked by P4-02 through P4-07
Dependencies: P4-02, P4-03, P4-04, P4-05, P4-06, P4-07

Deliverables:

- Add `ContextCompiler.resolve(request)` as the single orchestration entry point.
- Enforce resolve → retrieve → rank → confidence/widen → materialize → budget → bundle sequencing.
- Add `monas-lens context resolve <task> [--repository] [--focus] [--max-tokens]
  [--no-git-diff] [--json]`.
- Add human output that summarizes confidence, budget, primary targets, included roles, and bounded
  warnings without dumping hidden diagnostics or absolute paths.
- Add content-free structured stage logging and failure cleanup.

Exit criteria:

- Human and JSON CLI output is deterministic apart from explicitly excluded log timing.
- CLI/service errors use stable codes and never print tracebacks by default.
- A worker or Git failure leaves no executor, subprocess, session, or transaction open.
- Phase 5 can wrap the Python service without importing CLI code or changing bundle contracts.

### P4-09 — Close the Phase 4 release gate

Status: Blocked by P4-01 through P4-08
Dependencies: P4-01 through P4-08

Deliverables:

- Add mixed-language end-to-end task fixtures for missing import, wrong configuration key, broken
  API schema, expired session logic, cross-file rename, missing regression test, and unrelated
  working-tree change.
- Add concurrency, repository-isolation, stale-index, parse-failure, budget, fault-injection, Git,
  packaging, and deterministic-serialization tests.
- Add `benchmarks/phase4_context_compiler.py` with per-stage and total timing, candidate counts,
  context-token estimates, and reduction ratios.
- Add `docs/PHASE_4_VALIDATION.md`, CLI/README guidance, limitations, recovery guidance, and the
  recorded local baseline.
- Include the Phase 4 backlog and validation document in the source distribution.

Phase 4 exit criteria:

- The compiler returns focused, role-complete context for the seven required benchmark scenarios.
- Exact, lexical, graph, test, configuration, diff, and validation evidence remains
  repository-scoped, deterministic, and bounded.
- Confidence performs no more than one internal expansion and reports persistent uncertainty.
- Bundle allocation respects role and estimated-token caps and reports savings.
- Median local targets remain: symbol lookup `<= 20 ms`, graph traversal `<= 30 ms`, ranking
  `<= 80 ms`, and total context resolution `<= 500 ms`; p95 and machine details are recorded.
- Full format, lint, strict typing, test/coverage, lock, build, isolated-wheel, migration
  compatibility, and Windows/Linux CI gates pass.

## Cross-cutting validation

- Unit: resolver extraction, action classification, query planning, score components, tie-breaks,
  confidence formula, token estimation, budget allocation, cropping, hash deduplication, role
  selection, and validation-command suggestions.
- Integration: parallel database sessions, search/graph adapters, batched chunk materialization,
  optional Git diff adapter, fault isolation, repository isolation, and last-known-good index use.
- End-to-end: the seven roadmap benchmark scenarios, low-confidence widening, no-op repeatability,
  stale source recovery, Unicode input, and deterministic human/JSON CLI output.
- Security: no path traversal, no shell interpolation, no source/task/configuration values in logs,
  bounded subprocess output, no network access, and no repository upload.
- Packaging: offline isolated Python 3.12 wheel resolves context from a prebuilt fixture database;
  downgrade/upgrade compatibility through the Phase 3 migration head remains intact.
- Quality: Ruff format/lint, Pyright strict, pytest with at least 85% total coverage, lock check,
  build, `git diff --check`, and Windows/Linux CI.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Natural-language task parsing overstates intent | Wrong retrieval plan appears authoritative | Keep parsing rule-based, preserve unknown state, expose inferred versus explicit targets, and use confidence reasons. |
| FTS `AND` queries become too restrictive | Broad tasks return no primary seed | Generate bounded identifier/phrase/keyword queries separately and merge stable evidence. |
| SQLite reads are shared incorrectly across workers | Thread errors or inconsistent reads | Create a fresh service/session per worker and prohibit session objects in worker contracts. |
| Worker completion order changes ranking | Non-reproducible bundles and flaky tests | Assign plan ordinals, collect before merge, and sort on stable keys only. |
| Graph fan-out grows rapidly | Latency and bundle noise exceed targets | Cap seeds, depth, relations, branch results, candidates, and the single widening pass. |
| Rank score is mistaken for certainty | A high lexical score hides ambiguity | Keep rank and confidence separate and expose confidence components/reasons. |
| Confidence formula is poorly calibrated | Frequent false acceptance or degraded results | Version constants and calibrate with ambiguous and known-answer golden fixtures before release. |
| Heuristic token estimate drifts from an agent model | Returned bundle consumes more or less context than expected | Report `is_exact=false`, reserve margin, publish calibration error, and keep estimator pluggable. |
| Duplicate chunks waste budget | Important supporting roles are omitted | Deduplicate materialized content hash before allocation and merge provenance. |
| Git diff is large, slow, or unavailable | Context resolution stalls or leaks output into logs | Fixed arguments, repository cwd, timeout, byte/hunk caps, degradable diagnostics, and content-free logging. |
| Existing index is stale | Bundle reflects last-known-good rather than current source | Surface file/index staleness in diagnostics without silently rereading or replacing indexed data. |

## Recommended execution order

```text
P4-01
├── P4-02 ── P4-03 ── P4-04 ── P4-05
└── P4-06 ─────────────────┐
                          P4-07 ── P4-08 ── P4-09
```

`P4-01` is complete. `P4-02` and `P4-06` are ready and may proceed independently; all remaining
tasks follow their declared dependencies. Do not start semantic retrieval or MCP work inside
Phase 4.
