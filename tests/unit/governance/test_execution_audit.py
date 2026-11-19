"""Tool audit records preserve the real lifecycle and historical evidence."""

import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest
from agentscope.message import ToolResultState
from agentscope.tool import FunctionTool, ToolChunk

from qwenpaw.extensions.api.access_session import AccessIdentity, CURRENT_IDENTITY
from qwenpaw.governance.audit import AuditLog, _SCHEMA
from qwenpaw.governance.tool_adapter import _execute_audited


@pytest.fixture
def log(tmp_path):
    audit = AuditLog._create(tmp_path / "audit.db")
    yield audit
    audit.close()


def records(log):
    with sqlite3.connect(log._db_path) as conn:
        return [
            (row[0], json.loads(row[1]))
            for row in conn.execute("SELECT target, extra FROM audit_events ORDER BY rowid")
        ]


async def execute(log, tool):
    tool._qp_governor = SimpleNamespace(audit_log=log, workspace_dir="workspace")
    tool._qp_request_context = {"agent_id": "agent", "session_id": "session"}
    token = CURRENT_IDENTITY.set(AccessIdentity({"userId": "u1"}, "never-store-token"))
    try:
        value = await _execute_audited(tool, FunctionTool.__call__)
        if isinstance(value, ToolChunk):
            return [value]
        return [chunk async for chunk in value]
    finally:
        CURRENT_IDENTITY.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [ToolResultState.SUCCESS, ToolResultState.ERROR])
async def test_actual_stream_outcome_is_distinct_from_policy(log, state):
    async def read_sample():
        """Read a test sample."""
        yield ToolChunk(content=[], is_last=False)
        assert [row[1]["result"] for row in records(log)] == ["started"]
        yield ToolChunk(content=[], state=state)

    chunks = await execute(log, FunctionTool(read_sample))
    assert len(chunks) == 2 and chunks[-1].state == state
    start, finish = records(log)
    assert start[0] == finish[0] == "read_sample"
    assert start[1]["call_id"] == finish[1]["call_id"]
    assert finish[1]["result"] == state.value
    assert finish[1]["auth_user_id"] == "u1"
    assert "never-store-token" not in str((start, finish))


@pytest.mark.asyncio
async def test_cancellation_does_not_become_success(log):
    ready = asyncio.Event()

    async def read_sample():
        """Wait for a pending operation."""
        ready.set()
        await asyncio.Future()

    task = asyncio.create_task(execute(log, FunctionTool(read_sample)))
    await asyncio.wait_for(ready.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [row[1]["result"] for row in records(log)] == ["started", "cancelled"]


@pytest.mark.asyncio
async def test_plain_return_does_not_claim_business_success(log):
    def read_sample():
        """Return a plain adapter result."""
        return "a business error could be embedded in plain text"

    await execute(log, FunctionTool(read_sample))
    assert [row[1]["result"] for row in records(log)] == ["started", "returned"]


@pytest.mark.asyncio
async def test_failed_pre_execution_write_prevents_call(log, monkeypatch):
    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("disk unavailable")

    def read_sample():
        """Must never run while audit is unavailable."""
        pytest.fail("call started without an audit record")

    monkeypatch.setattr(log, "record_execution", unavailable)
    with pytest.raises(sqlite3.OperationalError):
        await execute(log, FunctionTool(read_sample))


def test_legacy_audit_retention_is_non_destructive(tmp_path):
    path = tmp_path / "audit.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(_SCHEMA.replace("ts            INTEGER", "ts            TEXT"))
        conn.execute(
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2025-01-01T00:00:00Z", "workspace", "agent", "session",
             "tool", "target", "allow", "reason", "{}"),
        )
    log = AuditLog._create(path)
    try:
        assert log.purge(2_000_000_000_000) == 0
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT ts FROM audit_events").fetchone() == (1_735_689_600_000,)
            assert conn.execute("SELECT ts FROM audit_events_legacy").fetchone() == ("2025-01-01T00:00:00Z",)
    finally:
        log.close()
