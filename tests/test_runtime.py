"""Phase-1 smoke tests for Mini Runtime.

Uses a stub LLMClient so tests don't need a real API key. The stub scripts
a tiny conversation: think -> tool_call -> observe -> stop.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_radar.data.db import get_db, init_db
from ai_radar.runtime.agent_loop import AgentConfig, run_agent
from ai_radar.runtime.context_manager import ContextManager, estimate_tokens
from ai_radar.runtime.llm_client import LLMClient, LLMResponse, ToolCall
from ai_radar.runtime.observability import Observability
from ai_radar.runtime.permission_gate import (
    AgentPolicy,
    PermissionDenied,
    PermissionGate,
)
from ai_radar.runtime.self_healing import retry_tool_call
from ai_radar.runtime.tool_registry import Tool, ToolRegistry


@pytest.fixture
def tmp_db(monkeypatch, tmp_path: Path) -> Path:
    db = tmp_path / "radar.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(db))
    init_db(db)
    return db


# ----- unit-level checks -----

def test_db_init_creates_tables(tmp_db: Path) -> None:
    conn = get_db(tmp_db)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {r["name"] for r in rows}
    assert {"user_actions", "feed_history", "agent_logs"}.issubset(names)
    conn.close()


def test_permission_gate_blocks_unknown_tool() -> None:
    gate = PermissionGate(AgentPolicy.of("X", ["a"]))
    gate.check("a")
    with pytest.raises(PermissionDenied):
        gate.check("b")


def test_self_healing_retries_until_success() -> None:
    counter = {"n": 0}

    def flaky() -> str:
        counter["n"] += 1
        if counter["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    out = retry_tool_call(flaky, max_attempts=3, base_delay=0, sleep=lambda _: None)
    assert out.success and out.result == "ok" and out.attempts == 3


def test_self_healing_gives_up_after_max() -> None:
    def always_fail() -> str:
        raise RuntimeError("nope")

    out = retry_tool_call(always_fail, max_attempts=2, base_delay=0, sleep=lambda _: None)
    assert not out.success and out.attempts == 2 and "nope" in out.error


def test_context_compression_when_over_budget() -> None:
    cm = ContextManager(token_budget=20)
    cm.add_user("first prompt seed")
    for i in range(8):
        cm.add_user("padding " * 50 + str(i))
    assert cm.total_tokens() > 20
    compressed = cm.compress_if_needed(keep_recent=2)
    assert compressed
    assert any("compressed earlier context" in str(m["content"]) for m in cm.messages)


def test_estimate_tokens_handles_cjk() -> None:
    assert estimate_tokens("hello world") < estimate_tokens("你好世界你好世界")


def test_tool_registry_emits_openai_schema() -> None:
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="ping",
            description="returns pong",
            input_schema={"type": "object", "properties": {}},
            handler=lambda: "pong",
        )
    )
    schemas = reg.schemas()
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "ping"
    assert "parameters" in schemas[0]["function"]


# ----- end-to-end mock-agent loop -----

def _stub_two_step():
    """Scripted: tool_call then plain text."""
    state = {"step": 0}

    def stub(messages, tools, system):
        state["step"] += 1
        if state["step"] == 1:
            return LLMResponse(
                stop_reason="tool_use",
                text="I should call echo to verify the loop.",
                tool_calls=[ToolCall(id="t1", name="echo", input={"text": "hello-runtime"})],
            )
        return LLMResponse(
            stop_reason="end_turn",
            text="Tool returned hello-runtime. Done.",
            tool_calls=[],
        )

    return stub


def test_agent_loop_end_to_end(tmp_db: Path) -> None:
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="echo",
            description="Return the text passed in.",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=lambda text: f"echoed:{text}",
        )
    )

    client = LLMClient(stub=_stub_two_step())
    obs = Observability(db_path=str(tmp_db))

    config = AgentConfig(
        name="mock_agent",
        system_prompt="You are a test agent.",
        policy=AgentPolicy.of("mock_agent", ["echo"]),
        token_budget=2000,
        max_turns=5,
    )

    result = run_agent(
        config,
        initial_user_message="please run the echo tool with text='hello-runtime'",
        client=client,
        tools=registry,
        observability=obs,
    )

    assert result.stopped_reason == "end_turn"
    assert result.turns == 2
    assert "hello-runtime" in result.final_text

    conn = get_db(tmp_db)
    rows = conn.execute(
        "SELECT agent_name, tool_called, tool_success FROM agent_logs ORDER BY id"
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    assert rows[0]["tool_called"] == "echo"
    assert rows[0]["tool_success"] == 1
    assert rows[1]["tool_called"] is None  # end_turn row
    obs.close()


def test_agent_loop_blocks_disallowed_tool(tmp_db: Path) -> None:
    """Permission gate denies unauthorized tool; model receives error and stops."""
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="forbidden",
            description="should never run",
            input_schema={"type": "object", "properties": {}},
            handler=lambda: "should not run",
        )
    )
    registry.register(
        Tool(
            name="echo",
            description="echo",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=lambda text: f"echoed:{text}",
        )
    )

    state = {"step": 0}

    def stub(messages, tools, system):
        state["step"] += 1
        if state["step"] == 1:
            return LLMResponse(
                stop_reason="tool_use",
                text="trying forbidden",
                tool_calls=[ToolCall(id="t1", name="forbidden", input={})],
            )
        return LLMResponse(
            stop_reason="end_turn",
            text="Got permission denied; stopping.",
            tool_calls=[],
        )

    client = LLMClient(stub=stub)
    obs = Observability(db_path=str(tmp_db))
    config = AgentConfig(
        name="restricted_agent",
        system_prompt="test",
        policy=AgentPolicy.of("restricted_agent", ["echo"]),
        max_turns=4,
    )

    result = run_agent(
        config,
        initial_user_message="try the forbidden tool",
        client=client,
        tools=registry,
        observability=obs,
    )

    assert result.stopped_reason == "end_turn"
    conn = get_db(tmp_db)
    row = conn.execute(
        "SELECT tool_success, tool_result_summary FROM agent_logs WHERE tool_called='forbidden'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["tool_success"] == 0
    assert "permission_denied" in row["tool_result_summary"]
    obs.close()
