"""Durable process-wide execution freeze and task control journal.

This records local execution state, never a claim that a remote effect was
rolled back. SQLite errors deny admission. The API requires the existing
trusted administrator identity; tools cannot read or edit this journal.
"""

from __future__ import annotations

import json
import sqlite3
import time
import asyncio
import weakref
from pathlib import Path
from contextlib import contextmanager

_EXECUTIONS: weakref.WeakSet = weakref.WeakSet()


def track_execution(future: asyncio.Future) -> None:
    """Track actual executor futures, including background/channel runs."""
    _EXECUTIONS.add(future)
    future.add_done_callback(_EXECUTIONS.discard)


def cancel_executions() -> int:
    count = 0
    for future in list(_EXECUTIONS):
        if not future.done():
            if not isinstance(future, asyncio.Task) or not future.cancelling():
                future.cancel()
            count += 1
    return count


class ControlStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS execution_control (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    frozen INTEGER NOT NULL, epoch INTEGER NOT NULL,
                    reason TEXT NOT NULL, updated_at REAL NOT NULL
                );
                INSERT OR IGNORE INTO execution_control VALUES(1,0,0,'',0);
                CREATE TABLE IF NOT EXISTS task_control (
                    namespace TEXT NOT NULL, run_key TEXT NOT NULL,
                    status TEXT NOT NULL, updated_at REAL NOT NULL,
                    PRIMARY KEY(namespace,run_key)
                );
                CREATE TABLE IF NOT EXISTS control_history (
                    epoch INTEGER PRIMARY KEY, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS control_instance (
                    id INTEGER PRIMARY KEY CHECK(id=1), instance_id TEXT NOT NULL
                );
            """)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self.path), timeout=5)
        try:
            self.path.chmod(0o600)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA synchronous=FULL")
            with conn:
                yield conn
        finally:
            conn.close()

    def snapshot(self) -> dict:
        with self._connect() as conn:
            return dict(
                conn.execute(
                    "SELECT frozen,epoch,reason,updated_at FROM execution_control WHERE id=1"
                ).fetchone()
            )

    def assert_open(self) -> int:
        try:
            state = self.snapshot()
        except (sqlite3.Error, TypeError, OSError):
            raise PermissionError("执行控制状态不可用，已阻断执行") from None
        if state["frozen"]:
            raise PermissionError("系统处于安全冻结状态，已阻断新执行")
        return state["epoch"]

    def reconcile_startup(self, instance_id: str) -> dict:
        """A new process never silently resumes tasks left active by a crash."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT instance_id FROM control_instance WHERE id=1"
            ).fetchone()
            if previous is None or previous[0] != instance_id:
                interrupted = conn.execute(
                    "SELECT COUNT(*) FROM task_control WHERE status IN ('running','stop_requested')"
                ).fetchone()[0]
                if interrupted:
                    conn.execute(
                        "UPDATE task_control SET status='interrupted_unknown',updated_at=? WHERE status IN ('running','stop_requested')",
                        (time.time(),),
                    )
                    conn.execute(
                        "UPDATE execution_control SET frozen=1,epoch=epoch+1,reason='重启发现未核验任务，请先核验远端结果',updated_at=? WHERE id=1",
                        (time.time(),),
                    )
                    state = dict(
                        conn.execute(
                            "SELECT frozen,epoch,reason,updated_at FROM execution_control WHERE id=1"
                        ).fetchone()
                    )
                    conn.execute(
                        "INSERT INTO control_history VALUES(?,?)",
                        (
                            state["epoch"],
                            json.dumps(
                                {**state, "actor": "startup_reconciliation"},
                                ensure_ascii=False,
                            ),
                        ),
                    )
                conn.execute(
                    "INSERT INTO control_instance VALUES(1,?) ON CONFLICT(id) DO UPDATE SET instance_id=excluded.instance_id",
                    (instance_id,),
                )
        return self.snapshot()

    def transition(
        self, frozen: bool, reason: str, expected_epoch: int, actor: str = ""
    ) -> dict:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "UPDATE execution_control SET frozen=?,epoch=epoch+1,reason=?,updated_at=? WHERE id=1 AND epoch=?",
                (int(frozen), reason, time.time(), expected_epoch),
            )
            if cursor.rowcount != 1:
                raise ValueError("控制版本已变化，请刷新后重试")
            state = dict(
                conn.execute(
                    "SELECT frozen,epoch,reason,updated_at FROM execution_control WHERE id=1"
                ).fetchone()
            )
            conn.execute(
                "INSERT INTO control_history VALUES(?,?)",
                (
                    state["epoch"],
                    json.dumps({**state, "actor": actor}, ensure_ascii=False),
                ),
            )
            return state

    def task_state(
        self, namespace: str, run_key: str, status: str | None = None
    ) -> dict:
        with self._connect() as conn:
            if status:
                conn.execute(
                    "INSERT INTO task_control VALUES(?,?,?,?) ON CONFLICT(namespace,run_key) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at",
                    (namespace, run_key, status, time.time()),
                )
            row = conn.execute(
                "SELECT status,updated_at FROM task_control WHERE namespace=? AND run_key=?",
                (namespace, run_key),
            ).fetchone()
            if not row:
                return {"status": "unknown", "remote_effects": "unknown"}
            result = dict(row)
            # A prior process cannot establish a remote or local terminal
            # state after restart; live trackers override this below.
            result["remote_effects"] = "unknown"
            return result


def get_control_store() -> ControlStore:
    from qwenpaw.constant import WORKING_DIR

    # No open connection or process-only state: each call sees persisted epoch.
    return ControlStore(Path(WORKING_DIR) / "trusted-agent" / "control.db")


def assert_execution_open() -> int:
    try:
        return get_control_store().assert_open()
    except (sqlite3.Error, OSError):
        raise PermissionError("执行控制存储不可用，已阻断执行") from None
