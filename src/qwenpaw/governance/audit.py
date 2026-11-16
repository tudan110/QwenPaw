# -*- coding: utf-8 -*-
"""AuditLog — Audit records for each assert_policy + audit call.

Storage: single-file SQLite (~/.qwenpaw/audit.db), global singleton.
- record() writes immediately, no in-memory buffer
- query() supports filtering by workspace / agent / tool / decision /
  time range, with pagination
- purge() removes only archived records older than six calendar months
- Each new event is committed with a durable archive-outbox entry
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import calendar
import hashlib
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
CREATE TABLE IF NOT EXISTS audit_outbox (
    event_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
    created_at INTEGER NOT NULL, archived_at INTEGER
);
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

    MAX_RECORDS = 100_000  # Threshold to trigger auto-cleanup
    PURGE_COUNT = 10_000  # Number of records to delete per cleanup
    _CHECK_INTERVAL = 1_000

    _instance: Optional[AuditLog] = None
    _db_path: Path
    _conn: sqlite3.Connection
    _insert_count: int
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
        # Convert legacy timestamps without dropping historical records.
        cls._migrate_legacy_schema(obj._conn)
        obj._conn.executescript(_SCHEMA)
        obj._conn.commit()
        obj._insert_count = 0
        obj._lock = threading.Lock()
        return obj

    @staticmethod
    def _migrate_legacy_schema(conn: sqlite3.Connection) -> None:
        """Convert legacy timestamps transactionally without deleting evidence."""
        cursor = conn.execute("PRAGMA table_info(audit_events)")
        for row in cursor.fetchall():
            # row: (cid, name, type, notnull, dflt_value, pk)
            if row[1] == "ts" and row[2].upper() != "INTEGER":
                rows = conn.execute("SELECT * FROM audit_events").fetchall()
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        "ALTER TABLE audit_events RENAME TO audit_events_legacy"
                    )
                    conn.execute(
                        "CREATE TABLE audit_events(ts INTEGER NOT NULL,workspace_dir TEXT NOT NULL,agent_id TEXT NOT NULL,session_id TEXT NOT NULL,tool_name TEXT NOT NULL,target TEXT NOT NULL,decision TEXT NOT NULL,reason TEXT NOT NULL,extra TEXT NOT NULL)"
                    )
                    for item in rows:
                        values = list(item)
                        if isinstance(values[0], str) and not values[0].isdigit():
                            dt = datetime.fromisoformat(
                                values[0].replace("Z", "+00:00")
                            )
                            values[0] = int(
                                dt.replace(tzinfo=dt.tzinfo or timezone.utc).timestamp()
                                * 1000
                            )
                        else:
                            values[0] = int(values[0])
                        conn.execute(
                            "INSERT INTO audit_events VALUES(?,?,?,?,?,?,?,?,?)", values
                        )
                    conn.execute("DROP TABLE audit_events_legacy")
                break

    def close(self) -> None:
        """Close the database connection and reset the singleton.

        Runs VACUUM before closing to reclaim space from any prior
        auto-purge DELETE operations (VACUUM is intentionally NOT run
        inside ``_auto_purge`` to avoid blocking the event loop).
        """
        if self._conn:
            try:
                self._conn.execute("VACUUM")
            except sqlite3.Error:
                pass
            self._conn.close()
            self._conn = None
        AuditLog._instance = None

    def record(
        self,
        workspace_dir: str,
        tc_spec: ToolCallSpec,
        decision: GovernanceDecision,
    ) -> None:
        """Record a policy decision, writing to SQLite immediately.

        Args:
            workspace_dir: Workspace path this event belongs to
            tc_spec: ToolCallSpec instance
            decision: GovernanceDecision instance (action + reason)
        Audit failure raises PermissionError before execution. Production
        evidence collection cannot be disabled by an agent policy setting.
        """
        from ..extensions.api.access_session import CURRENT_IDENTITY
        identity = CURRENT_IDENTITY.get()
        extra = (
            {"auth_user_id": identity.user_id, "auth_source": identity.source}
            if identity is not None else {}
        )
        self._append(
            workspace_dir,
            tc_spec,
            str(decision.action.value),
            decision.reason,
            {"event_type": "policy_decision", **extra},
        )

    def _append(self, workspace_dir, tc_spec, decision, reason, extra):
        from ..extensions.security.output_guard.redactor import redact

        target = tc_spec.target or ""
        if tc_spec.tool_name == "Bash":
            target = "sha256:" + hashlib.sha256(target.encode()).hexdigest()
        event_id = uuid.uuid4().hex
        payload = {
            "ts": _now_unix_ms(),
            "workspace_dir": workspace_dir,
            "agent_id": tc_spec.agent_id,
            "session_id": tc_spec.session_id,
            "tool_name": tc_spec.tool_name,
            "target": redact(target)[0],
            "decision": decision,
            "reason": redact(reason or "")[0],
            "extra": {"event_id": event_id, **extra},
        }
        try:
            with self._lock, self._conn:
                if extra.get("outcome") == "started":
                    from ..constant import EnvVarLoader

                    maximum = max(
                        1,
                        int(
                            EnvVarLoader.get_str("QWENPAW_AUDIT_MAX_PENDING", "100000")
                        ),
                    )
                    pending = self._conn.execute(
                        "SELECT COUNT(*) FROM audit_outbox WHERE archived_at IS NULL"
                    ).fetchone()[0]
                    if pending >= maximum:
                        raise PermissionError("审计归档积压达到上限，已阻断新执行")
                self._conn.execute(
                    "INSERT INTO audit_events VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        payload["ts"],
                        workspace_dir,
                        tc_spec.agent_id,
                        tc_spec.session_id,
                        tc_spec.tool_name,
                        payload["target"],
                        decision,
                        payload["reason"],
                        json.dumps(payload["extra"], ensure_ascii=False),
                    ),
                )
                self._conn.execute(
                    "INSERT INTO audit_outbox VALUES(?,?,?,NULL)",
                    (
                        event_id,
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        payload["ts"],
                    ),
                )
        except (sqlite3.Error, TypeError, AttributeError):
            _logger.error("Audit storage unavailable; execution must remain blocked")
            raise PermissionError("审计存储不可用，已阻断执行") from None
        return event_id

    def archive_status(self) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS pending,MIN(created_at) AS oldest_at FROM audit_outbox WHERE archived_at IS NULL"
            ).fetchone()
            return {
                **dict(row),
                "minimum_retention": "six_calendar_months",
                "external_retention_verified": False,
            }

    def execution_event(
        self, workspace_dir, tc_spec, outcome, *, trace_id=None, error_type=""
    ) -> str:
        trace_id = trace_id or uuid.uuid4().hex
        from ..extensions.api.access_session import CURRENT_IDENTITY

        identity = CURRENT_IDENTITY.get()
        from .execution_trace import CURRENT_EXECUTION_TRACE

        self._append(
            workspace_dir,
            tc_spec,
            "execution",
            "",
            {
                "event_type": "tool_execution",
                "trace_id": trace_id,
                "outcome": outcome,
                "parent_trace_id": (
                    CURRENT_EXECUTION_TRACE.get()
                    if CURRENT_EXECUTION_TRACE.get() != trace_id
                    else ""
                ),
                "error_type": error_type,
                "auth_user_id": identity.user_id if identity else "",
                "params_sha256": hashlib.sha256(
                    json.dumps(tc_spec.raw_params, sort_keys=True, default=str).encode()
                ).hexdigest(),
            },
        )
        return trace_id

    def pending_archive(self, limit: int = 500) -> list[dict]:
        with self._lock:
            return [
                dict(row)
                for row in self._conn.execute(
                    "SELECT event_id,payload,created_at FROM audit_outbox WHERE archived_at IS NULL ORDER BY created_at LIMIT ?",
                    (min(max(limit, 1), 5000),),
                ).fetchall()
            ]

    def acknowledge_archive(self, event_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE audit_outbox SET archived_at=? WHERE event_id=?",
                (_now_unix_ms(), event_id),
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
        """Delete records before the specified time and VACUUM to
        reclaim space.

        Args:
            before: Cutoff time (unix ms, UTC), exclusive

        Returns:
            Number of deleted records, or ``0`` on SQLite error.
        """
        # A record must be at least six calendar months old AND acknowledged
        # by the archive worker. Never purge the only copy.
        now = datetime.now(timezone.utc)
        month_index = now.year * 12 + now.month - 1 - 6
        year, month = divmod(month_index, 12)
        month += 1
        cutoff = int(
            now.replace(
                year=year,
                month=month,
                day=min(now.day, calendar.monthrange(year, month)[1]),
            ).timestamp()
            * 1000
        )
        before = min(before, cutoff)
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "DELETE FROM audit_events WHERE ts < ? AND json_extract(extra,'$.event_id') IN (SELECT event_id FROM audit_outbox WHERE archived_at IS NOT NULL)",
                    (before,),
                )
                self._conn.commit()
                deleted = cursor.rowcount
                if deleted > 0:
                    self._conn.execute("VACUUM")
            return deleted
        except sqlite3.Error as e:
            _logger.error(
                "AuditLog.purge: SQLite error: %s",
                e,
                exc_info=True,
            )
            return 0

    @property
    def count(self) -> int:
        """Total number of records."""
        return self._conn.execute(
            "SELECT COUNT(*) FROM audit_events",
        ).fetchone()[0]

    def _auto_purge(self) -> None:
        """Compatibility hook: capacity never overrides evidence retention."""
        _logger.warning("Audit capacity threshold reached; unique evidence retained")
