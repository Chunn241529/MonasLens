from __future__ import annotations

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_server_negotiates_and_executes_a_tool() -> None:
    async def smoke() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=("-m", "monas_lens", "mcp"),
        )
        async with (
            stdio_client(parameters) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            initialized = await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool(
                "compress_command_output",
                {
                    "output": "progress\nFAILED example\nsummary",
                    "command_kind": "test",
                },
            )

        assert initialized.serverInfo.name == "Monas Lens"
        assert [tool.name for tool in tools.tools] == [
            "resolve_task_context",
            "expand_context",
            "analyze_patch_impact",
            "compress_command_output",
        ]
        assert not result.isError
        assert result.structuredContent is not None
        assert result.structuredContent["command_kind"] == "test"
        assert "FAILED example" in result.structuredContent["content"]

    asyncio.run(smoke())
