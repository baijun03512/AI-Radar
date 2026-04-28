"""Inter-Agent data contracts. See PRD section 16."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

SourceLayer = Literal["学术层", "工业层", "社区层"]
NoveltyLabel = Literal["🆕", "🔁", "📌", "❓"]
PoolType = Literal["precision", "exploration"]


@dataclass
class CrawledItem:
    """Crawler -> Novelty Scorer."""

    item_id: str
    title: str
    summary: str
    source_platform: str
    source_layer: SourceLayer
    source_url: str
    published_at: str
    fetched_at: str
    raw_content: Optional[str] = None
    # Pool inherited from the crawl task (precision = preference-based,
    # exploration = broad sweep). Defaults to precision; the Crawler sets it.
    pool: PoolType = "precision"


@dataclass
class ScoredItem:
    """Novelty Scorer -> Recommender."""

    item_id: str
    title: str
    summary: str
    source_platform: str
    source_layer: SourceLayer
    source_url: str
    novelty_score: float
    novelty_label: NoveltyLabel
    novelty_reason: str
    is_verified: bool
    pool: PoolType


@dataclass
class FeedItem:
    """Recommender -> Frontend API."""

    item_id: str
    title: str
    one_liner: str
    novelty_label: NoveltyLabel
    source_layer_icon: str
    final_score: float
    pool_type: PoolType


@dataclass
class Feed:
    """Daily recommendation feed split into precision and exploration pools."""

    feed_date: str
    precision_pool: list[FeedItem] = field(default_factory=list)
    exploration_pool: list[FeedItem] = field(default_factory=list)


@dataclass
class ChatTurn:
    """One chat message passed from Chat Agent to Memory Agent."""

    role: Literal["user", "assistant"]
    content: str


@dataclass
class SourceUsed:
    """One cited source used during a chat answer."""

    layer: SourceLayer
    url: str
    snippet: str


@dataclass
class ChatToMemoryPayload:
    """Chat Agent -> Memory Agent."""

    product_id: str
    product_name: str
    conversation: list[ChatTurn]
    intent_type: Literal["exploratory", "deep_dive", "comparison"]
    sources_used: list[SourceUsed]
    new_insights: str
    ended_at: str
    end_reason: Literal["user_close", "timeout", "manual_save"]


@dataclass
class WikiPage:
    """Memory Agent -> Notion."""

    name: str
    one_liner: str
    tags: list[str]
    source_layer: SourceLayer
    tech_principle: str = ""
    product_impl: str = ""
    user_feedback: str = ""
    novelty_score: float = 0.0
    recall_count: int = 0
    weight: float = 1.0
    related_pages: list[str] = field(default_factory=list)
    chat_notes: str = ""
    quality_score: float = 0.0
    created_at: str = ""
    last_updated: str = ""
