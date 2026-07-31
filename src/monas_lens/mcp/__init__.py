"""Community MCP transport and tool services."""

from typing import TYPE_CHECKING

from monas_lens.mcp.compression import compress_command_output
from monas_lens.mcp.contracts import (
    CommandKind,
    CommandOutputSummary,
    ContextExpansion,
    ImpactNode,
    ImpactRisk,
    ImpactSymbol,
    PatchImpact,
)
from monas_lens.mcp.impact import PatchImpactAnalyzer

if TYPE_CHECKING:
    from monas_lens.community import CommunityTools

__all__ = [
    "CommandKind",
    "CommandOutputSummary",
    "CommunityTools",
    "ContextExpansion",
    "ImpactNode",
    "ImpactRisk",
    "ImpactSymbol",
    "PatchImpact",
    "PatchImpactAnalyzer",
    "compress_command_output",
]


def __getattr__(name: str) -> object:
    if name == "CommunityTools":
        from monas_lens.community import CommunityTools

        return CommunityTools
    raise AttributeError(name)
