"""
SQLite database layer for the news bot.
Stores all posts with channel info and timestamps for querying.
"""

import sqlite3
from datetime import datetime
from typing import Optional


class Database:
    def __init__(self, path: str):
        self.path = path
        self._init()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id  TEXT    NOT NULL,
                    channel_name TEXT   NOT NULL,
                    channel_username TEXT,
                    message_id  INTEGER NOT NULL,
                    text        TEXT    NOT NULL,
                    timestamp   DATETIME NOT NULL,
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(channel_id, message_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON posts(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_channel ON posts(channel_id)")
            conn.commit()

    def channel_stats_by_username(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT LOWER(channel_username) as uname, COUNT(*) as cnt FROM posts WHERE channel_username IS NOT NULL GROUP BY LOWER(channel_username)"
            ).fetchall()
        return {r["uname"]: r["cnt"] for r in rows}

    def save_post(
        self,
        channel_id: str,
        channel_name: str,
        channel_username: Optional[str],
        message_id: int,
        text: str,
        timestamp: datetime,
    ):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO posts
                    (channel_id, channel_name, channel_username, message_id, text, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (channel_id, channel_name, channel_username, message_id, text, timestamp),
            )
            conn.commit()

    def recent_posts(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM posts ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def posts_since(self, since: datetime) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM posts WHERE timestamp >= ? ORDER BY timestamp DESC",
                (since,),
            ).fetchall()
        return [dict(r) for r in rows]

    def posts_about(self, topic: str, limit: int = 50) -> list[dict]:
        """Simple keyword search across post text."""
        keywords = topic.lower().split()
        with self._connect() as conn:
            # Build a WHERE clause that requires ALL keywords to appear
            conditions = " AND ".join(["LOWER(text) LIKE ?" for _ in keywords])
            params = [f"%{kw}%" for kw in keywords] + [limit]
            rows = conn.execute(
                f"SELECT * FROM posts WHERE {conditions} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def channel_stats(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT channel_id, COUNT(*) as cnt FROM posts GROUP BY channel_id"
            ).fetchall()
        return {r["channel_id"]: r["cnt"] for r in rows}

    def total_posts(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
