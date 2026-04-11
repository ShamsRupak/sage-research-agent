"""Tests for tool registry and tools that don't require API keys."""

import asyncio
import pytest
from sage.tools.registry import ToolRegistry
from sage.tools.code_runner import code_run


def run_async(coro):
    """Helper to run async functions in sync tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ─── Registry Tests ──────────────────────────────────────────

class TestToolRegistry:

    def test_register_and_list(self):
        registry = ToolRegistry()

        async def dummy_tool(query: str) -> dict:
            return {"success": True, "content": query, "metadata": {}}

        registry.register(
            name="test_tool",
            description="A test tool",
            parameters="query: str",
            func=dummy_tool,
        )
        assert "test_tool" in registry.list_tools()

    def test_get_tool(self):
        registry = ToolRegistry()

        async def dummy(query: str) -> dict:
            return {"success": True, "content": "", "metadata": {}}

        registry.register("t1", "desc", "query: str", dummy)
        tool = registry.get("t1")
        assert tool is not None
        assert tool.name == "t1"

    def test_get_missing_tool(self):
        registry = ToolRegistry()
        assert registry.get("nonexistent") is None

    def test_dispatch_success(self):
        registry = ToolRegistry()

        async def echo(query: str) -> dict:
            return {"success": True, "content": f"echo: {query}", "metadata": {}}

        registry.register("echo", "Echoes input", "query: str", echo)
        result = run_async(registry.dispatch("echo", {"query": "hello"}))
        assert result["success"]
        assert result["content"] == "echo: hello"

    def test_dispatch_unknown_tool(self):
        registry = ToolRegistry()
        result = run_async(registry.dispatch("nope", {}))
        assert not result["success"]
        assert "Unknown tool" in result["content"]

    def test_dispatch_catches_exceptions(self):
        registry = ToolRegistry()

        async def broken(**kwargs) -> dict:
            raise ValueError("Something broke")

        registry.register("broken", "Breaks", "none", broken)
        result = run_async(registry.dispatch("broken", {}))
        assert not result["success"]
        assert "failed" in result["content"]

    def test_get_descriptions(self):
        registry = ToolRegistry()

        async def dummy(query: str) -> dict:
            return {"success": True, "content": "", "metadata": {}}

        registry.register("search", "Search the web", "query: str", dummy)
        registry.register("fetch", "Fetch a URL", "url: str", dummy)
        desc = registry.get_descriptions()
        assert "search" in desc
        assert "fetch" in desc


# ─── Code Runner Tests ───────────────────────────────────────

class TestCodeRunner:

    def test_simple_print(self):
        result = run_async(code_run("print('hello world')"))
        assert result["success"]
        assert "hello world" in result["content"]

    def test_math_computation(self):
        result = run_async(code_run("print(2 + 2)"))
        assert result["success"]
        assert "4" in result["content"]

    def test_syntax_error(self):
        result = run_async(code_run("def broken("))
        assert not result["success"]
        assert "error" in result["content"].lower() or "Error" in result["content"]

    def test_empty_snippet(self):
        result = run_async(code_run(""))
        assert not result["success"]

    def test_timeout(self):
        result = run_async(code_run("import time; time.sleep(30)", timeout=2))
        assert not result["success"]
        assert "timed out" in result["content"].lower()

    def test_multiline_code(self):
        code = """
data = [1, 2, 3, 4, 5]
total = sum(data)
avg = total / len(data)
print(f"Average: {avg}")
"""
        result = run_async(code_run(code))
        assert result["success"]
        assert "3.0" in result["content"]