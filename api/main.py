"""FastAPI entrypoint for the AI Radar backend."""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

from ..mcp_servers import build_default_registry
from .routers import (
    chat_router,
    dashboard_router,
    feed_router,
    preferences_router,
    wiki_router,
)
from .services import AppServices

_DEFAULT_SERVICES: AppServices | None = None
_DOTENV_LOADED = False


def _load_project_dotenv() -> None:
    """Load the repo .env once so API workers can see LLM / MCP credentials."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    env_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(env_path, override=False)
    _DOTENV_LOADED = True


def _get_default_services() -> AppServices:
    """Lazy singleton: build only on first request so dotenv loads first."""
    global _DEFAULT_SERVICES
    if _DEFAULT_SERVICES is None:
        _load_project_dotenv()
        _DEFAULT_SERVICES = AppServices(registry=build_default_registry())
    return _DEFAULT_SERVICES


def create_app(*, services: AppServices | None = None) -> FastAPI:
    """Create a configured FastAPI app."""
    app = FastAPI(
        title="AI Product Radar API",
        version="0.1.0",
        description="FastAPI layer for feed, chat, preferences, dashboard, and wiki access.",
    )
    container = services or _get_default_services()
    app.state.services = container

    @app.get("/healthz", tags=["system"])
    def healthcheck() -> dict[str, str]:
        """Simple health endpoint for local checks."""
        return {"status": "ok"}

    app.include_router(feed_router)
    app.include_router(chat_router)
    app.include_router(preferences_router)
    app.include_router(dashboard_router)
    app.include_router(wiki_router)
    return app


app = create_app()
