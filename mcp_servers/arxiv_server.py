"""arXiv search tool. Uses arXiv's public Atom feed; no credentials required."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
import httpx

from ..runtime.tool_registry import Tool, ToolRegistry

ARXIV_ENDPOINT = "https://export.arxiv.org/api/query"
DEFAULT_TIMEOUT = 30.0


def _isoformat(struct_time: Any) -> str:
    """Convert feedparser struct_time values to ISO8601 strings."""
    if struct_time is None:
        return ""
    try:
        dt = datetime(*struct_time[:6], tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return ""


def search_arxiv(
    query: str,
    max_results: int = 10,
    days: int = 90,
    categories: list[str] | None = None,
) -> str:
    """Search arXiv for papers matching `query` published within `days`."""
    cats = categories or ["cs.AI", "cs.LG", "cs.CL", "cs.CV"]
    cat_filter = " OR ".join(f"cat:{category}" for category in cats)
    search_query = f"({cat_filter}) AND all:{query}"
    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max_results * 2,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }

    resp = httpx.get(ARXIV_ENDPOINT, params=params, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    feed = feedparser.parse(resp.text)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    fetched_at = datetime.now(timezone.utc).isoformat()
    items: list[dict[str, Any]] = []
    for entry in feed.entries:
        published_iso = _isoformat(getattr(entry, "published_parsed", None))
        if published_iso:
            try:
                if datetime.fromisoformat(published_iso) < cutoff:
                    continue
            except ValueError:
                pass
        items.append(
            {
                "item_id": entry.get("id", "").rsplit("/", 1)[-1] or entry.get("id", ""),
                "title": (entry.get("title", "") or "").strip().replace("\n", " "),
                "summary": (entry.get("summary", "") or "").strip()[:500],
                "source_platform": "arxiv",
                "source_layer": "学术层",
                "source_url": entry.get("link", ""),
                "published_at": published_iso,
                "fetched_at": fetched_at,
                "authors": [author.get("name", "") for author in entry.get("authors", [])],
            }
        )
        if len(items) >= max_results:
            break

    return json.dumps(items, ensure_ascii=False)


_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search keywords in English."},
        "max_results": {
            "type": "integer",
            "description": "Maximum papers to return.",
            "default": 10,
        },
        "days": {
            "type": "integer",
            "description": "Restrict to papers from the last N days.",
            "default": 90,
        },
        "categories": {
            "type": "array",
            "items": {"type": "string"},
            "description": "arXiv category codes.",
        },
    },
    "required": ["query"],
}


def register(registry: ToolRegistry) -> None:
    """Register the arXiv search tool."""
    registry.register(
        Tool(
            name="search_arxiv",
            description=(
                "Search arXiv for recent AI papers. Returns JSON array of "
                "CrawlerItem-like objects from the academic layer."
            ),
            input_schema=_INPUT_SCHEMA,
            handler=search_arxiv,
        )
    )
