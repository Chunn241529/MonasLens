# Monas Lens — Phase 5 Retrieval Quality Plan

Status: Ready for implementation  
Priority: Complete before public Community validation  
Prerequisite: Preserve the current embedded agent-skill worktree changes

## Goal

Make Monas Lens the primary repository-discovery path for coding agents:

- one `resolve_task_context` call for the normal case;
- at most one targeted `expand_context` call;
- exact indexed source ranges instead of whole-file reads;
- complete task-relevant callers, dependencies/callees, interfaces, implementations, tests,
  schemas, and configuration;
- no repeated snippets across calls;
- explicit recovery guidance when the index or relationship graph cannot provide enough evidence.

The release claim is not complete until this behavior is proven by a deterministic quality gate.

## Non-goals

- Embeddings, vector databases, semantic reranking, or LLM-based ranking.
- Remote repository processing, telemetry, HTTP transport, OAuth, Pro, or Team features.
- Guessing ambiguous relationships to improve recall.
- Automatically mutating the index from the read-only MCP retrieval tools.

## Starting state

The current worktree already contains the embedded Monas Lens agent skill:

- MCP initialization returns the skill before normal requests.
- `monas-lens://agent-skill` exposes the same instructions as a resource.
- `monas-lens skill [--json]` exposes the same versioned contract to CLI agents.

Do not reset, discard, or overwrite these local changes.

Current known baseline issue:

- Full pytest has one failure because parser diagnostics now include Go while
  `test_parser_diagnostics_cover_all_initial_languages` still expects the original five languages.

## Implementation order

### R0 — Restore a green and versioned indexing baseline

1. Complete the Go baseline:
   - update parser diagnostics expectations;
   - add scanner detection coverage for `.go`;
   - add representative Go extraction coverage for type, function, method, import, call, and test
     symbols/facts;
   - update the supported-language documentation.
2. Add an extractor/index format version:
   - add `indexed_extractor_version` to indexed file state through migration `0005`;
   - define one current extractor version constant;
   - parse a file again when its content hash changed, its previous parse failed, or its extractor
     version differs from the current version;
   - persist the current version only after successful atomic replacement;
   - preserve last-known-good records when re-extraction fails.
3. Bump the extractor version whenever parser fact metadata or relationship inputs change.
4. Run the full quality gate before starting retrieval changes.

Acceptance:

- Ruff format and lint pass.
- Pyright strict reports zero errors and warnings.
- Full pytest passes, with only platform-supported skips.
- Existing databases upgrade programmatically and reparse old indexed files exactly once.

### R1 — Build the retrieval-efficiency quality gate

Create a deterministic gold task suite covering:

- exact function and class lookup;
- same-name symbol ambiguity across files;
- method caller and callee discovery;
- imported aliases and qualified calls;
- interface to implementation and implementation to interface;
- inheritance and overrides;
- exports and re-exports;
- route/registration to handler and schema;
- configuration dependencies;
- production symbol to regression tests;
- relevant Git diff context;
- degraded or stale index recovery.

Each gold case must declare:

- stable case ID and task text;
- optional explicit focus;
- expected primary symbols;
- required related symbols grouped by role;
- optional related symbols;
- maximum discovery calls;
- whether one expansion is permitted;
- expected next action when retrieval cannot complete normally.

The evaluator must:

1. Call the Context Compiler once.
2. Follow the returned next action.
3. Perform at most one expansion.
4. Treat any remaining grep, glob, search, graph, or whole-file discovery requirement as a manual
   fallback.
5. Emit deterministic JSON and exit non-zero when a release threshold fails.

Required metrics:

- primary top-1 and top-3 recall;
- required and optional related-symbol recall by role;
- missing-role count;
- duplicate content-hash count;
- returned and baseline estimated tokens;
- token-reduction ratio;
- discovery-call count;
- manual-fallback count and reasons;
- median and p95 retrieval latency;
- deterministic serialization comparison.

Release thresholds:

