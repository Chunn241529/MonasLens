"""Command-line interface for Monas Lens."""

from __future__ import annotations

import json
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer

from monas_lens import __version__
from monas_lens.config import (
    Settings,
    ensure_runtime_directories,
    load_settings,
)
from monas_lens.db.migration import database_is_current, upgrade_database
from monas_lens.db.session import Database
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.graph.contracts import GraphDirection
from monas_lens.graph.service import (
    GraphResponse,
    GraphService,
    parse_graph_direction,
    parse_relation_kinds,
)
from monas_lens.health import CheckResult, readiness_report
from monas_lens.indexing.service import IndexService, IndexStatus, IndexSummary
from monas_lens.logging_config import configure_logging, operation_context
from monas_lens.parsing.registry import ParserRegistry
from monas_lens.repositories import RepositoryRecord, RepositoryService
from monas_lens.search.service import SearchResponse, SearchService

app = typer.Typer(
    add_completion=False,
    help="Local-first repository intelligence for AI coding agents.",
    no_args_is_help=False,
)
repo_app = typer.Typer(help="Register and select local repositories.")
index_app = typer.Typer(help="Build and inspect the structural repository index.")
graph_app = typer.Typer(help="Query resolved repository relationships.")
app.add_typer(repo_app, name="repo")
app.add_typer(index_app, name="index")
app.add_typer(graph_app, name="graph")

_EXIT_CODES = {
    ErrorCode.CONFIGURATION_INVALID: 2,
    ErrorCode.INVALID_PATH: 2,
    ErrorCode.PATH_OUTSIDE_REPOSITORY: 2,
    ErrorCode.REPOSITORY_NOT_FOUND: 3,
    ErrorCode.REPOSITORY_LOCKED: 4,
    ErrorCode.GRAPH_QUERY_INVALID: 2,
    ErrorCode.SEARCH_QUERY_INVALID: 2,
    ErrorCode.DATABASE_NOT_INITIALIZED: 5,
    ErrorCode.DATABASE_UNAVAILABLE: 5,
    ErrorCode.PARSER_UNAVAILABLE: 6,
    ErrorCode.INDEX_FAILED: 7,
    ErrorCode.INTERNAL_ERROR: 1,
}


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"monas-lens {__version__}")
        raise typer.Exit


@app.callback(invoke_without_command=True)
def main(
    context: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            callback=_show_version,
            help="Show the installed version and exit.",
            is_eager=True,
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Show debug logs and unexpected tracebacks."),
    ] = False,
) -> None:
    """Run Monas Lens commands."""
    context.ensure_object(dict)
    context.obj["debug"] = debug
    if context.invoked_subcommand is None:
        typer.echo(context.get_help())


@app.command("init")
def initialize(
    context: typer.Context,
    json_output: Annotated[
        bool, typer.Option("--json", help="Return machine-readable JSON.")
    ] = False,
) -> None:
    """Initialize local Monas Lens storage."""
    with _command_errors(context, json_output):
        settings = _load_runtime_settings(context)
        ensure_runtime_directories(settings)
        database = Database(settings)
        try:
            upgrade_database(database.engine)
        finally:
            database.dispose()
        _emit(
            {
                "status": "initialized",
                "version": __version__,
                "data_dir": str(settings.data_dir),
                "database_path": str(settings.database_path),
            },
            json_output=json_output,
            human_message=f"Initialized Monas Lens in {settings.data_dir}",
        )


@app.command()
def doctor(
    context: typer.Context,
    json_output: Annotated[
        bool, typer.Option("--json", help="Return machine-readable JSON.")
    ] = False,
) -> None:
    """Check local configuration and database readiness."""
    with _command_errors(context, json_output):
        settings = _load_runtime_settings(context)
        database = Database(settings)
        try:
            report = readiness_report(settings, database)
        finally:
            database.dispose()
        parser_diagnostics = ParserRegistry().diagnostics()
        ready = report.ready and all(parser_diagnostics.values())
        payload = report.model_dump(mode="json")
        payload["status"] = "ok" if ready else "not_ready"
        payload["parsers"] = parser_diagnostics
        _emit(
            payload,
            json_output=json_output,
            human_message=_doctor_message(ready, report.checks, parser_diagnostics),
        )
        if not ready:
            raise typer.Exit(code=5)


@repo_app.command("add")
def repository_add(
    context: typer.Context,
    path: Annotated[Path, typer.Argument(help="Repository directory to register.")],
    activate: Annotated[
        bool, typer.Option("--activate/--no-activate", help="Make this repository active.")
    ] = True,
    json_output: Annotated[
        bool, typer.Option("--json", help="Return machine-readable JSON.")
    ] = False,
) -> None:
    """Register a local repository."""
    with _command_errors(context, json_output):
        with _repository_service(context) as service:
            repository = service.add(path, activate=activate)
        _emit_repository(repository, json_output, "Registered")


