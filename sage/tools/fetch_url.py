"""
SAGE URL Fetcher — fetches and extracts text from web pages.

Uses httpx for async HTTP and BeautifulSoup for HTML parsing.
Strips boilerplate to return clean, readable text content.
"""

from __future__ import annotations

import asyncio


async def fetch_url(url: str, max_length: int = 5000) -> dict:
    """
    Fetch a URL and extract its main text content.

    Args:
        url: The URL to fetch
        max_length: Maximum character length of returned content (default 5000)

    Returns:
        Standard result dict with page text in content.
    """
    try:
        import httpx
        from bs4 import BeautifulSoup

        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; SAGEBot/1.0; "
                    "+https://github.com/ShamsRupak/sage-research-agent)"
                )
            },
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Remove script, style, nav, footer elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # Extract text
        text = soup.get_text(separator="\n", strip=True)

        # Clean up whitespace
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean_text = "\n".join(lines)

        # Truncate if too long
        if len(clean_text) > max_length:
            clean_text = clean_text[:max_length] + "\n\n[... truncated]"

        return {
            "success": True,
            "content": clean_text,
            "metadata": {
                "url": url,
                "status_code": response.status_code,
                "content_length": len(clean_text),
            },
        }

    except Exception as e:
        return {
            "success": False,
            "content": f"Failed to fetch URL: {str(e)}",
            "metadata": {"url": url, "error": str(e)},
        }