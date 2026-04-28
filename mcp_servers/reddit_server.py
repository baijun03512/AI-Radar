"""Reddit search tool using the vendored YARS scraper."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..runtime.tool_registry import Tool, ToolRegistry
from ._vendor.yars.yars import YARS


def _created_iso(value: Any) -> str:
    """Convert a Reddit created_utc value into ISO8601 if present."""
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return ""


def _normalize_post(post: dict[str, Any], subreddit: str, fetched_at: str) -> dict[str, Any]:
    """Convert YARS post data to the CrawledItem-like contract."""
    permalink = post.get("permalink") or post.get("link") or ""
    url = permalink if str(permalink).startswith("http") else f"https://www.reddit.com{permalink}"
    summary = post.get("description") or post.get("selftext") or post.get("body") or ""
    return {
        "item_id": str(post.get("id") or permalink or post.get("title", "")),
        "title": (post.get("title") or "").strip(),
        "summary": str(summary).strip()[:500],
        "source_platform": "reddit",
        "source_layer": "社区层",
        "source_url": url,
        "published_at": _created_iso(post.get("created_utc")),
        "fetched_at": fetched_at,
        "subreddit": post.get("subreddit") or subreddit,
        "score": post.get("score", 0),
        "num_comments": post.get("num_comments", 0),
    }


def search_reddit(
    query: str = "AI",
    subreddit: str = "MachineLearning",
    max_results: int = 10,
    sort: str = "hot",
) -> str:
    """Search Reddit or fetch subreddit posts with YARS and return JSON."""
    client = YARS(timeout=30)
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        if query:
            raw_posts = client.search_subreddit(subreddit, query, limit=max_results)
        else:
            category = sort if sort in {"hot", "top", "new"} else "hot"
            raw_posts = client.fetch_subreddit_posts(
                subreddit, limit=max_results, category=category, time_filter="week"
            )
    except Exception as exc:
        raise RuntimeError(f"Reddit fetch failed: {exc}") from exc
    items = [_normalize_post(post, subreddit, fetched_at) for post in raw_posts]
    return json.dumps(items[:max_results], ensure_ascii=False)


_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Keyword query. Empty string fetches subreddit listing.",
            "default": "AI",
        },
        "subreddit": {
            "type": "string",
            "description": "Subreddit without r/ prefix.",
            "default": "MachineLearning",
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum posts to return.",
            "default": 10,
        },
        "sort": {
            "type": "string",
            "description": "hot/top/new when query is empty.",
            "default": "hot",
        },
    },
}


def register(registry: ToolRegistry) -> None:
    """Register the Reddit tool."""
    registry.register(
        Tool(
            name="search_reddit",
            description="Search Reddit via YARS and return community-layer CrawledItem objects.",
            input_schema=_INPUT_SCHEMA,
            handler=search_reddit,
        )
    )