@repo_app.command("list")
def repository_list(
    context: typer.Context,
    json_output: Annotated[
        bool, typer.Option("--json", help="Return machine-readable JSON.")
    ] = False,
) -> None:
    """List registered repositories."""
    with _command_errors(context, json_output):
        with _repository_service(context) as service:
            repositories = service.list()
        payload = {
            "repositories": [repository.model_dump(mode="json") for repository in repositories]
        }
        if repositories:
            lines = [
                f"{'*' if repository.is_active else ' '} {repository.id} "
                f"{repository.canonical_path}"
                for repository in repositories
            ]
            message = "\n".join(lines)
        else:
            message = "No repositories registered."
        _emit(payload, json_output=json_output, human_message=message)


@repo_app.command("use")
def repository_use(
    context: typer.Context,
    identifier: Annotated[str, typer.Argument(help="Repository ID or path.")],
    json_output: Annotated[
        bool, typer.Option("--json", help="Return machine-readable JSON.")
    ] = False,
) -> None:
    """Select the active Community repository."""
    with _command_errors(context, json_output):
        with _repository_service(context) as service:
            repository = service.activate(identifier)
        _emit_repository(repository, json_output, "Activated")


@repo_app.command("status")
def repository_status(
    context: typer.Context,
    identifier: Annotated[
        str | None,
        typer.Argument(help="Repository ID or path; defaults to active."),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Return machine-readable JSON.")
    ] = False,
) -> None:
    """Show repository registration and index state."""
    with _command_errors(context, json_output):
        with _repository_service(context) as service:
            repository = service.get(identifier) if identifier is not None else service.active()
        _emit_repository(repository, json_output, "Repository")


@repo_app.command("remove")
def repository_remove(
    context: typer.Context,
    identifier: Annotated[str, typer.Argument(help="Repository ID or path.")],
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Confirm metadata removal without prompting."),
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Return machine-readable JSON.")
    ] = False,
) -> None:
    """Remove Monas Lens metadata without changing repository source."""
    with _command_errors(context, json_output):
        if not yes:
            if not sys.stdin.isatty():
                raise MonasLensError(
                    ErrorCode.CONFIGURATION_INVALID,
                    "Use --yes when removing repository metadata non-interactively.",
                )
            typer.confirm(
                "Remove this repository's Monas Lens metadata? Source files are preserved.",
                abort=True,
            )
        with _repository_service(context) as service:
            repository = service.remove(identifier)
        _emit_repository(repository, json_output, "Removed")


@index_app.command("build")
def index_build(
    context: typer.Context,
    identifier: Annotated[
        str | None,
        typer.Argument(help="Repository ID or path; defaults to active."),
    ] = None,
    full: Annotated[
        bool,
        typer.Option("--full", help="Reparse every eligible source file."),
    ] = False,
    retry_failed: Annotated[
        bool,
        typer.Option("--retry-failed", help="Retry unchanged failed or stale files."),
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Return machine-readable JSON.")
    ] = False,
) -> None:
    """Build or incrementally update the structural index."""
    with _command_errors(context, json_output):
        with _index_service(context) as service:
            summary = service.build(
                identifier,
                full=full,
                retry_failed=retry_failed,
            )
        _emit_index_summary(summary, json_output)


@index_app.command("retry-failed")
def index_retry_failed(
    context: typer.Context,
    identifier: Annotated[
        str | None,
        typer.Argument(help="Repository ID or path; defaults to active."),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Return machine-readable JSON.")
    ] = False,
) -> None:
    """Retry unchanged files that previously failed to parse."""
    with _command_errors(context, json_output):
        with _index_service(context) as service:
            summary = service.build(identifier, retry_failed=True)
        _emit_index_summary(summary, json_output)


@index_app.command("status")
def index_status(
    context: typer.Context,
    identifier: Annotated[
        str | None,
        typer.Argument(help="Repository ID or path; defaults to active."),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Return machine-readable JSON.")
    ] = False,
) -> None:
    """Show structural index counts and the latest run."""
    with _command_errors(context, json_output):
        with _index_service(context) as service:
            status = service.status(identifier)
        _emit_index_status(status, json_output)


@app.command("search")
def search_repository(
    context: typer.Context,
    query: Annotated[str, typer.Argument(help="Symbol, path, signature, or source terms.")],
    identifier: Annotated[
        str | None,
        typer.Option(
            "--repository",
            "-r",
            help="Repository ID or path; defaults to active.",
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            min=1,
            max=100,
            help="Maximum number of results.",
        ),
    ] = 20,
    json_output: Annotated[
        bool, typer.Option("--json", help="Return machine-readable JSON.")
    ] = False,
) -> None:
    """Search the local structural index."""
    with _command_errors(context, json_output):
        with _search_service(context) as service:
            response = service.search(query, identifier, limit=limit)
        _emit_search_response(response, json_output)


