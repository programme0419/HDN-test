"""Local persistence for debrief sessions using SQLite (standard library).

Sessions are stored as a JSON snapshot in a single table, with a few columns
lifted out for listing and search. The database lives in a local, gitignored
directory because a debrief can contain sensitive operational detail and must
never be committed.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import List, Optional

from .assessment import Evaluator
from .session import DebriefSession

DEFAULT_DB_DIR = "debriefs"
DEFAULT_DB_NAME = "debriefs.db"


def default_db_path() -> str:
    return os.path.join(DEFAULT_DB_DIR, DEFAULT_DB_NAME)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    mission_name  TEXT,
    unit          TEXT,
    date_time     TEXT,
    mission_type  TEXT,
    state         TEXT,
    overall_score INTEGER,
    created_at    REAL,
    updated_at    REAL,
    data          TEXT NOT NULL
);
"""


class DebriefStore:
    """CRUD persistence for :class:`DebriefSession` objects."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or default_db_path()
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "DebriefStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def save(self, session: DebriefSession) -> None:
        """Insert or update a session snapshot."""
        meta = session.metadata
        try:
            overall = session.score().overall
        except Exception:
            overall = 0
        self._conn.execute(
            """
            INSERT INTO sessions
                (id, mission_name, unit, date_time, mission_type, state,
                 overall_score, created_at, updated_at, data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                mission_name=excluded.mission_name,
                unit=excluded.unit,
                date_time=excluded.date_time,
                mission_type=excluded.mission_type,
                state=excluded.state,
                overall_score=excluded.overall_score,
                updated_at=excluded.updated_at,
                data=excluded.data
            """,
            (
                session.id,
                meta.mission_name,
                meta.unit,
                meta.date_time,
                meta.mission_type,
                session.state.value,
                overall,
                session.created_at,
                session.updated_at or time.time(),
                json.dumps(session.to_dict()),
            ),
        )
        self._conn.commit()

    def load(
        self, session_id: str, evaluator: Optional[Evaluator] = None
    ) -> Optional[DebriefSession]:
        row = self._conn.execute(
            "SELECT data FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        return DebriefSession.from_dict(json.loads(row["data"]), evaluator=evaluator)

    def list(self) -> List[dict]:
        """Return lightweight summaries, most recently updated first."""
        rows = self._conn.execute(
            """
            SELECT id, mission_name, unit, date_time, mission_type, state,
                   overall_score, created_at, updated_at
            FROM sessions
            ORDER BY updated_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, session_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM sessions WHERE id = ?", (session_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0
