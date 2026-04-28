"""Dashboard observability endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_services
from ..schemas import DashboardResponse
from ..services import AppServices

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
def get_dashboard(services: AppServices = Depends(get_services)) -> DashboardResponse:
    """Return skill health and lightweight recommendation metrics."""
    return DashboardResponse(**services.dashboard_snapshot())
