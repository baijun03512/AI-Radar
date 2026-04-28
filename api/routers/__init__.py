"""API routers."""

from .chat import router as chat_router
from .dashboard import router as dashboard_router
from .feed import router as feed_router
from .preferences import router as preferences_router
from .wiki import router as wiki_router

__all__ = [
    "chat_router",
    "dashboard_router",
    "feed_router",
    "preferences_router",
    "wiki_router",
]
