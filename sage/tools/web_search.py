"""
SAGE Web Search Tool — searches the web via Tavily API.

Tavily is purpose-built for LLM agents: it returns clean snippets
rather than raw HTML, making results directly usable by the agent.
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


async def web_search(query: str, max_results: int = 5) -> dict:
    """
    Search the web for a query and return ranked snippets.

    Args:
        query: Search query string
        max_results: Maximum number of results to return (default 5)

    Returns:
        Standard result dict with search snippets in content.
    """
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        return {
            "success": False,
            "content": "TAVILY_API_KEY not set in environment",
            "metadata": {},
        }

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)

        response = client.search(
            query=query,
            max_results=max_results,
            search_depth="basic",
        )

        results = response.get("results", [])
        if not results:
            return {
                "success": True,
                "content": "No results found for this query.",
                "metadata": {"query": query, "num_results": 0},
            }

        # Format results as readable text
        formatted = []
        urls = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "No title")
            url = r.get("url", "")
            snippet = r.get("content", "No snippet available")
            formatted.append(f"[{i}] {title}\n    URL: {url}\n    {snippet}")
            urls.append(url)

        content = "\n\n".join(formatted)

        return {
            "success": True,
            "content": content,
            "metadata": {
                "query": query,
                "num_results": len(results),
                "urls": urls,
            },
        }

    except Exception as e:
        return {
            "success": False,
            "content": f"Web search failed: {str(e)}",
            "metadata": {"query": query, "error": str(e)},
        }