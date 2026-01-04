"""
Web search tool.

Search the web using DuckDuckGo.
"""

import json
import logging

from ddgs import DDGS

from ..base import tool

logger = logging.getLogger("qwen.browser")


@tool(
    name="web_search",
    description="Search the web using DuckDuckGo. Use this to find online code playgrounds for unfamiliar languages.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query, e.g. 'Haskell online playground'",
            },
        },
        "required": ["query"],
    },
)
async def web_search(query: str) -> str:
    """Search the web using DuckDuckGo."""
    logger.info(f"[TOOL] web_search: {query}")
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))

        if not results:
            logger.info("[TOOL] web_search: no results")
            return json.dumps({"status": "no_results", "query": query})

        formatted = [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", "")[:200],
            }
            for r in results
        ]
        logger.info(f"[TOOL] web_search: found {len(formatted)} results")
        return json.dumps({"status": "success", "results": formatted})
    except Exception as e:
        logger.error(f"[TOOL] web_search ERROR: {e}")
        return json.dumps({"status": "error", "message": str(e)})


TOOL = web_search
