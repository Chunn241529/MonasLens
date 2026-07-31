from __future__ import annotations

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from monas_lens.agent_skill import AGENT_SKILL_RESOURCE_URI, get_agent_skill


def test_stdio_server_negotiates_and_executes_a_tool() -> None:
    async def smoke() -> None:
        expected_skill = get_agent_skill(cli_command_prefix=(sys.executable, "-m", "monas_lens"))
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
            resources = await session.list_resources()
            skill = await session.read_resource(AGENT_SKILL_RESOURCE_URI)
            result = await session.call_tool(
                "compress_command_output",
                {
                    "output": "progress\nFAILED example\nsummary",
                    "command_kind": "test",
                },
            )

        assert initialized.serverInfo.name == "Monas Lens"
        assert initialized.instructions == expected_skill.instructions
        assert [tool.name for tool in tools.tools] == [
            "resolve_task_context",
            "expand_context",
            "analyze_patch_impact",
            "compress_command_output",
        ]
        assert [str(resource.uri) for resource in resources.resources] == [AGENT_SKILL_RESOURCE_URI]
        assert skill.contents[0].text == expected_skill.instructions
        assert not result.isError
        assert result.structuredContent is not None
        assert result.structuredContent["command_kind"] == "test"
        assert "FAILED example" in result.structuredContent["content"]

    asyncio.run(smoke())
