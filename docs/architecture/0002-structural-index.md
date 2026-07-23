# ADR 0002 — Offline structural index

Status: Accepted

## Context

Phase 2 must index Python, JavaScript, TypeScript, TSX, and Dart locally and incrementally. Parser
package compatibility changes quickly, and current language-pack releases download grammars on
first use, which weakens offline reproducibility.

## Decision

- Pin `tree-sitter==0.25.x` and `tree-sitter-language-pack==0.13.0`.
- Use the bundled language-pack wheel because it contains all initial grammars and requires no
  first-index network download.
- Isolate package APIs behind `ParserRegistry` and language adapters.
- Persist normalized files, symbols, syntax facts, and syntax-aware chunks.
- Keep syntax facts unresolved in Phase 2; Phase 3 will resolve graph relationships.
- Build deterministic symbol IDs from path, language, kind, qualified name, and signature.
- Store both observed and indexed hashes.
- Parse outside a write transaction and atomically replace one file's records.
- Preserve last known-good records when a new parse fails.
- Skip symlinks and reject source paths outside the registered root.
- Permit one indexing run per repository through a cross-platform file lock.

## Consequences

- A no-op run hashes eligible files but performs zero parses and zero structural replacements.
- A one-file edit replaces only that file's structural records.
- Parser errors do not destroy previously usable context.
- Grammar upgrades require an explicit compatibility change and fixture validation.
- Graph resolution, FTS5, embeddings, reranking, and MCP remain outside Phase 2.
