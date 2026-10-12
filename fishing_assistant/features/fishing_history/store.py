"""SQLite persistence for completed and in-progress fishing sessions."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import threading

from fishing_assistant.automation.models import FishingResult


@dataclass(frozen=True, slots=True)
class FishingHistoryRecord:
    session_id: int
    started_at: str
    ended_at: str | None
    catch_count: int
    ordinary_count: int
    failure_count: int
    status: str
    end_reason: str


@dataclass(frozen=True, slots=True)
class FishingHistorySummary:
    session_count: int
    catch_count: int
    ordinary_count: int
    failure_count: int
    average_duration_seconds: float

    @property
    def total_rounds(self) -> int:
        return self.catch_count + self.ordinary_count + self.failure_count

    @property
    def success_rate(self) -> float:
        if self.total_rounds == 0:
            return 0.0
        return (self.catch_count + self.ordinary_count) / self.total_rounds


class FishingHistoryStore:
    """Stores one row per automatic-fishing session in a local SQLite database."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = str(database_path) if database_path is not None else ":memory:"
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.database_path, check_same_thread=False, timeout=5.0
        )
        self._closed = False
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        if self.database_path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()
        self._mark_unfinished_sessions_interrupted()

    @classmethod
    def default(cls) -> FishingHistoryStore:
        app_data = Path(
            os.environ.get("LOCALAPPDATA", str(Path.home()))
        ) / "MabinogiFishingHelper"
        return cls(app_data / "fishing_history.sqlite3")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS fishing_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    catch_count INTEGER NOT NULL DEFAULT 0,
                    ordinary_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    end_reason TEXT NOT NULL DEFAULT ''
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS fishing_sessions_started_at
                ON fishing_sessions (started_at DESC)
                """
            )

    def _mark_unfinished_sessions_interrupted(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE fishing_sessions
                SET ended_at = ?, status = 'interrupted',
                    end_reason = 'application_terminated'
                WHERE ended_at IS NULL
                """,
                (self._now(),),
            )

    def start_session(self) -> int:
        self._ensure_open()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO fishing_sessions (started_at, status)
                VALUES (?, 'running')
                """,
                (self._now(),),
            )
            return int(cursor.lastrowid)

    def record_result(self, session_id: int, result: FishingResult) -> None:
        column = {
            FishingResult.CATCH: "catch_count",
            FishingResult.ORDINARY: "ordinary_count",
            FishingResult.FAILURE: "failure_count",
        }[result]
        self._ensure_open()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                f"""
                UPDATE fishing_sessions
                SET {column} = {column} + 1
                WHERE id = ? AND ended_at IS NULL
                """,
                (session_id,),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"Fishing session {session_id} is missing or already closed."
                )

    def finish_session(self, session_id: int, end_reason: str) -> None:
        self._ensure_open()
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE fishing_sessions
                SET ended_at = ?, status = 'completed', end_reason = ?
                WHERE id = ? AND ended_at IS NULL
                """,
                (self._now(), end_reason, session_id),
            )

    def list_sessions(self, limit: int = 100) -> list[FishingHistoryRecord]:
        self._ensure_open()
        safe_limit = max(1, min(1000, int(limit)))
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id, started_at, ended_at, catch_count, ordinary_count,
                       failure_count, status, end_reason
                FROM fishing_sessions
                ORDER BY started_at DESC, id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [FishingHistoryRecord(*row) for row in rows]

    def summary(self) -> FishingHistorySummary:
        self._ensure_open()
        with self._lock:
            row = self._connection.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(catch_count), 0),
                       COALESCE(SUM(ordinary_count), 0),
                       COALESCE(SUM(failure_count), 0),
                       COALESCE(
                           AVG((julianday(ended_at) - julianday(started_at)) * 86400),
                           0
                       )
                FROM fishing_sessions
                """
            ).fetchone()
        return FishingHistorySummary(
            session_count=int(row[0]),
            catch_count=int(row[1]),
            ordinary_count=int(row[2]),
            failure_count=int(row[3]),
            average_duration_seconds=float(row[4]),
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._connection.close()
            self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Fishing history store is closed.")
