"""Wiki search endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import get_services
from ..schemas import WikiSearchResponse
from ..services import AppServices

router = APIRouter(prefix="/api/wiki", tags=["wiki"])


@router.get("", response_model=WikiSearchResponse)
def search_wiki(
    query: str = Query(default="", description="Search term"),
    limit: int = Query(default=10, ge=1, le=50),
    services: AppServices = Depends(get_services),
) -> WikiSearchResponse:
    """Search the local warmed wiki cache."""
    return WikiSearchResponse(items=services.search_wiki(query=query, limit=limit))