- primary top-1 recall at least 95%;
- primary top-3 recall exactly 100%;
- every symbol marked required is returned;
- optional related-symbol recall at least 90%;
- median discovery calls equals one;
- p95 discovery calls is at most two;
- zero manual fallbacks in the gold suite;
- zero duplicate content hashes;
- at least 60% fewer estimated tokens than reading the complete relevant files;
- p95 retrieval latency below 500 ms after indexing;
- three consecutive runs produce identical retrieval JSON apart from timing fields.

### R2 — Complete relationship closure

Preserve the resolution behavior that already works:

- `self`, `this`, and `super` receiver scope;
- imported symbol aliases;
- qualified imported members;
- unique same-file and repository-local symbols;
- conservative ambiguity diagnostics.

Add the missing relationship capabilities:

1. Typed local receivers:
   - extract explicit declared types and constructor-assigned receiver types into syntax-fact
     metadata;
   - resolve `service.run()` to `Service.run` only when the receiver type is explicit or derived
     from an unambiguous local constructor;
   - leave dynamic or conflicting receiver types unresolved.
2. Exports and re-exports:
   - normalize `FactKind.EXPORT`;
   - resolve direct exports, named re-exports, and barrel/module re-exports;
   - retain the re-export path as relationship evidence.
3. Interfaces and implementations:
   - add `CandidateRole.IMPLEMENTATION`;
   - traverse inheritance/implementation relationships in both directions;
   - return implementations when the primary target is an interface or base type;
   - return interfaces/base types when the primary target is an implementation.
4. Overrides:
   - derive an override relationship only after the parent type relationship resolves;
   - match methods conservatively by owner, name, and compatible declaration shape;
   - do not guess overloaded or ambiguous targets.
5. Framework registrations:
   - normalize supported decorator, route, and registration facts;
   - relate route/registration symbols to handlers and schema-like contracts;
   - retain unsupported framework syntax as bounded diagnostics.
6. Role-aware graph closure:
   - initial traversal depth remains one;
   - targeted widening depth remains two;
   - preserve caller, dependency/callee, interface, implementation, test, schema, and configuration
     branches independently;
   - apply deterministic per-role caps before merging candidates.

Relationship changes must continue using incremental dependency-key refresh. Do not rebuild the
entire graph on every normal index run.

### R3 — Upgrade the Context Bundle to schema 1.1

Keep every existing schema 1.0 field and add:

```text
ContextSnippet.roles: tuple[CandidateRole, ...]
ContextSnippet.evidence: tuple[RetrievalEvidence, ...]
ContextBundle.next_action: NextAction
ContextBundle.recommended_focus_target: str | None
ContextBundle.recommended_missing_roles: tuple[CandidateRole, ...]
```

Add:

```text
NextAction.kind:
  none
  expand
  refresh_index
  manual_fallback

NextAction.reason:
  accepted
  missing_primary
  ambiguous_primary
  missing_roles
  stale_index
  truncated
  retrieval_unavailable
```

Compatibility rules:

- Keep `ContextSnippet.role` as the primary role for schema 1.0 consumers.
- Populate `roles` with every role represented by the deduplicated snippet.
- Preserve the old `content_hash`, range, provenance, rank, and token fields.
- Bump the serialized Context Bundle schema version to `1.1`.
- MCP and CLI must return the same schema.
- No database migration is required for these response-only fields.

Bundle construction rules:

1. Build a primary symbol capsule from the exact indexed definition range.
2. Include directly required declarations as separate focused snippets instead of expanding to the
   complete file.
3. Deduplicate by content hash without losing secondary roles or relationship evidence.
4. Reserve budget for one candidate from every required role before allocating remaining tokens.
5. Fill remaining budget through deterministic role-aware round robin.
6. Recalculate materialized role coverage after budgeting.
7. Do not return accepted confidence if budgeting or materialization removed every candidate for a
   required role.
8. Select the recommended focus deterministically from:
   - the highest-priority missing role;
   - the closest unresolved graph seed;
   - the highest ranked stable target;
   - stable path, line, and entity-ID tie breakers.

