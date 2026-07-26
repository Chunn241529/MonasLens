# Phase 5 Internal MCP Setup

Validated: 2026-07-26  
Transport: local MCP stdio  
SDK: `mcp>=1.27,<2`

## Prepare Monas Lens

```console
uv sync --locked --all-groups
uv run monas-lens init
uv run monas-lens repo add D:\project\MonasLens
uv run monas-lens index build
uv run monas-lens context resolve "Explain ContextCompiler.resolve" --no-git-diff --json
```

The MCP process is started by the client. Running `uv run monas-lens mcp` directly waits for MCP
messages on stdin and writes protocol messages to stdout; that is expected.

## Codex

Codex can add the local server from the CLI:

```console
codex mcp add monas-lens -- uv run --project D:\project\MonasLens monas-lens mcp
codex mcp list
```

Or add a trusted project-local `.codex/config.toml` entry:

```toml
[mcp_servers.monas-lens]
command = "uv"
args = ["run", "--project", "D:\\project\\MonasLens", "monas-lens", "mcp"]
cwd = "D:\\project\\MonasLens"
enabled = true
startup_timeout_sec = 20
tool_timeout_sec = 60
enabled_tools = [
  "resolve_task_context",
  "expand_context",
  "analyze_patch_impact",
  "compress_command_output",
]
```

Restart Codex after changing MCP configuration, then inspect the server through `/mcp`.

## Claude Code

The repository includes a project-scoped `.mcp.json`. To add the same server explicitly:

```console
claude mcp add --transport stdio --scope project monas-lens -- uv run --project D:\project\MonasLens monas-lens mcp
claude mcp list
```

Within Claude Code, use `/mcp` to inspect connection status and tool count.

## Expected agent sequence

1. Call `resolve_task_context` before raw repository discovery.
2. Use `expand_context` at most once and pass hashes already received in
   `known_content_hashes`.
3. Make the code change.
4. Call `analyze_patch_impact` with the task and expected changed paths.
5. Run returned validation argument arrays through the agent's normal approval path.
6. Use `compress_command_output` before returning unusually large validation output.

## Recovery

- `database_not_initialized`: run `monas-lens init`.
- `repository_not_found`: run `monas-lens repo add <path>` or pass a registered repository ID.
- Empty or stale context: run `monas-lens index status --json`, then `index build` or
  `index retry-failed`.
- `patch_impact_failed`: confirm the registered path is a Git repository and `git diff HEAD --`
  succeeds locally.
- Client shows no tools: run `uv run monas-lens --help`, verify `mcp` is listed, then restart the
  client and inspect `/mcp`.
- MCP SDK v2 must not be installed until the `<2` pin is intentionally migrated.

## Client references

- [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp)
- [Claude Code MCP configuration](https://code.claude.com/docs/en/mcp)
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
