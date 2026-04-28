"""SQLite layer. Three tables per PRD section 17.2."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "radar.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS user_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    item_title TEXT,
    action TEXT NOT NULL,
    pool_type TEXT,
    novelty_label TEXT,
    chat_turns INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feed_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_date DATE NOT NULL,
    item_id TEXT NOT NULL,
    pool_type TEXT NOT NULL,
    final_score REAL,
    novelty_score REAL,
    preference_score REAL,
    novelty_label TEXT,
    source_platform TEXT,
    source_layer TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    turn INTEGER,
    reasoning TEXT,
    tool_called TEXT,
    tool_input TEXT,
    tool_result_summary TEXT,
    tool_success INTEGER,
    context_tokens INTEGER,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_actions_created ON user_actions(created_at);
CREATE INDEX IF NOT EXISTS idx_feed_date ON feed_history(feed_date);
CREATE INDEX IF NOT EXISTS idx_logs_agent_time ON agent_logs(agent_name, created_at);
"""


def _resolve_path(path: Optional[str | os.PathLike]) -> Path:
    if path is None:
        env = os.getenv("SQLITE_DB_PATH")
        path = env if env else DEFAULT_DB_PATH
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_db(path: Optional[str | os.PathLike] = None) -> sqlite3.Connection:
    """Open a connection. Caller is responsible for closing."""
    p = _resolve_path(path)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(path: Optional[str | os.PathLike] = None) -> Path:
    """Create tables if missing. Idempotent."""
    p = _resolve_path(path)
    conn = sqlite3.connect(str(p))
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    return p


if __name__ == "__main__":
    out = init_db()
    print(f"Initialized SQLite at: {out}")
