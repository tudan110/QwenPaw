# -*- coding: utf-8 -*-
"""AuditLog — Audit records for each assert_policy + audit call.

Storage: single-file SQLite (~/.qwenpaw/audit.db), global singleton.
- record() writes immediately, no in-memory buffer
- query() supports filtering by workspace / agent / tool / decision /
  time range, with pagination
- Retains local evidence without capacity-based deletion.
- Never erases old records during initialization.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from ..constant import WORKING_DIR

from .policy import GovernanceDecision, ToolCallSpec

_logger = logging.getLogger(__name__)

# ``ts`` is stored as INTEGER (milliseconds since epoch, UTC) so that
# ``WHERE ts >= ? / <= ?`` performs strict numeric comparison instead of
# fragile lexicographic comparison on ISO 8601 strings.
_SCHEMA = """\
CREATE TABLE IF NOT EXISTS audit_events (
    ts            INTEGER NOT NULL,
    workspace_dir TEXT NOT NULL,
    agent_id      TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    tool_name     TEXT NOT NULL,
    target        TEXT NOT NULL,
    decision      TEXT NOT NULL,
    reason        TEXT NOT NULL DEFAULT '',
    extra         TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_events(ts);
CREATE INDEX IF NOT EXISTS idx_audit_workspace ON audit_events(workspace_dir);
CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_tool ON audit_events(tool_name);
"""


def _now_unix_ms() -> int:
    """Return current UTC timestamp in milliseconds since epoch."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)


@dataclass
class AuditEvent:
    """A single audit record.

    Records 5W: who (agent_id), what (tool_name + target),
    when (ts), outcome (decision), why (reason).
    """

    ts: int  # Milliseconds since epoch, UTC
    workspace_dir: str
    agent_id: str
    session_id: str
    tool_name: str
    target: str
    decision: str  # "allow" | "deny" | "ask" | "sandbox_fallback"
    reason: str = ""  # Additional explanation (e.g. violation cause)
    extra: dict = field(default_factory=dict)


def _event_from_row(row: sqlite3.Row) -> AuditEvent:
    """Construct an AuditEvent from a SQLite row."""
    return AuditEvent(
        ts=row["ts"],
        workspace_dir=row["workspace_dir"],
        agent_id=row["agent_id"],
        session_id=row["session_id"],
        tool_name=row["tool_name"],
        target=row["target"],
        decision=row["decision"],
        reason=row["reason"],
        extra=json.loads(row["extra"]),
    )


class AuditLog:
    """Append-only audit log, SQLite-backed, global singleton.

    Shared by multiple ResourceGovernor instances; each audit()
    call (typically after assert_policy()) invokes record() which writes
    to the database immediately.

    .. note:: Threading & async

        All SQLite operations are synchronous and protected by a
        ``threading.Lock``.  When called from an async context
        (e.g. ``check_permissions``), the event-loop thread is briefly
        blocked for the INSERT + commit (~sub-ms with WAL mode).
        TODO: migrate to ``aiosqlite`` or ``asyncio.to_thread()`` for
        true non-blocking audit writes.
    """

    _instance: Optional[AuditLog] = None
    _db_path: Path
    _conn: sqlite3.Connection
    _lock: threading.Lock

    @classmethod
    def get_instance(
        cls,
        db_dir: Optional[Path] = None,
    ) -> AuditLog:
        """Get the global singleton, initializing on first call.

        Args:
            db_dir: Optional directory to place ``audit.db`` in. Only
                honored on first creation; if the singleton already
                exists in a different directory, the request is logged
                and ignored (the singleton stays shared).
        """
        if cls._instance is None:
            if db_dir is not None:
                resolved_dir = Path(db_dir)
            else:
                resolved_dir = WORKING_DIR / "governance"
            cls._instance = cls._create(resolved_dir / "audit.db")
        return cls._instance

    @classmethod
    def _create(cls, db_path: Path) -> AuditLog:
        """Internal factory method: create instance and initialize database."""
        obj = object.__new__(cls)
        obj._db_path = db_path
        obj._db_path.parent.mkdir(parents=True, exist_ok=True)
        obj._conn = sqlite3.connect(
            str(obj._db_path),
            check_same_thread=False,
        )
        obj._conn.row_factory = sqlite3.Row
        obj._conn.execute("PRAGMA journal_mode=WAL")
        obj._conn.execute("PRAGMA synchronous=FULL")
        try:
            cls._migrate_legacy_schema(obj._conn)
            obj._conn.executescript(_SCHEMA)
            obj._conn.commit()
        except Exception:
            obj._conn.close()
            raise
        obj._lock = threading.Lock()
        return obj

    @staticmethod
    def _migrate_legacy_schema(conn: sqlite3.Connection) -> None:
        """Normalize existing timestamps atomically, keeping the original rows."""
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            types = {row[1]: row[2].upper() for row in conn.execute(
                "PRAGMA table_info(audit_events)"
            )}
            if not types or types.get("ts") == "INTEGER":
                return
            # The original table retains its timestamps byte for byte. Drop
            # no data; a failed conversion rolls back the schema change too.
            conn.execute("ALTER TABLE audit_events RENAME TO audit_events_legacy")
            for name in ("ts", "workspace", "agent", "tool"):
                conn.execute(f"DROP INDEX IF EXISTS idx_audit_{name}")
            conn.execute(_SCHEMA.split(";", 1)[0])
            fields = "ts, workspace_dir, agent_id, session_id, tool_name, target, decision, reason, extra"
            for row in conn.execute(f"SELECT {fields} FROM audit_events_legacy"):
                timestamp = str(row[0])
                if timestamp.isdecimal():
                    milliseconds = int(timestamp)
                else:
                    value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    milliseconds = int(value.replace(
                        tzinfo=value.tzinfo or timezone.utc,
                    ).timestamp() * 1000)
                conn.execute(
                    f"INSERT INTO audit_events ({fields}) VALUES (?,?,?,?,?,?,?,?,?)",
                    (milliseconds, *tuple(row)[1:]),
                )

    def close(self) -> None:
        """Close the database connection and reset the singleton."""
        with self._lock:
            self._conn.close()
            if AuditLog._instance is self:
                AuditLog._instance = None

    def record(
        self,
        workspace_dir: str,
        tc_spec: ToolCallSpec,
        decision: GovernanceDecision,
    ) -> None:
        """Record a policy decision as a separate event from execution."""
        try:
            self._append(AuditEvent(
                ts=_now_unix_ms(), workspace_dir=workspace_dir,
                agent_id=tc_spec.agent_id, session_id=tc_spec.session_id,
                tool_name=tc_spec.tool_name, target=tc_spec.target,
                decision=decision.action.value, reason=decision.reason,
                extra=self._identity_fields(),
            ))
        except sqlite3.Error:
            _logger.error("Cannot persist governance decision", exc_info=True)

    @staticmethod
    def _identity_fields() -> dict:
        from ..extensions.api.access_session import CURRENT_IDENTITY

        identity = CURRENT_IDENTITY.get()
        return (
            {"auth_user_id": identity.user_id, "auth_source": identity.source}
            if identity is not None else {}
        )

    def record_execution(
        self, workspace_dir: str, *, agent_id: str, session_id: str,
        tool_name: str, event_id: str, result: str,
    ) -> None:
        """Store observed execution status without saving tool inputs or output."""
        if result not in {
            "started", "success", "error", "denied", "cancelled", "returned",
            "unconfirmed",
        }:
            raise ValueError("Unknown execution result")
        self._append(AuditEvent(
            ts=_now_unix_ms(), workspace_dir=workspace_dir,
            agent_id=agent_id, session_id=session_id, tool_name=tool_name,
            target=tool_name, decision="", extra={
                **self._identity_fields(),
                "kind": "tool_execution", "result": result, "call_id": event_id,
            },
        ))

    def _append(self, event: AuditEvent) -> None:
        extra = {"event_id": uuid.uuid4().hex, **event.extra}
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO audit_events "
                "(ts, workspace_dir, agent_id, session_id, "
                "tool_name, target, decision, reason, extra) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event.ts, event.workspace_dir, event.agent_id, event.session_id,
                 event.tool_name, event.target, event.decision, event.reason,
                 json.dumps(extra)),
            )

    def query(
        self,
        workspace_dir: Optional[str] = None,
        agent_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        decision: Optional[str] = None,
        since: Optional[int] = None,
        until: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[AuditEvent], int]:
        """Query audit events with pagination.

        Args:
            workspace_dir: Filter by workspace
            agent_id: Filter by agent
            tool_name: Filter by tool name
            decision: Filter by decision result
            since: Start time (unix ms, UTC), inclusive
            until: End time (unix ms, UTC), inclusive
            limit: Page size
            offset: Offset (for pagination)

        Returns:
            (events, total) — event list and total count of matching
            records. Returns ``([], 0)`` if a SQLite error occurs so
            callers (e.g. the Console UI) get a safe empty page rather
            than an unhandled exception.
        """
        clauses: list[str] = []
        params: list = []

        if workspace_dir:
            clauses.append("workspace_dir = ?")
            params.append(workspace_dir)
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if tool_name:
            clauses.append("tool_name = ?")
            params.append(tool_name)
        if decision:
            clauses.append("decision = ?")
            params.append(decision)
        if since:
            clauses.append("ts >= ?")
            params.append(since)
        if until:
            clauses.append("ts <= ?")
            params.append(until)

        where = " WHERE " + " AND ".join(clauses) if clauses else ""

        try:
            # Total count
            count_sql = f"SELECT COUNT(*) FROM audit_events{where}"
            total = self._conn.execute(count_sql, params).fetchone()[0]

            # Paginated query
            data_sql = (
                f"SELECT * FROM audit_events{where} "
                "ORDER BY ts DESC LIMIT ? OFFSET ?"
            )
            data_params = params + [limit, offset]
            rows = self._conn.execute(data_sql, data_params).fetchall()

            return [_event_from_row(r) for r in rows], total
        except sqlite3.Error as e:
            _logger.error(
                "AuditLog.query: SQLite error: %s",
                e,
                exc_info=True,
            )
            return [], 0

    def purge(self, before: int) -> int:
        """Retain the only audit copy until independent archival is verified."""
        return 0

    @property
    def count(self) -> int:
        """Total number of records."""
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
