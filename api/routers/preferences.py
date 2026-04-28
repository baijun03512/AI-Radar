"""Preferences endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_services
from ..schemas import PreferencesResponse, PreferencesUpdateRequest
from ..services import AppServices

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


@router.get("", response_model=PreferencesResponse)
def get_preferences(services: AppServices = Depends(get_services)) -> PreferencesResponse:
    """Return the current preference profile."""
    return PreferencesResponse(**services.load_preferences())


@router.post("", response_model=PreferencesResponse)
def update_preferences(
    request: PreferencesUpdateRequest,
    services: AppServices = Depends(get_services),
) -> PreferencesResponse:
    """Persist a partial preference update."""
    updated = services.save_preferences(request.model_dump())
    return PreferencesResponse(**updated)
