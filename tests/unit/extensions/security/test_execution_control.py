"""Freeze epochs survive restart and cancellation is not premature success."""

import asyncio

import pytest

from qwenpaw.extensions.security.execution_control import ControlStore


def test_freeze_survives_reopening_and_stale_unfreeze_rejected(tmp_path):
    path = tmp_path / "control.db"
    store = ControlStore(path)
    initial = store.snapshot()
    frozen = store.transition(True, "incident", initial["epoch"])
    reopened = ControlStore(path)
    with pytest.raises(PermissionError):
        reopened.assert_open()
    with pytest.raises(ValueError):
        reopened.transition(False, "recovered", initial["epoch"])
    reopened.transition(False, "recovered", frozen["epoch"])
    assert reopened.assert_open() > frozen["epoch"]


def test_crashed_task_requires_reconciliation_before_new_execution(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    store.reconcile_startup("old-instance")
    store.task_state("workspace", "task", "running")
    reopened = ControlStore(tmp_path / "control.db")
    state = reopened.reconcile_startup("new-instance")
    assert state["frozen"]
    assert reopened.task_state("workspace", "task")["status"] == "interrupted_unknown"
    with pytest.raises(PermissionError):
        reopened.assert_open()


async def test_external_stop_does_not_claim_remote_completion():
    from qwenpaw.app.task_tracker import TaskTracker

    tracker = TaskTracker()
    await tracker.register_external_task("external-1")
    assert await tracker.request_stop("external-1")
    assert await tracker.has_active_tasks()
    assert (await tracker.get_control_status("external-1"))[
        "status"
    ] == "stop_requested"
    await tracker.unregister_external_task("external-1")
    assert not await tracker.has_active_tasks()


async def test_stop_before_first_step_finishes_stream_and_records_terminal():
    from qwenpaw.app.task_tracker import TaskTracker

    tracker = TaskTracker()

    async def never_started(_):
        pytest.fail("Cancelled work must never begin")
        yield "unreachable"

    queue, _ = await tracker.attach_or_start("queued", None, never_started)
    assert await tracker.request_stop("queued")
    assert await asyncio.wait_for(queue.get(), 1) is None
    assert (await tracker.get_control_status("queued"))["status"] == "cancelled"


async def test_task_status_stays_stopping_until_cleanup_finishes():
    from qwenpaw.app.task_tracker import TaskTracker

    tracker = TaskTracker()
    started, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def stream(_):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup.set()
            await release.wait()
        yield "unused"

    await tracker.attach_or_start("slow-stop", None, stream)
    await started.wait()
    await tracker.request_stop("slow-stop")
    await cleanup.wait()
    assert (await tracker.get_control_status("slow-stop"))["status"] == "stop_requested"
    release.set()
    assert await tracker.wait_all_done(timeout=1)
    assert (await tracker.get_control_status("slow-stop"))["status"] == "cancelled"


async def test_freeze_blocks_real_tool_entry_and_new_tasks(monkeypatch, tmp_path):
    from qwenpaw.extensions.security import execution_control, execution_policy
    from qwenpaw.app.task_tracker import TaskTracker

    store = ControlStore(tmp_path / "control.db")
    monkeypatch.setattr(execution_control, "get_control_store", lambda: store)
    store.transition(True, "incident", 0)
    with pytest.raises(PermissionError):
        await execution_policy.check_tool("get_current_time", {})
    tracker = TaskTracker()
    with pytest.raises(PermissionError):
        await tracker.register_external_task("new")
    assert not await tracker.has_active_tasks()


async def test_heartbeat_waits_for_child_cleanup_before_stop_completes():
    from qwenpaw.runtime.heartbeat import _iter_with_heartbeat

    cleanup, release = asyncio.Event(), asyncio.Event()

    async def source():
        try:
            await asyncio.Event().wait()
        finally:
            cleanup.set()
            await release.wait()
        yield "never"

    stream = _iter_with_heartbeat(source(), 30)
    task = asyncio.create_task(anext(stream))
    await asyncio.sleep(0.01)
    task.cancel()
    await cleanup.wait()
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
