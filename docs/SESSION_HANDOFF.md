# Bàn giao phiên phát triển Monas Lens

Cập nhật lần cuối: 2026-07-24

## Mục đích

Đây là điểm bắt đầu cho phiên Codex tiếp theo. Phase 3 đã hoàn tất; không tiếp tục thêm hạng mục
P3 nếu không phát hiện regression. Đọc tài liệu này, backlog Phase 3, ADR 0003, báo cáo
validation và roadmap gốc trước khi thay đổi code.

## Trạng thái Git

- Workspace: `D:\project\MonasLens`
- Nhánh: `main`, theo dõi `origin/main`
- Remote: `https://github.com/Chunn241529/MonasLens.git`
- Giấy phép: Apache-2.0; GitHub được xác nhận public ngày 2026-07-23.
- Phase 1–2 đã được commit tại `a651e11` (`phase 1,2`).
- Toàn bộ P3-01 đến P3-08 đang ở worktree local, chưa commit và chưa push.
- Không reset, xóa hoặc ghi đè các thay đổi local Phase 3.
- Worktree hiện không có defect Phase 3 đã biết hoặc quality gate chưa đạt.

Luôn kiểm tra trước khi tiếp tục:

```console
git status --short --branch
git diff --check
```

## Phạm vi đã hoàn thành

### Phase 1 — Local application foundation

- Package Python 3.12, CLI `monas-lens`, dependency lock và CI Windows/Linux.
- Pydantic settings, structured logging, đường dẫn local an toàn và mã lỗi ổn định.
- SQLite WAL, foreign keys, busy timeout và SQLAlchemy 2.
- Repository lifecycle và FastAPI health/readiness.

### Phase 2 — Incremental structural index

- Scanner ổn định, `.gitignore` lồng nhau, negation và bộ lọc file an toàn.
- Tree-sitter offline cho Python, JavaScript, TypeScript, TSX và Dart.
- Symbol, signature, parameter, return type, docstring, chunk và syntax fact.
- Incremental add/update/delete, full rebuild, locking và stale-file tracking.
- Ghi atomic theo file và bảo toàn last-known-good khi parse thất bại.

### Phase 3 — Search and relationship graph

- Migration có thể nâng/hạ:
  - `0001_foundation`
  - `0002_structural_index`
  - `0003_search_index`
  - `0004_relationship_graph`
- SQLite FTS5 projection, trigger đồng bộ và backfill dữ liệu Phase 2.
- Exact symbol/qualified-name lookup trước lexical ranking có giới hạn.
- Kết quả search deterministic, repository-scoped, deduplicate và có snippet/range.
- Normalizer fact thuần cho năm ngôn ngữ, tách module/path, symbol và configuration target.
- Graph bảo thủ với `imports`, `calls`, `inherits`, `implements`, `tested_by`,
  `configured_by`.
- Ambiguous, unresolved và unsupported target tạo diagnostic, không tạo cạnh suy đoán.
- Edge ID ổn định; graph refresh theo changed file và dependency key của inbound fact.
- Last-known-good structural, lexical và graph được giữ nguyên khi replacement thất bại.
- Graph query one-hop và traversal có direction, relation filter, depth/result cap, chống cycle.
- CLI:
  - `monas-lens search`
  - `monas-lens graph neighbors`
  - `monas-lens graph traverse`
  - `monas-lens index status` có graph counts và diagnostic counts.
- Benchmark lặp lại được tại `benchmarks/phase3_search_graph.py`.

## Validation gần nhất

Validation đầy đủ ngày 2026-07-24:

- Ruff format: đạt, 58 file.
- Ruff lint: đạt.
- Pyright strict: `0 errors`, `0 warnings`.
- Pytest: `81 passed`, `1 skipped`.
- Coverage: `89.76%`, vượt ngưỡng `85%`.
- Test symlink bị skip trên Windows do process không có quyền tạo symlink; vẫn bật trên Linux CI.
- `uv lock --check`: đạt, 46 package.
- `uv build`: tạo thành công sdist và wheel.
- `git diff --check`: đạt, chỉ có cảnh báo chuyển đổi line ending trên Windows.
- Wheel được cài offline trong môi trường Python 3.12 isolated.
- Wheel smoke đã init database, index 58 file, tạo 903 relationship, search và graph query thành
  công.