Expected next-action behavior:

- `none`: confidence accepted and every required role materialized.
- `expand`: one explicit focus can recover a missing relationship.
- `refresh_index`: indexed content is stale.
- `manual_fallback`: retrieval is unavailable, irreducibly ambiguous, or still incomplete after one
  expansion.

### R4 — Add CLI parity and freshness guidance

Add CLI equivalents for the MCP workflow:

```console
monas-lens context expand "<task>" \
  --focus <target> \
  --known-hash <sha256> \
  --repository <id-or-path> \
  --max-tokens <count> \
  --json

monas-lens impact analyze \
  --task "<task>" \
  --repository <id-or-path> \
  --expected-path <path> \
  --json

monas-lens output compress [FILE|-] \
  --kind <auto|test|build|compiler|linter|stack_trace|git_diff> \
  --max-output-chars <count> \
  --json
```

Rules:

- `context expand` reuses `CommunityTools.expand_context`.
- `impact analyze` reuses the existing patch-impact service.
- `output compress` reads UTF-8 from a file or stdin and reuses the current compressor.
- CLI and MCP transports must not import each other.
- Normal JSON goes to stdout; structured errors go to stderr with existing exit-code conventions.

Freshness behavior:

- Perform a bounded, read-only Git changed-path check before repository-backed context resolution.
- Compare supported changed paths with indexed hashes when practical.
- If freshness cannot be established, report `unknown` without pretending the index is current.
- If stale, return `INDEX_STALE` plus `next_action=refresh_index` and bounded changed paths.
- Do not rebuild the index inside read-only MCP tools.

Update the embedded skill to version 1.1:

- consume snippets directly;
- obey `next_action`;
- use `recommended_focus_target` for the only permitted expansion;
- preserve all received content hashes;
- use manual grep/glob/view only after `manual_fallback`;
- report the fallback reason so quality regressions can be reproduced.

### R5 — Validation and release evidence

Required unit tests:

- extractor-version migration and forced one-time reparse;
- Go scanner/parser coverage;
- typed receiver success and ambiguity;
- direct export and re-export resolution;
- incoming implementation and outgoing interface traversal;
- override relationship derivation;
- route/registration relationships;
- multi-role snippet deduplication;
- required-role budget reservation;
- post-materialization confidence;
- deterministic next-action and focus selection;
- freshness diagnostics;
- CLI argument validation and stdin compression.

Required integration tests:

- MCP initialization still delivers the embedded skill.
- MCP resource matches CLI `skill --json`.
- MCP and CLI resolve/expand outputs are semantically equivalent.
- Expansion returns only unseen content hashes.
- A gold task completes with one resolve.
- A degraded gold task completes with one resolve plus one expansion.
- Stale index returns refresh guidance without mutating the database.
- Isolated wheel can initialize, index, load the skill, resolve, expand, and analyze impact.

Mandatory commands:

```console
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv lock --check
uv build
git diff --check
```

Run the new retrieval-quality benchmark after the normal quality gate. Public Community validation
must not begin until every R1 threshold passes.

## Definition of done

The revamp is complete only when:

- the full repository quality gate is green;
- Context Bundle schema 1.1 is documented and deterministic;
- CLI and MCP expose the same retrieval workflow;
- every gold task returns all required symbols;
- the normal case uses one discovery call;
- the bounded degraded case uses no more than two calls;
- agents do not need whole-file reads for gold tasks;
- token and latency release thresholds pass;
- failure cases return an explicit next action instead of silently forcing broad manual search.

## Next-session starting point

1. Read this file, `PHASE_5_IMPLEMENTATION_TASKS.md`, and `docs/SESSION_HANDOFF.md`.
2. Run `git status --short --branch`; preserve all current local changes.
3. Run the full quality gate once to confirm the known Go diagnostics failure.
4. Implement R0 only.
5. Re-run the full quality gate.
6. Continue to R1 only after the baseline is green.
