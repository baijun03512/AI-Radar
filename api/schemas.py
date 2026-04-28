"""Pydantic request and response models for the API layer."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class FeedItemResponse(BaseModel):
    """One feed item returned to the frontend."""

    item_id: str
    title: str
    one_liner: str
    novelty_label: str
    novelty_type: Literal["new", "update", "watch"] | None = None
    source_layer_icon: str
    source_type: Literal["academic", "industry", "community"] | None = None
    final_score: float
    pool_type: Literal["precision", "exploration"]


class FeedResponse(BaseModel):
    """Daily feed API response."""

    feed_date: str
    precision_pool: list[FeedItemResponse]
    exploration_pool: list[FeedItemResponse]
    filter_bubble_warning: bool = False
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class FeedActionRequest(BaseModel):
    """Record one user action against a feed item."""

    action: Literal["open", "skip", "save", "skip_future"]
    item_title: str = ""
    one_liner: str = ""
    pool_type: Literal["precision", "exploration"] | None = None
    novelty_label: str | None = None
    source_type: Literal["academic", "industry", "community"] | None = None
    chat_turns: int = 0


class FeedActionResponse(BaseModel):
    """Outcome of recording a user action."""

    ok: bool
    item_id: str
    action: str
    notion_synced: bool | None = None
    message: str = ""


class PreferencesResponse(BaseModel):
    """User preference profile used by the orchestrator and recommender."""

    interests: list[str] = Field(default_factory=list)
    preferred_platforms: list[str] = Field(default_factory=list)
    exploration_ratio: float = 0.3
    feed_size: int = 10
    exploration_queries: list[str] = Field(default_factory=list)
    boosted_topics: list[str] = Field(default_factory=list)
    suppressed_topics: list[str] = Field(default_factory=list)


class PreferencesUpdateRequest(BaseModel):
    """Partial preferences update."""

    interests: list[str] | None = None
    preferred_platforms: list[str] | None = None
    exploration_ratio: float | None = None
    feed_size: int | None = None
    exploration_queries: list[str] | None = None
    boosted_topics: list[str] | None = None
    suppressed_topics: list[str] | None = None


class ChatRequest(BaseModel):
    """Input payload for the chat endpoint."""

    query: str
    product_id: str = "general"
    product_name: str = "General"
    product_context: str = ""
    max_per_tool: int = 2
    persist_memory: bool = True
    write_notion: bool = False


class DashboardSkillHealth(BaseModel):
    """Health snapshot for one persisted skill."""

    skill_id: str
    skill_type: str
    success_rate: float
    usage_count: int
    version: int
    heal_required: bool


class DashboardResponse(BaseModel):
    """Observability response for the dashboard."""

    skill_health: list[DashboardSkillHealth]
    feed_metrics: dict[str, Any]
    execution: dict[str, Any]


class WikiItemResponse(BaseModel):
    """One wiki search result returned by the API."""

    name: str
    tags: list[str] = Field(default_factory=list)
    one_liner: str = ""
    weight: float = 1.0
    recall_count: int = 0


class WikiSearchResponse(BaseModel):
    """Local wiki search results."""

    items: list[WikiItemResponse]