- Downgrade database có dữ liệu `0004 → 0003 → 0002`, sau đó upgrade/backfill về head: đạt.
- Mixed-language build, no-op, update, rename, delete, parse failure, recovery và repository
  isolation: đạt.

Benchmark fixture bảy file, 20 vòng:

| Chỉ số | Median | p95 |
|---|---:|---:|
| Exact lookup | 0.728 ms | 0.878 ms |
| FTS ranking | 0.652 ms | 0.729 ms |
| Graph one-hop | 1.969 ms | 2.190 ms |

Full index mất 138.021 ms, full graph build 11.858 ms; one-file incremental index mất
47.909 ms và graph refresh 6.636 ms. Đây là baseline local, không phải cam kết đa nền tảng.

## Điểm dừng chính xác

- P3-01 đến P3-08 đã hoàn tất và backlog Phase 3 đã chuyển sang trạng thái delivered.
- Không còn bước triển khai hoặc validation Phase 3 bắt buộc.
- Sản phẩm build được; wheel isolated đã chạy được migration, index, search và graph query.
- Chưa có quyết định triển khai Phase 4 và chưa tạo backlog Phase 4.
- Bước tiếp theo theo roadmap gốc là **Phase 4 — Context Compiler**, không phải semantic
  embeddings. Phạm vi roadmap gồm Task Resolver, Parallel Retriever, Ranker, Confidence Gate,
  Context Bundle và Token Estimator.

## Lệnh khởi động lại

```console
cd D:\project\MonasLens
uv sync --locked --all-groups
uv run monas-lens init
uv run monas-lens repo add .
uv run monas-lens index build
uv run monas-lens index status --json
uv run monas-lens search GraphService --json
uv run monas-lens graph neighbors GraphService.neighbors --relations calls --json
uv run monas-lens graph traverse GraphService.neighbors --depth 2 --json
```

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

1. Kiểm tra và bảo toàn toàn bộ diff local P3-01 đến P3-08.
2. Đọc `PHASE_3_IMPLEMENTATION_TASKS.md`, ADR 0003, `PHASE_3_VALIDATION.md` và mục
   `Phase 4 — Context Compiler` trong `Monas_Lens_Full_Plan_v2.md`.
3. Không chạy lại toàn bộ Phase 3 hoặc sửa code Phase 3 nếu không có regression/evidence mới.
4. Không commit hoặc push nếu người dùng chưa yêu cầu rõ ràng.
5. Nếu người dùng yêu cầu tiếp tục roadmap, tạo `PHASE_4_IMPLEMENTATION_TASKS.md` trước khi code;
   chia nhỏ Task Resolver, Parallel Retriever, Ranker, Confidence Gate, Context Bundle và Token
   Estimator thành task có dependency, exit criteria, test và performance gate.
6. Chỉ bắt đầu P4-01 sau khi backlog Phase 4 đã chốt contract đầu vào/đầu ra và ranh giới với
   search/graph hiện có.

## Giới hạn hiện tại

- Source phải là UTF-8; symlink bị bỏ qua.
- Import/call resolution là static, repository-local và cố ý bảo thủ.
- Dynamic dispatch, runtime loading, generated dependency injection và whole-program call
  analysis chưa được mô hình hóa.
- Test/configuration detection chỉ hỗ trợ các syntax form đã khai báo.
- Chưa có background watcher, embeddings, hybrid ranking, context compiler hoặc MCP.
- Chưa có licensing, payment, Pro hoặc Team functionality.

## Ràng buộc phiên này

- Không sử dụng FourTIndex theo yêu cầu của người dùng.
- Không commit hoặc push phần triển khai Phase 3.

## Tài liệu cần đọc

- [`../Monas_Lens_Full_Plan_v2.md`](../Monas_Lens_Full_Plan_v2.md)
- [`../PHASE_3_IMPLEMENTATION_TASKS.md`](../PHASE_3_IMPLEMENTATION_TASKS.md)
- [`PHASE_3_VALIDATION.md`](PHASE_3_VALIDATION.md)
- [`PHASE_3_LEXICAL_SEARCH_VALIDATION.md`](PHASE_3_LEXICAL_SEARCH_VALIDATION.md)
- [`PHASE_1_2_VALIDATION.md`](PHASE_1_2_VALIDATION.md)
- [`architecture/0003-lexical-search-and-graph-foundation.md`](architecture/0003-lexical-search-and-graph-foundation.md)
- [`../README.md`](../README.md)
