"""FastMCP stdio adapter for the local Community tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from monas_lens.config import load_settings
from monas_lens.db.migration import database_is_current
from monas_lens.db.session import Database
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.logging_config import configure_logging, operation_context
from monas_lens.mcp.compression import compress_command_output as compress_output
from monas_lens.mcp.service import CommunityTools


def create_server() -> FastMCP[None]:
    """Create a stateless stdio server backed by short-lived local runtimes."""

    server = FastMCP(
        "Monas Lens",
        instructions=(
            "Call resolve_task_context first. Call expand_context at most once for one missing "
            "relationship. After editing, call analyze_patch_impact. Validation commands are "
            "display-only argument arrays. Repository source remains local."
        ),
    )

    def _resolve_task_context(
        task: str,
        repository: str | None = None,
        focus_targets: list[str] | None = None,
        max_tokens: int | None = None,
        include_git_diff: bool = True,
    ) -> dict[str, Any]:
        """Mandatory first call: compile focused context for one coding task."""

        return _run_tool(
            lambda tools: tools.resolve_task_context(
                task,
                repository,
                focus_targets=focus_targets or (),
                max_tokens=max_tokens,
                include_git_diff=include_git_diff,
            ).model_dump(mode="json")
        )

    def _expand_context(
        task: str,
        focus_target: str,
        known_content_hashes: list[str] | None = None,
        repository: str | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Return only new context for one explicit missing relationship; call at most once."""

        return _run_tool(
            lambda tools: tools.expand_context(
                task,
                focus_target,
                repository,
                known_content_hashes=known_content_hashes or (),
                max_tokens=max_tokens,
            ).model_dump(mode="json")
        )

    def _analyze_patch_impact(
        task: str | None = None,
        repository: str | None = None,
        expected_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Analyze the bounded current Git diff against indexed symbols and relationships."""

        return _run_tool(
            lambda tools: tools.analyze_patch_impact(
                repository,
                task=task,
                expected_paths=expected_paths or (),
            ).model_dump(mode="json")
        )

    def _compress_command_output(
        output: str,
        command_kind: str = "auto",
        max_output_chars: int = 12_000,
    ) -> dict[str, Any]:
        """Compress test, build, compiler, linter, stack-trace, or Git output."""

        try:
            return compress_output(
                output,
                command_kind=command_kind,
                max_output_chars=max_output_chars,
            ).model_dump(mode="json")
        except MonasLensError as exc:
            raise ToolError(f"{exc.code.value}: {exc.message}") from None

    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    server.add_tool(
        _resolve_task_context,
        name="resolve_task_context",
        annotations=read_only,
    )
    server.add_tool(_expand_context, name="expand_context", annotations=read_only)
    server.add_tool(
        _analyze_patch_impact,
        name="analyze_patch_impact",
        annotations=read_only,
    )
    server.add_tool(
        _compress_command_output,
        name="compress_command_output",
        annotations=read_only,
    )
    return server


def run_stdio_server() -> None:
    """Run the Community MCP server over standard input/output."""

    create_server().run(transport="stdio")


def _run_tool[T](callback: Callable[[CommunityTools], T]) -> T:
    settings = load_settings()
    configure_logging(settings)
    if settings.database_path is None or not settings.database_path.exists():
        raise ToolError(f"{ErrorCode.DATABASE_NOT_INITIALIZED.value}: Run `monas-lens init` first.")
    database = Database(settings)
    try:
        if not database_is_current(database.engine):
            raise ToolError(
                f"{ErrorCode.DATABASE_NOT_INITIALIZED.value}: "
                "The local database requires initialization or migration."
            )
        with operation_context():
            return callback(CommunityTools(database, settings))
    except MonasLensError as exc:
        raise ToolError(f"{exc.code.value}: {exc.message}") from None
    finally:
        database.dispose()
