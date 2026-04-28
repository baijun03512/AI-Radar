"""Observability: every tool call is recorded to SQLite agent_logs."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from ..data import get_db, init_db


def _summarize(value: Any, limit: int = 200) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            value = str(value)
    return value if len(value) <= limit else value[: limit - 3] + "..."


@dataclass
class LogEntry:
    agent: str
    turn: int
    reasoning: str = ""
    tool_called: Optional[str] = None
    tool_input: Optional[dict] = None
    tool_result_summary: str = ""
    tool_success: bool = True
    context_tokens: int = 0
    duration_ms: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Observability:
    """Writes structured logs. Auto-initializes DB on first use."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path
        init_db(db_path)
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = get_db(self.db_path)
        return self._conn

    def log(self, entry: LogEntry) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO agent_logs (
                agent_name, turn, reasoning, tool_called, tool_input,
                tool_result_summary, tool_success, context_tokens, duration_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.agent,
                entry.turn,
                _summarize(entry.reasoning, 1000),
                entry.tool_called,
                json.dumps(entry.tool_input, ensure_ascii=False) if entry.tool_input else None,
                _summarize(entry.tool_result_summary, 200),
                1 if entry.tool_success else 0,
                entry.context_tokens,
                entry.duration_ms,
                entry.timestamp,
            ),
        )
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
