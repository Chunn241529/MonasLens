"""Incremental structural indexing orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from monas_lens.config import Settings
from monas_lens.db.models import IndexRunModel, IndexState, RepositoryModel
from monas_lens.db.session import Database
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.graph.builder import GraphBuilder, GraphBuildSummary
from monas_lens.indexing.contracts import FileCandidate, ParseStatus
from monas_lens.indexing.scanner import RepositoryScanner
from monas_lens.indexing.store import StoredFile, StructuralStore
from monas_lens.locking import repository_lock
from monas_lens.parsing.registry import ParserRegistry
from monas_lens.repositories import RepositoryRecord, RepositoryService


class IndexSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository_id: str
    run_id: str
    state: str
    scanned_files: int
    parsed_files: int
    unchanged_files: int
    deleted_files: int
    failed_files: int
    stale_files: int
    graph_refreshed_facts: int
    relationships: int
    graph_diagnostics: int
    graph_duration_ms: float
    duration_ms: float


class IndexStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository_id: str
    repository_path: Path
    state: str
    files: int
    symbols: int
    chunks: int
    facts: int
    stale_files: int
    relationships: int
    graph_diagnostics: int
    unresolved_relations: int
    ambiguous_relations: int
    unsupported_relations: int
    graph_dirty: bool
    last_indexed_at: datetime | None
    last_run_id: str | None


class IndexService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        scanner: RepositoryScanner | None = None,
        parsers: ParserRegistry | None = None,
    ) -> None:
        self._database = database
        self._settings = settings
        self._scanner = scanner or RepositoryScanner(settings)
        self._parsers = parsers or ParserRegistry()
        self._repositories = RepositoryService(database, settings)
        self._store = StructuralStore(database)
        self._graph = GraphBuilder(database)

    def build(
        self,
        identifier: str | Path | None = None,
        *,
        full: bool = False,
        retry_failed: bool = False,
    ) -> IndexSummary:
        repository = self._resolve_repository(identifier)
        with repository_lock(self._settings, repository.id):
            return self._run_index(
                repository,
                full=full,
                retry_failed=retry_failed,
            )

    def status(self, identifier: str | Path | None = None) -> IndexStatus:
        repository = self._resolve_repository(identifier)
        counts = self._store.counts(repository.id)
        graph_counts = self._graph.counts(repository.id)
        with self._database.session() as session:
            last_run = session.scalar(
                select(IndexRunModel)
                .where(IndexRunModel.repository_id == repository.id)
                .order_by(IndexRunModel.started_at.desc())
                .limit(1)
            )
        return IndexStatus(
            repository_id=repository.id,
            repository_path=repository.canonical_path,
            state=repository.index_state,
            files=counts.files,
            symbols=counts.symbols,
            chunks=counts.chunks,
            facts=counts.facts,
            stale_files=counts.stale_files,
            relationships=graph_counts.relationships,
            graph_diagnostics=graph_counts.diagnostics,
            unresolved_relations=graph_counts.unresolved,
            ambiguous_relations=graph_counts.ambiguous,
            unsupported_relations=graph_counts.unsupported,
            graph_dirty=self._graph.is_dirty(repository.id),
            last_indexed_at=repository.last_indexed_at,
            last_run_id=last_run.id if last_run is not None else None,
        )

    def _run_index(
        self,
        repository: RepositoryRecord,
        *,
        full: bool,
        retry_failed: bool,
    ) -> IndexSummary:
        started = datetime.now(UTC)
        start_clock = perf_counter()
        run_id = str(uuid4())
        self._start_run(repository.id, run_id, started, full)
        parsed = 0
        unchanged = 0
        deleted = 0
        failed = 0
        scanned = 0
        try:
            scan_result = self._scanner.scan(repository.canonical_path)
            scanned = len(scan_result.files)
            self._set_run_state(repository.id, run_id, IndexState.PARSING)
            stored = self._store.files(repository.id)
            candidates = {candidate.relative_path: candidate for candidate in scan_result.files}
            deletion_paths: list[str] = []
            for relative_path in sorted(stored.keys() - candidates.keys()):
                protected = any(
                    _scan_issue_protects(issue.relative_path, issue.code, relative_path)
                    for issue in scan_result.issues
                )
                if protected:
                    unchanged += 1
                else:
                    deletion_paths.append(relative_path)
            parse_candidates: list[FileCandidate] = []
            for candidate in scan_result.files:
                if self._should_parse(
                    stored.get(candidate.relative_path),
                    candidate,
                    full=full,
                    retry_failed=retry_failed,
                ):
                    parse_candidates.append(candidate)
                else:
                    unchanged += 1

            planned_paths = {
                *deletion_paths,
                *(candidate.relative_path for candidate in parse_candidates),
            }
            graph_was_dirty = self._graph.is_dirty(repository.id)
            previous_keys = self._graph.snapshot_keys(repository.id, planned_paths)
            changed_paths: set[str] = set()

            for relative_path in deletion_paths:
                if self._store.delete_file(repository.id, relative_path):
                    deleted += 1
                    changed_paths.add(relative_path)

            for candidate in parse_candidates:
                try:
                    source = self._read_stable_source(candidate)
                    source.decode("utf-8")
                    extraction = self._parsers.extract(
                        candidate.language,
                        candidate.relative_path,
                        source,
                    )
                except Exception as exc:
                    failed += 1
                    self._store.record_failure(
                        repository.id,
                        candidate,
                        error_code=_failure_code(exc),
                        error_message=_failure_message(exc),
                    )
                    continue
                self._store.replace_file(repository.id, candidate, extraction)
                parsed += 1
                changed_paths.add(candidate.relative_path)

            graph_summary = self._refresh_graph(
                repository.id,
                run_id,
                changed_paths=changed_paths,
                previous_keys=previous_keys,
                force_full=graph_was_dirty or full,
            )

            duration_ms = (perf_counter() - start_clock) * 1_000
            counts = self._store.counts(repository.id)
            self._finish_run(
                repository.id,
                run_id,
                duration_ms,
                scanned=scanned,
                parsed=parsed,
                unchanged=unchanged,
                deleted=deleted,
                failed=failed,
            )
            return IndexSummary(
                repository_id=repository.id,
                run_id=run_id,
                state=IndexState.READY.value,
                scanned_files=scanned,
                parsed_files=parsed,
                unchanged_files=unchanged,
                deleted_files=deleted,
                failed_files=failed,
                stale_files=counts.stale_files,
                graph_refreshed_facts=graph_summary.refreshed_facts,
                relationships=graph_summary.relationships,
                graph_diagnostics=graph_summary.diagnostics,
                graph_duration_ms=graph_summary.duration_ms,
                duration_ms=round(duration_ms, 3),
            )
        except Exception as exc:
            self._fail_run(repository.id, run_id, start_clock, exc)
            if isinstance(exc, MonasLensError):
                raise
            raise MonasLensError(
                ErrorCode.INDEX_FAILED,
                "The structural index run failed.",
            ) from exc

    def _refresh_graph(
        self,
        repository_id: str,
        run_id: str,
        *,
        changed_paths: set[str],
        previous_keys: dict[str, frozenset[str]],
        force_full: bool,
    ) -> GraphBuildSummary:
        if not force_full and not changed_paths:
            counts = self._graph.counts(repository_id)
            return GraphBuildSummary(
                refreshed_facts=0,
                relationships=counts.relationships,
                diagnostics=counts.diagnostics,
                full_rebuild=False,
                duration_ms=0.0,
            )
        self._set_run_state(repository_id, run_id, IndexState.BUILDING_GRAPH)
        return self._graph.refresh(
            repository_id,
            changed_paths=changed_paths,
            previous_keys=previous_keys,
            force_full=force_full,
        )

    def _resolve_repository(self, identifier: str | Path | None) -> RepositoryRecord:
        return (
            self._repositories.active()
            if identifier is None
            else self._repositories.get(identifier)
        )

    @staticmethod
    def _should_parse(
        previous: StoredFile | None,
        candidate: FileCandidate,
        *,
        full: bool,
        retry_failed: bool,
    ) -> bool:
        if full or previous is None:
            return True
        if previous.parse_status in {ParseStatus.FAILED, ParseStatus.STALE}:
            return retry_failed or previous.observed_hash != candidate.content_hash
        return previous.indexed_hash != candidate.content_hash

    @staticmethod
    def _read_stable_source(candidate: FileCandidate) -> bytes:
        source = candidate.absolute_path.read_bytes()
        if (
            len(source) != candidate.size_bytes
            or sha256(source).hexdigest() != candidate.content_hash
        ):
            raise MonasLensError(
                ErrorCode.INDEX_FAILED,
                "A source file changed between scanning and parsing.",
                details={"path": candidate.relative_path},
            )
        return source

    def _start_run(
        self,
        repository_id: str,
        run_id: str,
        started: datetime,
        full: bool,
    ) -> None:
        with self._database.session() as session:
            repository = session.get(RepositoryModel, repository_id)
            if repository is None:
                raise MonasLensError(
                    ErrorCode.REPOSITORY_NOT_FOUND,
                    "The repository was removed before indexing started.",
                )
            repository.index_state = IndexState.SCANNING.value
            repository.last_error_code = None
            session.add(
                IndexRunModel(
                    id=run_id,
                    repository_id=repository_id,
                    state=IndexState.SCANNING.value,
                    full_rebuild=full,
                    started_at=started,
                )
            )
            session.commit()

    def _set_run_state(self, repository_id: str, run_id: str, state: IndexState) -> None:
        with self._database.session() as session:
            repository = session.get(RepositoryModel, repository_id)
            run = session.get(IndexRunModel, run_id)
            if repository is not None:
                repository.index_state = state.value
            if run is not None:
                run.state = state.value
            session.commit()

    def _finish_run(
        self,
        repository_id: str,
        run_id: str,
        duration_ms: float,
        *,
        scanned: int,
        parsed: int,
        unchanged: int,
        deleted: int,
        failed: int,
    ) -> None:
        finished = datetime.now(UTC)
        with self._database.session() as session:
            repository = session.get(RepositoryModel, repository_id)
            run = session.get(IndexRunModel, run_id)
            if repository is not None:
                repository.index_state = IndexState.READY.value
                repository.last_indexed_at = finished
                repository.last_error_code = "partial_index_failure" if failed else None
            if run is not None:
                run.state = IndexState.READY.value
                run.finished_at = finished
                run.duration_ms = duration_ms
                run.scanned_files = scanned
                run.parsed_files = parsed
                run.unchanged_files = unchanged
                run.deleted_files = deleted
                run.failed_files = failed
                if failed:
                    run.error_code = "partial_index_failure"
                    run.error_message = f"{failed} file(s) could not be indexed"
            session.commit()

    def _fail_run(
        self,
        repository_id: str,
        run_id: str,
        start_clock: float,
        error: Exception,
    ) -> None:
        finished = datetime.now(UTC)
        with self._database.session() as session:
            repository = session.get(RepositoryModel, repository_id)
            run = session.get(IndexRunModel, run_id)
            error_code = _failure_code(error)
            if repository is not None:
                repository.index_state = IndexState.FAILED.value
                repository.last_error_code = error_code
            if run is not None:
                run.state = IndexState.FAILED.value
                run.finished_at = finished
                run.duration_ms = (perf_counter() - start_clock) * 1_000
                run.error_code = error_code
                run.error_message = _failure_message(error)
            session.commit()


def _failure_code(error: Exception) -> str:
    if isinstance(error, UnicodeError):
        return "unsupported_encoding"
    if isinstance(error, MonasLensError):
        return error.code.value
    if isinstance(error, OSError):
        return "source_read_failed"
    return ErrorCode.INTERNAL_ERROR.value


def _failure_message(error: Exception) -> str:
    if isinstance(error, UnicodeError):
        return "Source is not valid UTF-8."
    if isinstance(error, MonasLensError):
        return error.message[:500]
    if isinstance(error, OSError):
        return "Source could not be read."
    return "Unexpected indexing failure."


def _scan_issue_protects(
    issue_path: str,
    issue_code: str,
    stored_path: str,
) -> bool:
    if issue_code == "directory_unreadable":
        return not issue_path or stored_path.startswith(f"{issue_path}/")
    if issue_code in {
        "entry_unreadable",
        "stat_failed",
        "read_failed",
        "changed_during_scan",
    }:
        return stored_path == issue_path
    return False
