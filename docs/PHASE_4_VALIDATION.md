# Phase 4 Context Compiler Validation

Validated: 2026-07-26  
Scope: P4-01 through P4-09

## Delivered

- Immutable request, resolution, evidence, ranking, confidence, token, snippet, diagnostic, and
  bundle contracts.
- Pure deterministic task resolution and bounded two-stage parallel retrieval.
- Inspectable evidence ranking, identity/content deduplication, and stable tie-breaks.
- Versioned confidence formula with no more than one targeted depth-two widening pass.
- Model-agnostic heuristic token estimates, safety/envelope reserve, role caps, and line-aware
  cropping.
- Indexed-chunk materialization, bounded relevant Git hunks, and display-only validation argv.
- `ContextCompiler.resolve()` as the service entry point and
  `monas-lens context resolve` in human/JSON modes.
- Seven required mixed-language end-to-end scenarios and repeatable per-stage benchmark.

## Quality and packaging gates

- Ruff format: passed, 86 files checked.
- Ruff lint: passed.
- Pyright strict mode: `0 errors`, `0 warnings`.
- Pytest: `175 passed`, `1 skipped`.
- Branch coverage: `89.56%`, above the required `85%`.
- `uv lock --check`: passed with 64 locked packages.
- `uv build`: source distribution and wheel built successfully.
- Source distribution inspection: local cache entries absent; Phase 4/5 backlogs and validation
  documentation included after the final rebuild.
- An isolated environment installed the built wheel, initialized fresh storage, indexed 86 files,
  and resolved `ContextCompiler.resolve` under a 3,000-token budget. The result used 2,444
  estimated tokens and reported an `85.23%` reduction from pre-budget candidates.
- The official MCP SDK client negotiated stdio with the packaged server shape, discovered all four
  tools, and executed `compress_command_output` successfully.
- The existing Windows symlink test remains skipped because this process cannot create symlinks;
  it remains enabled on Linux CI.

## Behavioral evidence

- Missing import, wrong configuration key, broken API schema, expired session logic, cross-file
  rename, missing regression test, and unrelated-change tasks select their intended targets in a
  Python/JavaScript/TypeScript/Dart fixture.
- Repeating an unchanged request produces byte-equivalent sorted JSON.
- Required lexical failures use `context_retrieval_failed`; optional graph/Git failures degrade
  with bounded diagnostics.
- Every retrieval worker owns a fresh read session, and same-name entities remain repository
  scoped.
- Deliberately shuffled completion/input order does not change merged candidates, ranks, or bundle
  JSON.
- Confidence accepts coherent unique targets, preserves ambiguity, widens no more than once, and
  returns an explicit degraded result when uncertainty persists.
- Materialization uses the narrowest indexed chunk, deduplicates identical content while retaining
  provenance, and never exceeds the accepted estimated-token budget.
- Git collection uses fixed arguments, `shell=False`, repository-rooted execution, timeout, byte,
  path, and hunk caps.
- Task/source/diff/configuration content is absent from stage logs; only counts and durations are
  emitted.

## Local benchmark

Run:

```console
uv run python benchmarks/phase4_context_compiler.py --iterations 20
```

Measured on Windows 11 with Python 3.12.7 against the deterministic seven-file fixture:

| Stage | Median | p95 |
|---|---:|---:|
| Task resolver | 0.042 ms | 0.070 ms |
| Retrieval | 31.086 ms | 33.884 ms |
| Ranking + confidence | 5.378 ms | 8.465 ms |
| Context assembly | 1.511 ms | 2.019 ms |
| Total | 38.220 ms | 46.724 ms |

The fixture indexed in 93.905 ms. Median output contained seven ranked candidates and 40 estimated
context tokens. Its snippets are already very small, so the measured reduction ratio is `0.0`; the
public 60% token-reduction target requires larger representative repositories and is not inferred
from this microbenchmark. These measurements are a local regression baseline, not a cross-machine
performance guarantee.

## Recovery guidance

- If no repository is active, run `monas-lens repo add <path>` or pass `--repository`.
- If the database is missing or behind migration head, run `monas-lens init`.
- If index status is stale or graph-dirty, run `monas-lens index build`; use
  `index retry-failed` after fixing an unchanged stale file.
- If confidence is degraded, inspect `missing_roles` and reason codes. Supply `--focus` only when
  the intended path or symbol is known; do not treat a high rank score as certainty.
- If Git context is unavailable, rerun with `--no-git-diff`; indexed context remains usable.
- If a requested budget is rejected, use `256 <= --max-tokens <=` the configured
  `context_max_total_tokens`.

## Known limitations

- Task parsing is deterministic and rule-based; it does not infer language or intent with an LLM.
- Static repository-local graph resolution does not model dynamic dispatch, runtime loading, or
  whole-program calls.
- Token estimates are heuristic (`is_exact=false`) and intentionally model-agnostic.
- Current Git context covers the bounded working-tree diff, not Git history.
- Semantic retrieval, external expansion policy, persistent task state, patch application, and
  validation execution remain outside Phase 4.
