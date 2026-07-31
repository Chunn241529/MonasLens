# Bàn giao phiên phát triển Monas Lens

Cập nhật lần cuối: 2026-07-30

## Mục đích

Đây là điểm bắt đầu cho phiên tiếp theo. Phase 1–4 đã hoàn tất trong worktree hiện tại. Phase 5 đã
có baseline MCP stdio dùng nội bộ với đủ bốn Community tools; public-release validation vẫn là bước
tiếp theo. Đọc tài liệu này, backlog Phase 5, Phase 4 validation, và roadmap gốc trước khi thay đổi
code.

## Trạng thái Git

- Workspace: `D:\project\MonasLens`
- Nhánh: `main`, theo dõi `origin/main`
- Remote: `https://github.com/Chunn241529/MonasLens.git`
- Giấy phép: Apache-2.0.
- Phase 1–2 đã được commit tại `a651e11` (`phase 1,2`).
- Phase 3, Phase 4, và baseline Phase 5 đang ở worktree local, chưa commit và chưa push.
- Không reset, xóa, hoặc ghi đè các thay đổi local.
- Không commit hoặc push nếu người dùng chưa yêu cầu rõ ràng.

Luôn kiểm tra trước khi tiếp tục:

```console
git status --short --branch
git diff --check
```

## Phạm vi đã hoàn thành

### Phase 1 — Local application foundation

- Python 3.12 package, Typer CLI, dependency lock, CI Windows/Linux.
- Pydantic settings, structured logging, local path/error safety.
- SQLite WAL/foreign keys/busy timeout, SQLAlchemy 2, migrations, repositories, health endpoints.

### Phase 2 — Incremental structural index

- Deterministic scanner with layered `.gitignore`, binary/size/generated-file filters.
- Offline Tree-sitter for Python, JavaScript, TypeScript, TSX, Dart, and Go.
- Symbols, chunks, syntax facts, stable identities, atomic incremental replacement, last-known-good
  recovery, locking, and stale-file tracking.

### Phase 3 — Search and relationship graph

- SQLite FTS5 exact/lexical search and deterministic repository-scoped results.
- Conservative imports, calls, inheritance, implementation, test, and configuration graph.
- Incremental graph refresh, explicit diagnostics, cycle-safe bounded queries, CLI and benchmark.
- Reversible migration head is `0005_extractor_version`.

### Phase 4 — Context Compiler ✅

- P4-01 through P4-09 delivered.
- Immutable contracts, deterministic task resolver, bounded parallel retriever, ranker, confidence
  gate, token estimator, focused bundle builder, Git hunks, and validation suggestions.
- `ContextCompiler.resolve()` is the single orchestration entry point.
- CLI: `monas-lens context resolve <task> [--repository] [--focus] [--max-tokens]
  [--no-git-diff] [--json]`.
- Seven required mixed-language scenarios, deterministic serialization, benchmark, README, and
  `docs/PHASE_4_VALIDATION.md` are present.

### Phase 5 — Retrieval-quality release gate ✅

- Official MCP Python SDK pinned to `mcp>=1.27,<2`; lock currently resolves `mcp==1.28.1`.
- `monas-lens mcp` runs FastMCP over local stdio only.
- Read-only tools:
  - `resolve_task_context`
  - `expand_context`
  - `analyze_patch_impact`
  - `compress_command_output`
- Context tools reuse Phase 4 service contracts and do not import CLI code.
- Expansion filters known content hashes; patch impact is current-diff/index based and bounded;
  output compression preserves failures/summaries and reports omissions.
- Context schema 1.1 includes multi-role snippets, relationship evidence, deterministic
  `next_action`, focus guidance, and stale-index recovery without database mutation.
- CLI parity is available through `context expand`, `impact analyze`, and `output compress`.
- The 13-case, three-repetition quality benchmark passes with 100% primary and role recall, one
  discovery call at p95, zero manual fallbacks, and 91.01% estimated token reduction.
