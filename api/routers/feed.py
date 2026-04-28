"""Feed endpoints."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends

from ..deps import get_services
from ..schemas import FeedActionRequest, FeedActionResponse, FeedResponse
from ..services import AppServices

router = APIRouter(prefix="/api/feed", tags=["feed"])

SOURCE_TYPE_BY_ICON = {
    "📚": "academic",
    "馃摎": "academic",
    "ð": "academic",
    "🏭": "industry",
    "馃彮": "industry",
    "馃彚": "industry",
    "ð­": "industry",
    "💬": "community",
    "馃挰": "community",
    "ð¬": "community",
}

NOVELTY_TYPE_BY_LABEL = {
    "🆕": "new",
    "ð": "new",
    "馃啎": "new",
    "🔁": "update",
    "ð": "update",
    "馃攣": "update",
    "🔭": "watch",
    "ð­": "watch",
    "馃搶": "watch",
    "✂️": "watch",
}


@router.get("", response_model=FeedResponse)
def get_feed(services: AppServices = Depends(get_services)) -> FeedResponse:
    """Return today's precision and exploration feed."""
    payload = services.build_feed()
    feed = payload["feed"]
    return FeedResponse(
        feed_date=feed.feed_date,
        precision_pool=[_serialize_feed_item(item) for item in feed.precision_pool],
        exploration_pool=[_serialize_feed_item(item) for item in feed.exploration_pool],
        filter_bubble_warning=payload["filter_bubble_warning"],
        diagnostics=payload["diagnostics"],
    )


@router.post("/{item_id}/action", response_model=FeedActionResponse)
def record_feed_action(
    item_id: str,
    request: FeedActionRequest,
    services: AppServices = Depends(get_services),
) -> FeedActionResponse:
    """Persist one feed interaction event."""
    services.record_action(
        item_id=item_id,
        action=request.action,
        item_title=request.item_title,
        one_liner=request.one_liner,
        pool_type=request.pool_type,
        novelty_label=request.novelty_label,
        source_type=request.source_type,
        chat_turns=request.chat_turns,
    )
    return FeedActionResponse(ok=True, item_id=item_id, action=request.action)


def _serialize_feed_item(item: object) -> dict:
    """Expose stable enums so the frontend does not infer from emoji or mojibake."""
    payload = asdict(item)
    payload["source_type"] = SOURCE_TYPE_BY_ICON.get(payload.get("source_layer_icon"), "community")
    novelty_type = NOVELTY_TYPE_BY_LABEL.get(payload.get("novelty_label"))
    if novelty_type is None:
        novelty_type = _classify_novelty(payload)
    payload["novelty_type"] = novelty_type
    return payload


def _classify_novelty(payload: dict) -> str:
    """Classify novelty from score plus simple launch/recency cues."""
    score = float(payload.get("final_score") or 0.0)
    text = f"{payload.get('title', '')} {payload.get('one_liner', '')}".lower()
    if any(token in text for token in ("beta", "launch", "release", "introducing", "new", "open source")):
        if score >= 0.62:
            return "new"
        if score >= 0.5:
            return "watch"
    if any(token in text for token in ("benchmark", "token", "workflow", "feedback", "research")):
        if score >= 0.55:
            return "watch"
    if score >= 0.7:
        return "new"
    if score >= 0.52:
        return "watch"
    return "update"
