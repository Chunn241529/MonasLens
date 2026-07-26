"""Transport-independent Community MCP tool implementations."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from monas_lens.config import Settings
from monas_lens.db.session import Database
from monas_lens.mcp.compression import compress_command_output
from monas_lens.mcp.contracts import (
    CommandKind,
    CommandOutputSummary,
    ContextExpansion,
    PatchImpact,
)
from monas_lens.mcp.impact import PatchImpactAnalyzer
from monas_lens.retrieval.compiler import ContextCompiler
from monas_lens.retrieval.contracts import ContextBundle


class CommunityTools:
    """Provide the four local Community tools without transport coupling."""

    def __init__(self, database: Database, settings: Settings) -> None:
        self._compiler = ContextCompiler(database, settings)
        self._impact = PatchImpactAnalyzer(
            database,
            settings,
            compiler=self._compiler,
        )

    def resolve_task_context(
        self,
        task: str,
        repository: str | Path | None = None,
        *,
        focus_targets: Sequence[str] = (),
        max_tokens: int | None = None,
        include_git_diff: bool = True,
    ) -> ContextBundle:
        return self._compiler.resolve(
            {
                "task": task,
                "repository": repository,
                "focus_targets": tuple(focus_targets),
                "max_tokens": max_tokens,
                "include_git_diff": include_git_diff,
            }
        )

    def expand_context(
        self,
        task: str,
        focus_target: str,
        repository: str | Path | None = None,
        *,
        known_content_hashes: Sequence[str] = (),
        max_tokens: int | None = None,
    ) -> ContextExpansion:
        known = frozenset(known_content_hashes)
        bundle = self.resolve_task_context(
            task,
            repository,
            focus_targets=(focus_target,),
            max_tokens=max_tokens,
            include_git_diff=False,
        )
        snippets = tuple(
            snippet for snippet in bundle.snippets if snippet.content_hash not in known
        )
        omitted = len(bundle.snippets) - len(snippets)
        return ContextExpansion(
            repository_id=bundle.repository_id,
            focus_target=focus_target,
            confidence=bundle.confidence,
            snippets=snippets,
            diagnostics=bundle.diagnostics,
            omitted_known_snippets=omitted,
            truncated=bundle.truncated,
        )

    def analyze_patch_impact(
        self,
        repository: str | Path | None = None,
        *,
        task: str | None = None,
        expected_paths: Sequence[str] = (),
    ) -> PatchImpact:
        return self._impact.analyze(
            repository,
            task=task,
            expected_paths=expected_paths,
        )

    @staticmethod
    def compress_command_output(
        output: str,
        *,
        command_kind: CommandKind | str = CommandKind.AUTO,
        max_output_chars: int = 12_000,
    ) -> CommandOutputSummary:
        return compress_command_output(
            output,
            command_kind=command_kind,
            max_output_chars=max_output_chars,
        )
