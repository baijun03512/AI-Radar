"""LLM thin wrapper (OpenAI-compatible).

Uses the OpenAI Python SDK with a configurable base_url so we can swap
providers (DeepSeek now, Anthropic's OpenAI-compat endpoint later, etc.)
without touching agent code.

OpenAI tool-calling format:
- request:  tools=[{"type":"function","function":{"name","description","parameters"}}]
- response: choices[0].message.tool_calls = [{id, type:"function", function:{name, arguments(json str)}}]
- stop:     choices[0].finish_reason in {"stop","tool_calls","length","content_filter"}
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

try:
    from openai import OpenAI
except ImportError:  # tests can run without the SDK installed
    OpenAI = None  # type: ignore


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    stop_reason: str          # "end_turn" | "tool_use" | "max_tokens" | "content_filter"
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None
    usage_input_tokens: int = 0
    usage_output_tokens: int = 0
    # DeepSeek reasoning models require this be echoed back in subsequent turns.
    reasoning_content: str = ""


# Map OpenAI's finish_reason to our internal vocabulary so the agent loop
# stays provider-agnostic.
_FINISH_MAP = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "content_filter",
    None: "end_turn",
}


class LLMClient:
    """OpenAI-compatible chat client with retry + a stub mode for tests."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        stub: Optional[Callable[[list[dict], list[dict] | None, str | None], LLMResponse]] = None,
    ) -> None:
        self.model = model or os.getenv("LLM_MODEL", "deepseek-v4-flash")
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
        self.timeout = timeout
        self.max_retries = max_retries
        self._stub = stub

        if stub is None:
            key = api_key or os.getenv("LLM_API_KEY")
            if not key:
                raise RuntimeError("LLM_API_KEY is not set")
            if OpenAI is None:
                raise RuntimeError("openai SDK not installed")
            self._client = OpenAI(api_key=key, base_url=self.base_url, timeout=timeout)
        else:
            self._client = None

    def call(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Send messages + optional tools. Returns provider-neutral LLMResponse.

        `messages` are already in OpenAI format. `system`, if provided, is
        prepended as a system message. Network errors trigger exponential
        backoff up to `max_retries`.
        """
        if self._stub is not None:
            return self._stub(messages, tools, system)

        full_messages = (
            [{"role": "system", "content": system}] + messages if system else messages
        )

        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": full_messages,
                    "max_tokens": max_tokens,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"

                resp = self._client.chat.completions.create(**kwargs)  # type: ignore[union-attr]
                return self._parse(resp)
            except Exception as e:
                last_err = e
                if attempt == self.max_retries - 1:
                    break
                time.sleep(2 ** attempt)
        raise RuntimeError(f"LLM API failed after {self.max_retries} attempts: {last_err}")

    @staticmethod
    def _parse(resp: Any) -> LLMResponse:
        choice = resp.choices[0]
        msg = choice.message

        text = msg.content or ""
        reasoning_content = getattr(msg, "reasoning_content", "") or ""
        tool_calls: list[ToolCall] = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, input=args))

        stop_reason = _FINISH_MAP.get(choice.finish_reason, choice.finish_reason or "end_turn")
        usage = getattr(resp, "usage", None)
        return LLMResponse(
            stop_reason=stop_reason,
            text=text,
            tool_calls=tool_calls,
            raw=resp,
            usage_input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            usage_output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            reasoning_content=reasoning_content,
        )