- Codex and Claude Code setup is documented in `docs/PHASE_5_INTERNAL_SETUP.md`; project-scoped
  Claude configuration is in `.mcp.json`.

## Validation gần nhất

Full quality gate ngày 2026-07-30:

- Ruff format: đạt, 93 files.
- Ruff lint: đạt.
- Pyright strict: `0 errors`, `0 warnings`.
- Pytest: `191 passed`, `1 skipped`.
- Branch coverage: `90.22%` (yêu cầu `>=85%`).
- `uv lock --check`: đạt, 64 packages.
- `uv build`: tạo thành công sdist và wheel.
- Benchmark Phase 5 (13 case, 3 vòng): primary top-1/top-3 và required/optional role recall đều
  `100%`; p95 discovery calls `1`; token reduction `91.01%`; p95 retrieval `175.775 ms`.
- Source archive không chứa `.uv-cache` và có đủ Phase 4/5 docs/backlogs.
- Isolated wheel smoke đã init state mới, index repository, load skill 1.2, resolve schema 1.1,
  expand, và analyze impact; official MCP SDK client smoke đã handshake/list/call tool thành công.
- Test symlink bị skip trên Windows do process không có quyền tạo symlink; vẫn bật trên Linux CI.

## Lệnh sử dụng nội bộ

```console
cd D:\project\MonasLens
uv sync --locked --all-groups
uv run monas-lens init
uv run monas-lens repo add D:\project\MonasLens
uv run monas-lens index build
uv run monas-lens context resolve "Explain ContextCompiler.resolve" --no-git-diff --json
uv run monas-lens mcp
```

MCP server chờ protocol trên stdin; không in banner hoặc JSON ứng dụng thường lên stdout.

Quality gate:

```console
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv lock --check
uv build
git diff --check
```

## Điểm bắt đầu đề xuất cho phiên sau

1. Bảo toàn toàn bộ diff local và xác nhận final smoke vẫn xanh.
2. Tiếp tục Phase 5 public-release gate: client matrix Linux/macOS, wheel-installed MCP soak test,
   public installation walkthrough, and larger benchmark repositories.
3. Không nâng MCP SDK lên v2 cho đến khi stable release và migration guide được đánh giá riêng.
4. Không bắt đầu embeddings/Qdrant/reranker, Pro, licensing, billing, SePay, hoặc Team trong repo này
   nếu chưa có yêu cầu/phê duyệt riêng.
5. Không commit hoặc push nếu người dùng chưa yêu cầu rõ ràng.

## Giới hạn hiện tại

- Source phải là UTF-8; symlink bị bỏ qua.
- Static relationship resolution cố ý bảo thủ và repository-local.
- Token estimate là heuristic, không phải exact model tokenizer.
- Patch impact chỉ dùng current Git diff và indexed relationships; chưa có Git history hoặc semantic
  impact analysis.
- MCP chỉ có stdio local, không có remote HTTP/OAuth/background daemon.
- Chưa có embeddings, hybrid ranking, persistent MCP call ledger, licensing, payment, Pro, hoặc Team.

## Tài liệu cần đọc

- [`../PHASE_5_IMPLEMENTATION_TASKS.md`](../PHASE_5_IMPLEMENTATION_TASKS.md)
- [`PHASE_5_INTERNAL_SETUP.md`](PHASE_5_INTERNAL_SETUP.md)
- [`PHASE_4_VALIDATION.md`](PHASE_4_VALIDATION.md)
- [`../PHASE_4_IMPLEMENTATION_TASKS.md`](../PHASE_4_IMPLEMENTATION_TASKS.md)
- [`architecture/0004-context-compiler-contracts.md`](architecture/0004-context-compiler-contracts.md)
- [`../Monas_Lens_Full_Plan_v2.md`](../Monas_Lens_Full_Plan_v2.md)
- [`../README.md`](../README.md)
