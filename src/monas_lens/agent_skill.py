"""Embedded operating guidance for AI agents using Monas Lens."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

AGENT_SKILL_SCHEMA_VERSION = "1.0"
AGENT_SKILL_VERSION = "1.2"
AGENT_SKILL_RESOURCE_URI = "monas-lens://agent-skill"

_INSTRUCTIONS = """# Monas Lens Agent Skill

Use Monas Lens as the primary repository-discovery path. Its job is to return the exact indexed
code ranges and their task-relevant relationships while avoiding repeated glob, grep, and
whole-file reads.

## Retrieval workflow

1. Before broad repository exploration, submit the complete coding task once.
   - MCP: call `resolve_task_context`.
   - CLI: run `monas-lens context resolve "<task>" --json`.
   - Pass the repository when more than one is registered. Pass a known file or symbol as a focus
     target instead of searching for it again.
2. Work directly from returned `snippets`. Treat each `relative_path`, `start_line`, `end_line`,
   `content`, `role`, `roles`, `evidence`, and `content_hash` as the authoritative focused read. Do
   not reopen an entire file when the returned content is sufficient.
3. Inspect `primary_targets`, `confidence`, `freshness`, `freshness_changed_paths`, `next_action`,
   `recommended_missing_roles`, `diagnostics`, and `truncated`.
   Related code should cover the relevant callers, dependencies/callees, interfaces, tests, and
   configuration for the task.
4. Obey `next_action`.
   - `none`: code from the returned snippets.
   - `expand`: perform the only permitted targeted expansion using `recommended_focus_target`.
   - `refresh_index`: rebuild the index before relying on indexed snippets.
   - `manual_fallback`: use a narrowly scoped manual discovery fallback and report its reason.
5. Perform at most one targeted expansion when requested.
   - MCP: call `expand_context` with one explicit `focus_target` and every previously returned
     `content_hash` in `known_content_hashes`.
   - CLI: run `monas-lens context expand "<task>" --focus <target>` and repeat `--known-hash` for
     every previously returned hash.
6. Use grep, glob, graph, search, or whole-file view only after `manual_fallback`. Scope fallback
   discovery to the returned reason and missing roles, and do not reread returned content.
7. After edits, call MCP `analyze_patch_impact`. Run relevant returned validation argument arrays
   through the normal approval path. Use `compress_command_output` for unusually large output.

## Readiness recovery

For MCP, use the `cli_command_prefix` appended to this skill. Append `init` to initialize or migrate
storage, append `repo add <path>` to register a repository, and append `index build <path>` to build
its index. A readiness error also includes the complete `recovery_command` argument array for the
immediate repair. Execute these arrays as commands; do not assume `monas-lens` is on `PATH`, and do
not install a similarly named package. From a Monas Lens source checkout, the equivalent explicit
form is `uv run --project <monas-lens-checkout> monas-lens <arguments>`.

After recovery, retry the original MCP call. If diagnostics say the index is stale, rebuild or
retry failed files before falling back to manual discovery.

## Efficiency contract

Aim for one context request and no more than one expansion. Prefer exact symbol snippets over full
files, preserve content hashes across calls, and report any manual fallback so retrieval gaps can
be measured and improved.
""".strip()


class AgentSkill(BaseModel):
    """Versioned agent guidance shared by MCP and CLI transports."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = AGENT_SKILL_SCHEMA_VERSION
    name: Literal["monas-lens"] = "monas-lens"
    version: Literal["1.2"] = AGENT_SKILL_VERSION
    instructions: str = _INSTRUCTIONS


def get_agent_skill(*, cli_command_prefix: tuple[str, ...] | None = None) -> AgentSkill:
    """Return the immutable Monas Lens agent skill."""

    instructions = _INSTRUCTIONS
    if cli_command_prefix is not None:
        encoded_prefix = json.dumps(cli_command_prefix)
        instructions = (
            f"{instructions}\n\n## Runtime CLI\n\n"
            "Use this exact argument prefix for recovery commands in this MCP environment:\n\n"
            f"`cli_command_prefix={encoded_prefix}`"
        )
    return AgentSkill(instructions=instructions)
