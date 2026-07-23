# Bàn giao phiên phát triển Monas Lens

Cập nhật lần cuối: 2026-07-24

## Mục đích

Tài liệu này là điểm bắt đầu cho phiên Codex tiếp theo. Hãy đọc tài liệu này trước khi
thay đổi code, sau đó đọc các ADR và báo cáo validation được liên kết bên dưới.

## Trạng thái Git và giấy phép

- Workspace: `D:\project\MonasLens`
- Nhánh hiện tại: `main`, theo dõi `origin/main`
- Remote: `https://github.com/Chunn241529/MonasLens.git`
- GitHub được xác nhận là public vào ngày 2026-07-23.
- Giấy phép: Apache-2.0.
- Toàn bộ phần triển khai Phase 1–2 hiện vẫn ở local, chưa commit và chưa push.
- `.gitignore` đã được sửa; các file ứng dụng, test, CI và tài liệu mới đang untracked.

Không được reset, xóa hoặc ghi đè các thay đổi local này. Trước khi tiếp tục, luôn chạy:

```console
git status --short --branch
git diff --check
```

## Phạm vi đã hoàn thành

### Phase 1 — Local application foundation

- Package Python 3.12, `uv.lock`, CLI `monas-lens` và workflow CI Windows/Linux.
- Pydantic settings với thứ tự ưu tiên TOML, biến môi trường và CLI override.
- Structured logging, đường dẫn local an toàn và mã lỗi CLI ổn định.
- SQLite với WAL, foreign keys, busy timeout và SQLAlchemy 2.
- Alembic migration có thể nâng/hạ phiên bản:
  - `0001_foundation`
  - `0002_structural_index`
- Quản lý repository: add, list, use, status và remove metadata.
- FastAPI health endpoints: `/health/live` và `/health/ready`.

### Phase 2 — Incremental structural index

- Scanner xác định thứ tự ổn định, hỗ trợ `.gitignore` lồng nhau và negation.
- Loại trừ symlink, binary, generated, file quá kích thước và các thư mục mặc định.
- SHA-256 hashing và incremental add/update/delete.
- Tree-sitter parser chạy offline cho Python, JavaScript, TypeScript, TSX và Dart.
- Trích xuất symbol, signature, parameter, return type, docstring, chunk và syntax fact.
- Ghi dữ liệu atomic theo file, cascade deletion và last-known-good khi parse lỗi.
- Full rebuild, retry failed, stale-file tracking và repository-level locking.
- JSON output cho các lệnh CLI phục vụ automation.

## Kết quả validation gần nhất

Validation đầy đủ được thực hiện ngày 2026-07-23:

- Ruff format: đạt.
- Ruff lint: đạt.
- Pyright: `0 errors`, `0 warnings`.
- Pytest: `39 passed`, `1 skipped`.
- Coverage: `86.72%`, cao hơn ngưỡng bắt buộc `85%`.
- Test symlink bị skip trên máy Windows hiện tại vì process không có quyền tạo symlink;
  test vẫn được bật trên Linux CI.
- `uv lock --check`: đạt, khóa 46 package.
- `uv build`: tạo thành công source distribution và wheel.
- Wheel được cài trong môi trường isolated, CLI hoạt động.
- `monas-lens doctor --json` xác nhận migration `0002_structural_index` và cả năm parser
  đều sẵn sàng.

Baseline self-index:

| Chỉ số | Full rebuild | Lần chạy không đổi |
|---|---:|---:|
| File hợp lệ | 43 | 43 |
| File được parse | 43 | 0 |
| File không đổi | 0 | 43 |
| File lỗi hoặc stale | 0 | 0 |
| Thời gian | 744.971 ms | 92.879 ms |

Dữ liệu structural đã lưu gồm 315 symbols, 288 chunks và 1.798 unresolved syntax facts.
Đây là baseline trên máy phát triển, không phải cam kết hiệu năng đa nền tảng.

## Lệnh khởi động lại công việc

```console
cd D:\project\MonasLens
uv sync --locked --all-groups
uv run monas-lens --version
uv run monas-lens init
uv run monas-lens repo add .
uv run monas-lens doctor
uv run monas-lens index build
uv run monas-lens index status
```

Chạy toàn bộ quality gate trước khi commit:

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

1. Kiểm tra `git status` và bảo toàn toàn bộ thay đổi Phase 1–2.
2. Đọc backlog, hai ADR và báo cáo validation.
3. Review diff Phase 1–2.
4. Chỉ commit/push khi có yêu cầu rõ ràng của người dùng.
5. Sau khi Phase 1–2 được chấp nhận, chọn backlog tiếp theo; các hạng mục đang để lại gồm
   FTS5, relationship graph, resolver/ranking, MCP, watcher, embeddings và Pro/Team.

## Giới hạn hiện tại

- Source file phải là UTF-8.
- Symlink bị bỏ qua.
- Route và test detection được thiết kế bảo thủ.
- Chưa có background watcher.
- Chưa có FTS5 search, graph resolution, embeddings, ranking hoặc MCP.
- Chưa có licensing, payment, Pro hoặc Team functionality.

## Quyết định và ràng buộc của phiên trước

- FourTIndex không được sử dụng trong phiên triển khai Phase 1–2 theo yêu cầu của người dùng.
- Quyết định này chỉ ghi nhận lịch sử phiên trước; phiên sau phải tuân theo yêu cầu mới nhất
  của người dùng và hướng dẫn hiện hành.
- Không có commit hoặc push nào được thực hiện.

## Tài liệu cần đọc

- [`../PHASE_1_2_IMPLEMENTATION_TASKS.md`](../PHASE_1_2_IMPLEMENTATION_TASKS.md)
- [`PHASE_1_2_VALIDATION.md`](PHASE_1_2_VALIDATION.md)
- [`architecture/0001-local-foundation.md`](architecture/0001-local-foundation.md)
- [`architecture/0002-structural-index.md`](architecture/0002-structural-index.md)
- [`../README.md`](../README.md)