@graph_app.command("neighbors")
def graph_neighbors(
    context: typer.Context,
    target: Annotated[
        str,
        typer.Argument(help="Symbol ID, qualified name, name, file ID, or path."),
    ],
    identifier: Annotated[
        str | None,
        typer.Option(
            "--repository",
            "-r",
            help="Repository ID or path; defaults to active.",
        ),
    ] = None,
    direction: Annotated[
        str,
        typer.Option(
            "--direction",
            help="Relationship direction: outgoing, incoming, or both.",
        ),
    ] = GraphDirection.BOTH.value,
    relations: Annotated[
        str | None,
        typer.Option(
            "--relations",
            help="Comma-separated relationship kinds.",
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum number of edges (1-500)."),
    ] = 50,
    json_output: Annotated[
        bool, typer.Option("--json", help="Return machine-readable JSON.")
    ] = False,
) -> None:
    """Return direct incoming or outgoing relationships."""
    with _command_errors(context, json_output):
        with _graph_service(context) as service:
            response = service.neighbors(
                target,
                identifier,
                direction=parse_graph_direction(direction),
                relation_kinds=parse_relation_kinds(relations),
                limit=limit,
            )
        _emit_graph_response(response, json_output)


@graph_app.command("traverse")
def graph_traverse(
    context: typer.Context,
    target: Annotated[
        str,
        typer.Argument(help="Symbol ID, qualified name, name, file ID, or path."),
    ],
    identifier: Annotated[
        str | None,
        typer.Option(
            "--repository",
            "-r",
            help="Repository ID or path; defaults to active.",
        ),
    ] = None,
    direction: Annotated[
        str,
        typer.Option(
            "--direction",
            help="Relationship direction: outgoing, incoming, or both.",
        ),
    ] = GraphDirection.BOTH.value,
    relations: Annotated[
        str | None,
        typer.Option(
            "--relations",
            help="Comma-separated relationship kinds.",
        ),
    ] = None,
    depth: Annotated[
        int,
        typer.Option("--depth", help="Traversal depth (1-5)."),
    ] = 2,
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum number of edges (1-500)."),
    ] = 200,
    json_output: Annotated[
        bool, typer.Option("--json", help="Return machine-readable JSON.")
    ] = False,
) -> None:
    """Traverse repository relationships with bounded breadth-first search."""
    with _command_errors(context, json_output):
        with _graph_service(context) as service:
            response = service.traverse(
                target,
                identifier,
                direction=parse_graph_direction(direction),
                relation_kinds=parse_relation_kinds(relations),
                depth=depth,
                limit=limit,
            )
        _emit_graph_response(response, json_output)


def _load_runtime_settings(context: typer.Context) -> Settings:
    settings = load_settings()
    configure_logging(settings, debug=bool(context.obj.get("debug", False)))
    return settings


@contextmanager
def _ready_database(context: typer.Context) -> Generator[tuple[Database, Settings]]:
    settings = _load_runtime_settings(context)
    if settings.database_path is None or not settings.database_path.exists():
        raise MonasLensError(
            ErrorCode.DATABASE_NOT_INITIALIZED,
            "Monas Lens is not initialized. Run `monas-lens init` first.",
        )
    database = Database(settings)
    try:
        if not database_is_current(database.engine):
            raise MonasLensError(
                ErrorCode.DATABASE_NOT_INITIALIZED,
                "The local database requires initialization or migration.",
            )
        yield database, settings
    finally:
        database.dispose()


@contextmanager
def _repository_service(context: typer.Context) -> Generator[RepositoryService]:
    with _ready_database(context) as (database, settings):
        yield RepositoryService(database, settings)


@contextmanager
def _index_service(context: typer.Context) -> Generator[IndexService]:
    with _ready_database(context) as (database, settings):
        yield IndexService(database, settings)


@contextmanager
def _search_service(context: typer.Context) -> Generator[SearchService]:
    with _ready_database(context) as (database, settings):
        yield SearchService(database, settings)


@contextmanager
def _graph_service(context: typer.Context) -> Generator[GraphService]:
    with _ready_database(context) as (database, settings):
        yield GraphService(database, settings)


@contextmanager
def _command_errors(context: typer.Context, json_output: bool) -> Generator[None]:
    try:
        with operation_context():
            yield
    except MonasLensError as exc:
        _emit_error(exc, json_output)
        raise typer.Exit(code=_EXIT_CODES[exc.code]) from exc
    except typer.Exit:
        raise
    except Exception as exc:
        if bool(context.obj.get("debug", False)):
            raise
        error = MonasLensError(
            ErrorCode.INTERNAL_ERROR,
            "Monas Lens encountered an unexpected internal error.",
        )
        _emit_error(error, json_output)
        raise typer.Exit(code=1) from exc


