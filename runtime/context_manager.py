"""Context manager: assembles OpenAI-format messages, tracks token budget,
compresses on overflow.

OpenAI message shapes used here:
  user:      {"role": "user", "content": str}
  assistant: {"role": "assistant", "content": str|None, "tool_calls": [...]}
  tool:      {"role": "tool", "tool_call_id": "...", "content": str}

Token estimation is approximate (1 token ~= 4 chars ASCII, ~= 1.5 chars CJK)
- precise enough for budget-pressure decisions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


def estimate_tokens(text: Any) -> int:
    """Rough heuristic blending ASCII and CJK character widths."""
    if not isinstance(text, str):
        try:
            text = json.dumps(text, ensure_ascii=False, default=str)
        except Exception:
            text = str(text)
    if not text:
        return 0
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    other = len(text) - cjk
    return max(1, int(cjk / 1.5 + other / 4))


def _msg_token_estimate(m: dict) -> int:
    n = estimate_tokens(m.get("content"))
    for tc in m.get("tool_calls") or []:
        n += estimate_tokens(tc.get("function", {}).get("arguments", ""))
        n += estimate_tokens(tc.get("function", {}).get("name", ""))
    return n


@dataclass
class ContextManager:
    """Holds the running OpenAI-format message list for a single Agent run."""

    token_budget: int = 8000
    messages: list[dict] = field(default_factory=list)

    def add_user(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant(
        self,
        text: str,
        tool_calls: list[dict] | None = None,
        reasoning_content: str = "",
    ) -> None:
        """Assistant turn: text and/or OpenAI-format tool_calls.

        `reasoning_content` is required by DeepSeek reasoning models on
        subsequent turns; harmless on providers that ignore it.
        """
        msg: dict[str, Any] = {"role": "assistant", "content": text or None}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if reasoning_content:
            msg["reasoning_content"] = reasoning_content
        self.messages.append(msg)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self.messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "content": content}
        )

    def total_tokens(self) -> int:
        return sum(_msg_token_estimate(m) for m in self.messages)

    def compress_if_needed(self, keep_recent: int = 6) -> bool:
        """Compress oldest messages to a summary placeholder when over budget.

        Keeps the first user prompt and the most recent `keep_recent` messages
        intact. Returns True if compression occurred.
        """
        if self.total_tokens() <= self.token_budget:
            return False
        if len(self.messages) <= keep_recent + 1:
            return False

        head = self.messages[0]
        tail = self.messages[-keep_recent:]
        dropped = self.messages[1:-keep_recent]
        if not dropped:
            return False

        summary_chars = 0
        for m in dropped:
            c = m.get("content")
            summary_chars += len(c) if isinstance(c, str) else len(json.dumps(c, default=str))
        summary = (
            f"[compressed earlier context: {len(dropped)} messages, "
            f"~{summary_chars} chars]"
        )
        self.messages = [head, {"role": "user", "content": summary}, *tail]
        return True
