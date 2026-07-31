# Monas Lens — Phase 5 Community MCP Backlog

Status: Internal-ready baseline delivered in the current working tree
Source: `Monas_Lens_Full_Plan_v2.md`
Baseline: Phase 4 release gate passed

## Goal

Expose the local Context Compiler and bounded safety helpers to coding agents through an MCP stdio
subprocess. Internal readiness means an installed wheel can start the server, negotiate MCP,
advertise four read-only tools, and execute those tools without a web server, Docker, telemetry, or
repository upload.

## Delivered internal baseline

### P5-01 — SDK and stdio transport ✅

- Official MCP Python SDK pinned to `mcp>=1.27,<2`; v2 remains excluded until a dedicated migration.
- `monas-lens mcp` starts FastMCP over stdio with no network listener.
- Expected domain failures use MCP tool errors; stdout remains protocol-only.
- Tool annotations mark all current operations read-only, non-destructive, idempotent, and local.

### P5-02 — Context tools ✅

- `resolve_task_context` wraps `ContextCompiler` without importing CLI code.
- `expand_context` requires one explicit focus target and filters known content hashes so the
  response contains only new snippets.
- Existing Phase 4 repository isolation, confidence, widening, token budget, Git bounds, and
  deterministic contracts remain unchanged.

### P5-03 — Safety and compression tools ✅

- `analyze_patch_impact` maps bounded current Git hunks to indexed changed symbols, direct callers,
  routes, schema-like contracts, tests, conservative risks, unrelated paths, and validation argv.
- `compress_command_output` preserves failure/summary lines, collapses repeats, records omissions,
  and enforces input/output caps for test, build, compiler, linter, stack-trace, and Git output.

### P5-04 — Internal agent integration ✅

- Project-scoped Claude Code `.mcp.json` example is included.
- Codex CLI and project `.codex/config.toml` examples are documented without mutating user-global
  configuration.
- An official SDK client smoke test covers stdio initialization, tool discovery, and tool execution.

### P5-05 — Embedded agent skill ✅

- MCP initialization delivers the versioned Monas Lens operating skill before normal tool use.
- `monas-lens://agent-skill` exposes the same guidance as a read-only Markdown resource.
- `monas-lens skill [--json]` gives CLI-based agents the identical versioned contract.
- Guidance limits normal discovery to one context request and at most one targeted expansion.

### P5-06 — Retrieval-efficiency release gate ✅

- Build a gold task suite with expected primary symbols, callers, dependencies/callees,
  interfaces, tests, and configuration.
- Measure primary/related-symbol recall, redundant snippet rate, full-file fallback rate, discovery
  tool calls, returned tokens, and post-index latency.
- Gate public readiness on median one discovery call, p95 at most two calls, at least 60% fewer
  context tokens, and retrieval under 500 ms after indexing.
- Record local benchmark fallback reasons so missing relationships can be fixed instead of hidden by
  grep or glob.

### P5-07 — Related-symbol closure completeness ✅

- Resolve import aliases, re-exports, receiver/type-aware method calls, constructors,
  overrides/implementations, and framework registration/decorator edges.
- Build bounded role-aware closure that preserves required callers, dependencies/callees,
  interfaces, tests, and configuration before lower-value lexical matches.
- Add per-snippet relationship provenance and prevent token budgeting from silently removing every
  candidate for a required role.

### P5-08 — CLI parity and freshness ✅

- Add CLI equivalents for targeted expansion, patch impact, and output compression so MCP and CLI
  agents follow one workflow.
- Detect stale indexed files before context resolution and provide a bounded refresh or explicit
  recovery action.
- Return a machine-readable next action and recommended focus target when confidence is degraded or
  required roles are missing.

## Internal constraints

- Initialize storage and register/index a repository before calling repository-backed tools.
- `compress_command_output` is pure and remains available without an initialized database.
- One active repository is selected when a tool omits `repository`.
- Clients should call `resolve_task_context` first, `expand_context` at most once, and
  `analyze_patch_impact` after edits.
- Suggested validation commands are data only and are never executed by the MCP server.

## Deferred public-release work

- Linux and macOS client matrix beyond CI coverage.
- Signed release artifacts and public installation walkthrough/video.
- Long-running client soak tests and larger external benchmark repositories.
- MCP v2 migration after the stable SDK and migration guide are evaluated.
- Remote HTTP transport, OAuth, embeddings, semantic ranking, Pro features, telemetry, and cloud
  repository processing remain out of scope.
