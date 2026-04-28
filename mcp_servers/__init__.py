"""MCP tool servers.

Each module exposes `register(registry: ToolRegistry)` to add its tools.
`build_default_registry()` wires up everything that has working creds.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from ..runtime.tool_registry import ToolRegistry

log = logging.getLogger(__name__)


def build_default_registry(env: Optional[dict] = None) -> ToolRegistry:
    """Build a registry with every tool whose required env vars are present.

    Tools with missing creds are skipped with a log warning instead of raising,
    so partial-credentials development still works.
    """
    e = env if env is not None else os.environ
    registry = ToolRegistry()

    # arXiv: no creds needed.
    from . import arxiv_server
    arxiv_server.register(registry)

    # Reddit (YARS): no creds needed.
    from . import reddit_server
    reddit_server.register(registry)

    # fetch_page: no creds needed.
    from . import fetch_page_server
    fetch_page_server.register(registry)

    # ProductHunt: needs API key.
    if e.get("PRODUCTHUNT_API_KEY"):
        from . import producthunt_server
        producthunt_server.register(registry)
    else:
        log.warning("PRODUCTHUNT_API_KEY missing; skipping search_product_hunt")

    # Notion: needs API key + at least one DB id.
    if e.get("NOTION_API_KEY") and e.get("NOTION_WIKI_DATABASE_ID"):
        from . import notion_server
        notion_server.register(registry)
    else:
        log.warning("NOTION_API_KEY/NOTION_WIKI_DATABASE_ID missing; skipping Notion tools")

    return registry
