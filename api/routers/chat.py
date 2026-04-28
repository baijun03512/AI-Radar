"""SSE chat endpoint."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..deps import get_services
from ..schemas import ChatRequest
from ..services import AppServices

router = APIRouter(prefix="/api/chat", tags=["chat"])

SOURCE_TYPE_BY_LAYER = {
    "academic": "academic",
    "industry": "industry",
    "community": "community",
    "学术层": "academic",
    "工业层": "industry",
    "社区层": "community",
}


def _sse(event: str, data: dict) -> str:
    """Render one server-sent event frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("")
def stream_chat(
    request: ChatRequest,
    services: AppServices = Depends(get_services),
) -> StreamingResponse:
    """Stream a grounded chat answer in SSE format."""
    def event_stream() -> str:
        try:
            payload = services.answer_chat(
                query=request.query,
                product_id=request.product_id,
                product_name=request.product_name,
                product_context=request.product_context,
                max_per_tool=request.max_per_tool,
                persist_memory=request.persist_memory,
                write_notion=request.write_notion,
            )
            result = payload["result"]
            memory_result = payload["memory_result"]

            yield _sse(
                "meta",
                {
                    "intent_type": result.intent_type,
                    "sources_used": [
                        {
                            **source.__dict__,
                            "source_type": SOURCE_TYPE_BY_LAYER.get(source.layer, "community"),
                        }
                        for source in result.sources_used
                    ],
                    "new_insights": result.new_insights,
                    "memory_persisted": memory_result is not None,
                    "quality_score": None if memory_result is None else memory_result.quality_score,
                },
            )
            for chunk in _chunk_text(result.answer, size=120):
                yield _sse("message", {"delta": chunk})
            yield _sse("done", {"ok": True})
        except Exception as exc:
            yield _sse("error", {"detail": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _chunk_text(text: str, size: int = 120) -> list[str]:
    """Split long assistant text into stable stream chunks."""
    return [text[index:index + size] for index in range(0, len(text), size)] or [""]
