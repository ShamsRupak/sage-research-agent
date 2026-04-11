"""
SAGE Tool Registry — registration, description, and dispatch.

Every tool is registered here with its name, description, and callable.
The registry generates tool descriptions for LLM prompts and dispatches
tool calls by name. All tools return a standard result dict:
  {"success": bool, "content": str, "metadata": dict}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable


@dataclass
class ToolSpec:
    """Specification for a registered tool."""
    name: str
    description: str
    parameters: str  # Human-readable parameter description
    func: Callable[..., Awaitable[dict[str, Any]]]


class ToolRegistry:
    """
    Central registry for all agent tools.
    Tools register themselves; the agent dispatches calls through here.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: str,
        func: Callable[..., Awaitable[dict[str, Any]]],
    ) -> None:
        """Register a tool by name."""
        self._tools[name] = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            func=func,
        )

    def get(self, name: str) -> ToolSpec | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._tools.keys())

    def get_descriptions(self) -> str:
        """
        Generate a formatted string of all tool descriptions.
        This is injected into the ReAct prompt so the LLM knows what's available.
        """
        lines = []
        for tool in self._tools.values():
            lines.append(
                f"- {tool.name}: {tool.description}\n"
                f"  Parameters: {tool.parameters}"
            )
        return "\n".join(lines)

    async def dispatch(
        self, name: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Execute a tool by name with the given inputs.
        Returns the standard result dict.
        Catches exceptions and returns a failure result.
        """
        tool = self._tools.get(name)
        if tool is None:
            return {
                "success": False,
                "content": f"Unknown tool: '{name}'. Available: {self.list_tools()}",
                "metadata": {},
            }

        try:
            result = await tool.func(**inputs)
            return result
        except Exception as e:
            return {
                "success": False,
                "content": f"Tool '{name}' failed: {str(e)}",
                "metadata": {"error_type": type(e).__name__},
            }