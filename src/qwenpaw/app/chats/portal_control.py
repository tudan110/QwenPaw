"""Admission and emergency cancellation for one QwenPaw backend process."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from weakref import WeakSet

from ..task_tracker import TaskTracker, _RunState
from .session import _atomic_write_json


class PortalChatsPaused(Exception):
    """An administrator has paused new Portal chat executions."""


class PortalChatStopPending(Exception):
    """One or more local cancellations have not settled yet."""


class PortalChatControl:
    """Coordinate starts and stops across workspaces in this process.

    Keep the freeze and the latest batch's status on the persistent volume.
    Local cancellation handles and open browsers are not shared across processes.
    """

    def __init__(self, path: Path, timeout_seconds: float) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self._lock = asyncio.Lock()
        self._trackers: WeakSet[TaskTracker] = WeakSet()
        self._pending: dict[tuple[int, str], _RunState] = {}
        self._state: dict | None = None

    def _read(self) -> dict:
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"paused": False, "last_stop": None}
        if not isinstance(state, dict) or not isinstance(state.get("paused"), bool):
            raise ValueError("Invalid Portal chat control state")
        return state

    async def _load(self) -> dict:
        if self._state is None:
            self._state = await asyncio.to_thread(self._read)
        return self._state

    async def _save(self, state: dict) -> None:
        await asyncio.to_thread(_atomic_write_json, str(self.path), state)
        self._state = state

    async def start(self, tracker: TaskTracker, key, payload, stream_fn, **kwargs):
        async with self._lock:
            if (await self._load())["paused"]:
                raise PortalChatsPaused
            self._trackers.add(tracker)
            return await tracker.attach_or_start(
                key, payload, stream_fn, portal_timeout=self.timeout_seconds, **kwargs,
            )

    @staticmethod
    def _public(state: dict, timeout_seconds: float) -> dict:
        last = state["last_stop"]
        summary = None
        if last is not None:
            results = last["tasks"]
            summary = {key: last[key] for key in ("id", "at", "elapsed_ms")}
            summary["total"] = len(results) if results is not None else None
            summary["counts"] = {}
            for entry in results or []:
                key = entry["status"]
                summary["counts"][key] = summary["counts"].get(key, 0) + 1
        return {"paused": state["paused"], "timeout_seconds": timeout_seconds, "last_stop": summary}

    async def _refresh(self, state: dict) -> dict:
        last = state["last_stop"]
        if not last or last["tasks"] is None:
            return state
        tasks = []
        changed = False
        settled = []
        for item in last["tasks"]:
            status = item["status"]
            key = (item["tracker"], item["chat_id"])
            if status == "accepted":
                run = self._pending.get(key)
                # After process restart there is no local handle to confirm
                # how the earlier task ended. Preserve that uncertainty.
                status = run.stop_status() if run else "unknown"
                if status != "accepted":
                    settled.append(key)
                    changed = True
            tasks.append({**item, "status": status})
        if changed:
            state = {**state, "last_stop": {**last, "tasks": tasks}}
            await self._save(state)
            for key in settled:
                self._pending.pop(key, None)
        return state

    async def status(self) -> dict:
        async with self._lock:
            return self._public(await self._refresh(await self._load()), self.timeout_seconds)

    async def stop(self, actor: str) -> dict:
        async with self._lock:
            previous = await self._refresh(await self._load())
            if previous["paused"] and previous["last_stop"] and previous["last_stop"]["tasks"] is not None:
                return self._public(previous, self.timeout_seconds)
            start = time.monotonic()
            last = {
                "id": uuid.uuid4().hex, "at": time.time(), "actor": actor,
                "tasks": None, "elapsed_ms": None,
            }
            # Record the freeze before requesting cancellations. A restart
            # during the batch must not silently reopen chat admission.
            await self._save({"paused": True, "last_stop": last})
            snapshots = await asyncio.gather(*(
                tracker.request_portal_stops() for tracker in list(self._trackers)
            ))
            runs = {
                (index, chat_id): run
                for index, worker in enumerate(snapshots)
                for chat_id, run in worker.items()
            }
            if runs:
                await asyncio.wait({run.task for run in runs.values()}, timeout=1.0)
            tasks = []
            for key, run in runs.items():
                status = run.stop_status()
                tasks.append({"tracker": key[0], "chat_id": key[1], "status": status})
                if status == "accepted":
                    self._pending[key] = run
            result = {"paused": True, "last_stop": {
                **last, "tasks": tasks, "elapsed_ms": round((time.monotonic() - start) * 1000),
            }}
            await self._save(result)
            return self._public(result, self.timeout_seconds)

    async def reopen(self) -> dict:
        async with self._lock:
            state = await self._refresh(await self._load())
            if self._pending:
                raise PortalChatStopPending
            result = {**state, "paused": False}
            await self._save(result)
            return self._public(result, self.timeout_seconds)
