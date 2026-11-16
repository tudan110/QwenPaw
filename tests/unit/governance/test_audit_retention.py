"""Audit evidence is durable, redacted and cannot be purged prematurely."""

import sqlite3
from datetime import datetime, timezone

import pytest

from qwenpaw.governance.audit import AuditLog
from qwenpaw.governance.policy import GovernanceAction, GovernanceDecision, ToolCallSpec


def test_record_count_cleanup_never_deletes_unique_evidence(tmp_path):
    log = AuditLog._create(tmp_path / "audit.db")
    try:
        log.MAX_RECORDS = 2
        log._CHECK_INTERVAL = 1
        log.PURGE_COUNT = 1
        for _ in range(3):
            log.record(
                "w",
                ToolCallSpec(
                    tool_name="Read", target="a", agent_id="a", session_id="s"
                ),
                GovernanceDecision(action=GovernanceAction.ALLOW, reason="allowed"),
            )
        assert log.count == 3
        assert log.purge(int(datetime.now(timezone.utc).timestamp() * 1000) + 1) == 0
    finally:
        log.close()


def test_execution_events_redact_and_are_queued_atomically(tmp_path):
    log = AuditLog._create(tmp_path / "audit.db")
    try:
        tc = ToolCallSpec(
            tool_name="Bash",
            target="python report.py --token secret-password",
            agent_id="a",
            session_id="s",
        )
        trace = log.execution_event("w", tc, "started", trace_id="trace-1")
        log.execution_event(
            "w", tc, "failed", trace_id=trace, error_type="RuntimeError"
        )
        events, total = log.query()
        assert total == 2
        assert all("secret-password" not in e.target for e in events)
        assert {e.extra["outcome"] for e in events} == {"started", "failed"}
        assert all(e.extra["trace_id"] == "trace-1" for e in events)
        assert len(log.pending_archive()) == 2
    finally:
        log.close()


def test_legacy_schema_is_migrated_without_losing_history(tmp_path):
    path = tmp_path / "audit.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE audit_events(ts TEXT,workspace_dir TEXT,agent_id TEXT,session_id TEXT,tool_name TEXT,target TEXT,decision TEXT,reason TEXT,extra TEXT)"
        )
        conn.execute(
            "INSERT INTO audit_events VALUES('2026-01-01T00:00:00+00:00','w','a','s','Read','x','allow','','{}')"
        )
    log = AuditLog._create(path)
    try:
        assert log.count == 1
        assert log.query()[0][0].ts == 1767225600000
    finally:
        log.close()


def test_audit_failure_blocks_execution(tmp_path):
    log = AuditLog._create(tmp_path / "audit.db")
    log.close()
    with pytest.raises(PermissionError):
        log.execution_event(
            "w",
            ToolCallSpec(tool_name="Write", target="a", agent_id="a", session_id="s"),
            "started",
        )


def test_six_calendar_months_and_archive_ack_are_both_required(monkeypatch, tmp_path):
    from qwenpaw.governance import audit

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 8, 31, 12, tzinfo=timezone.utc)

    monkeypatch.setattr(audit, "datetime", Clock)
    log = AuditLog._create(tmp_path / "audit.db")
    try:
        for day in (27, 28, 1):
            ts = int(datetime(2026, 2, day, 12, tzinfo=timezone.utc).timestamp() * 1000)
            monkeypatch.setattr(audit, "_now_unix_ms", lambda value=ts: value)
            log.execution_event("w", ToolCallSpec("Read", "a", "a", "s"), "completed")
        pending = log.pending_archive()
        # Acknowledge Feb27 and Feb28; leave Feb1 as the unique local copy.
        for row in pending:
            if datetime.fromtimestamp(row["created_at"] / 1000, timezone.utc).day != 1:
                log.acknowledge_archive(row["event_id"])
        assert log.purge(9999999999999) == 1
        assert log.count == 2
    finally:
        log.close()
