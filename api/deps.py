"""FastAPI dependencies for shared services."""
from __future__ import annotations

from fastapi import Request

from .services import AppServices


def get_services(request: Request) -> AppServices:
    """Resolve the current application service container from app state."""
    return request.app.state.services
