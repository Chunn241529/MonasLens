from __future__ import annotations

import asyncio
from pathlib import Path

from monas_lens.config import Settings
from monas_lens.db.session import Database
from monas_lens.indexing.service import IndexService
from monas_lens.mcp.compression import compress_command_output
from monas_lens.mcp.impact import PatchImpactAnalyzer
from monas_lens.mcp.server import create_server
from monas_lens.mcp.service import CommunityTools
from monas_lens.repositories import RepositoryService
from monas_lens.retrieval.retriever import GitDiffHunk, GitDiffResult


class _GitDiff:
    def collect(self, repository_root: Path, *, max_hunks: int) -> GitDiffResult:
        assert repository_root.is_dir()
        assert max_hunks > 0
        return GitDiffResult(
            hunks=(
                GitDiffHunk(
                    relative_path="service.py",
                    old_start_line=2,
                    new_start_line=2,
                    content=(
                        "@@ -2,2 +2,2 @@\n"
                        "-def get_user() -> dict[str, str]:\n"
                        "+def get_user() -> dict[str, object]:\n"
                        "     return {'status': 'ok'}\n"
                    ),
                    content_hash="a" * 64,
                ),
            )
        )


def test_community_tools_resolve_and_expand_only_new_content(
    tmp_path: Path,
    database: Database,
    settings: Settings,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "service.py").write_text(
        "def helper() -> str:\n    return 'ok'\n\ndef run_service() -> str:\n    return helper()\n",
        encoding="utf-8",
    )
    repository = RepositoryService(database, settings).add(root)
    IndexService(database, settings).build(repository.id)
    tools = CommunityTools(database, settings)

    bundle = tools.resolve_task_context(
        "Explain run_service",
        repository.id,
        include_git_diff=False,
    )
    expansion = tools.expand_context(
        "Explain run_service",
        "run_service",
        repository.id,
        known_content_hashes=[snippet.content_hash for snippet in bundle.snippets],
    )

    assert bundle.snippets
    assert expansion.repository_id == repository.id
    assert expansion.snippets == ()
    assert expansion.omitted_known_snippets == len(bundle.snippets)


def test_patch_impact_reports_changed_routes_risks_and_unrelated_paths(
    tmp_path: Path,
    database: Database,
    settings: Settings,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
    (root / "service.py").write_text(
        "@app.get('/users')\ndef get_user() -> dict[str, str]:\n    return {'status': 'ok'}\n",
        encoding="utf-8",
    )
    repository = RepositoryService(database, settings).add(root)
    IndexService(database, settings).build(repository.id)

    impact = PatchImpactAnalyzer(
        database,
        settings,
        git_diff_adapter=_GitDiff(),
    ).analyze(repository.id, expected_paths=("other.py",))

    assert impact.changed_paths == ("service.py",)
    assert impact.changed_symbols[0].qualified_name == "get_user"
    assert impact.routes == impact.changed_symbols
    assert impact.unrelated_changes == ("service.py",)
    assert {risk.code for risk in impact.risks} == {
        "missing_regression_test",
        "route_contract_changed",
        "unrelated_change",
    }
    assert impact.validation_commands[0].arguments == ("python", "-m", "pytest")


def test_command_output_compression_keeps_failures_and_collapses_noise() -> None:
    output = "\n".join(
        [
            *("collecting" for _ in range(20)),
            *(f"progress {index}" for index in range(100)),
            "ERROR test_service.py::test_run - expected 2, actual 1",
            *(f"cleanup {index}" for index in range(30)),
        ]
    )

    summary = compress_command_output(output, command_kind="test", max_output_chars=2_000)

    assert "ERROR test_service.py" in summary.content
    assert summary.repeated_lines_collapsed == 19
    assert summary.omitted_lines > 0
    assert summary.truncated


def test_mcp_server_exposes_the_four_community_tools() -> None:
    tools = asyncio.run(create_server().list_tools())

    assert [tool.name for tool in tools] == [
        "resolve_task_context",
        "expand_context",
        "analyze_patch_impact",
        "compress_command_output",
    ]
    assert all(tool.inputSchema["type"] == "object" for tool in tools)
    assert all(tool.annotations is not None and tool.annotations.readOnlyHint for tool in tools)

    result = asyncio.run(
        create_server().call_tool(
            "compress_command_output",
            {"output": "FAILED example", "command_kind": "test"},
        )
    )
    assert result[1]["command_kind"] == "test"
    assert "FAILED example" in result[1]["content"]