def _emit_repository(repository: RepositoryRecord, json_output: bool, action: str) -> None:
    _emit(
        repository.model_dump(mode="json"),
        json_output=json_output,
        human_message=(
            f"{action} {repository.display_name} ({repository.id})\n"
            f"Path: {repository.canonical_path}\n"
            f"Index state: {repository.index_state}"
        ),
    )


def _emit_index_summary(summary: IndexSummary, json_output: bool) -> None:
    _emit(
        summary.model_dump(mode="json"),
        json_output=json_output,
        human_message=(
            f"Index run {summary.run_id}: {summary.state}\n"
            f"Scanned: {summary.scanned_files}, parsed: {summary.parsed_files}, "
            f"unchanged: {summary.unchanged_files}, deleted: {summary.deleted_files}, "
            f"failed: {summary.failed_files}, stale: {summary.stale_files}\n"
            f"Relationships: {summary.relationships}, diagnostics: "
            f"{summary.graph_diagnostics}, refreshed facts: "
            f"{summary.graph_refreshed_facts}\n"
            f"Duration: {summary.duration_ms:.3f} ms"
        ),
    )


def _emit_index_status(status: IndexStatus, json_output: bool) -> None:
    _emit(
        status.model_dump(mode="json"),
        json_output=json_output,
        human_message=(
            f"Repository: {status.repository_path}\n"
            f"State: {status.state}\n"
            f"Files: {status.files}, symbols: {status.symbols}, "
            f"chunks: {status.chunks}, facts: {status.facts}, "
            f"stale files: {status.stale_files}\n"
            f"Relationships: {status.relationships}, graph diagnostics: "
            f"{status.graph_diagnostics} "
            f"(unresolved: {status.unresolved_relations}, "
            f"ambiguous: {status.ambiguous_relations}, "
            f"unsupported: {status.unsupported_relations}), "
            f"graph dirty: {status.graph_dirty}"
        ),
    )


def _emit_search_response(response: SearchResponse, json_output: bool) -> None:
    if not response.results:
        human_message = f"No results for: {response.query}"
    else:
        lines: list[str] = []
        for position, result in enumerate(response.results, start=1):
            label = result.qualified_name or result.name or result.kind
            lines.append(
                f"{position}. {label} [{result.match_type}, {result.score:.3f}]\n"
                f"   {result.relative_path}:{result.start_line}-{result.end_line}\n"
                f"   {result.snippet}"
            )
        human_message = "\n".join(lines)
    _emit(
        response.model_dump(mode="json"),
        json_output=json_output,
        human_message=human_message,
    )


def _emit_graph_response(response: GraphResponse, json_output: bool) -> None:
    node_labels = {
        node.id: node.qualified_name or node.name or node.relative_path for node in response.nodes
    }
    edge_lines = [
        (
            f"{edge.kind}: {node_labels[edge.source_id]} -> "
            f"{node_labels[edge.target_id]} "
            f"[{edge.resolution_strategy}, {edge.confidence:.2f}]"
        )
        for edge in response.edges
    ]
    root_label = response.root.qualified_name or response.root.name or response.root.relative_path
    human_message = "\n".join(
        [
            f"Graph for {root_label}: {len(response.edges)} relationship(s), "
            f"{len(response.nodes)} node(s)",
            *edge_lines,
            *(["Result limit reached; traversal was truncated."] if response.truncated else []),
        ]
    )
    _emit(
        response.model_dump(mode="json"),
        json_output=json_output,
        human_message=human_message,
    )


def _emit(
    payload: dict[str, Any],
    *,
    json_output: bool,
    human_message: str,
) -> None:
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        typer.echo(human_message)


def _emit_error(error: MonasLensError, json_output: bool) -> None:
    if json_output:
        typer.echo(
            json.dumps({"error": error.as_dict()}, ensure_ascii=False, sort_keys=True),
            err=True,
        )
    else:
        typer.echo(f"Error [{error.code.value}]: {error.message}", err=True)


def _doctor_message(
    ready: bool,
    checks: tuple[CheckResult, ...],
    parser_diagnostics: dict[str, bool],
) -> str:
    check_lines = [
        f"{'OK' if check.ok else 'FAIL'} {check.name}: {check.detail}" for check in checks
    ]
    parser_lines = [
        f"{'OK' if available else 'FAIL'} parser {language}"
        for language, available in parser_diagnostics.items()
    ]
    return "\n".join(
        [
            f"Monas Lens is {'ready' if ready else 'not ready'}.",
            *check_lines,
            *parser_lines,
        ]
    )
