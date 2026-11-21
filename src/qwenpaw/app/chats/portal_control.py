"""Admission and emergency cancellation for one QwenPaw backend process."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from weakref import WeakSet

from ..task_tracker import TaskTracker, _RunState
from .models import ChatUpdate
from .session import EMPTY_RECALLED_CHAT_NAME, _write_session_json, portal_turn_status

logger = logging.getLogger(__name__)

# Keep the latest record plus this many previous batches in the control file.
_HISTORY_LIMIT = 100
INCIDENT_PAGE_SIZE = 15


class PortalChatsPaused(Exception):
    """An administrator has paused new Portal chat executions."""


class PortalChatStopPending(Exception):
    """One or more local cancellations have not settled yet."""


class PortalIncidentReviewRequired(Exception):
    """A risk-triggered freeze is not a maintenance stop."""


class PortalIncidentChanged(Exception):
    """The batch that the administrator reviewed is no longer frozen."""


class PortalRollbackUnavailable(Exception):
    """The requested shutdown batch is not available for rollback."""


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
        await _write_session_json(str(self.path), state)
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
            summary["rollback_total"] = sum("turn_id" in entry for entry in results or [])
            if rollback := last.get("rollback"):
                summary["rollback"] = {"at": rollback["at"], "counts": {}}
                for entry in results or []:
                    if status := entry.get("rollback_status"):
                        counts = summary["rollback"]["counts"]
                        counts[status] = counts.get(status, 0) + 1
        return {"paused": state["paused"], "timeout_seconds": timeout_seconds, "last_stop": summary}

    @classmethod
    def _incident_summary(cls, last: dict) -> dict:
        summary = cls._public({"paused": False, "last_stop": last}, 0)["last_stop"]
        return {
            **summary,
            "reason": last.get("reason", "maintenance"),
            "actor": last.get("actor"),
            "resume": last.get("resume"),
        }

    @staticmethod
    def _run_snapshot(run: _RunState, status: str) -> dict:
        return {
            "status": status,
            "started_at": run.start_time.timestamp() if run.start_time else None,
            "finished_at": run.finish_time.timestamp()
            if status != "accepted" and run.finish_time else None,
            "checkpoint_saved": bool(run.checkpoint)
            if status in {"cancelled", "timeout"} else None,
        }

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
                    if run is not None:
                        item = {**item, **self._run_snapshot(run, status)}
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

    async def _active_count(self) -> int:
        return sum(await asyncio.gather(*(
            tracker.count_active_portal_runs() for tracker in list(self._trackers)
        )))

    @staticmethod
    def _batches(state: dict) -> list[dict]:
        return ([state["last_stop"]] if state["last_stop"] else []) + state.get("history", [])

    async def incidents(self, page: int) -> dict:
        async with self._lock:
            state = await self._refresh(await self._load())
            batches = self._batches(state)
            offset = (page - 1) * INCIDENT_PAGE_SIZE
            return {
                "paused": state["paused"],
                "active_count": await self._active_count(),
                "latest": self._incident_summary(batches[0]) if batches else None,
                "records": [self._incident_summary(batch) for batch in batches[offset:offset + INCIDENT_PAGE_SIZE]],
                "total": len(batches),
                "page_size": INCIDENT_PAGE_SIZE,
                "retention_limit": _HISTORY_LIMIT + 1,
                "queried_at": time.time(),
            }

    async def incident(self, batch_id: str, page: int) -> dict | None:
        async with self._lock:
            state = await self._refresh(await self._load())
            batch = next((item for item in self._batches(state) if item["id"] == batch_id), None)
            if batch is None:
                return None
            tasks = batch["tasks"]
            offset = (page - 1) * INCIDENT_PAGE_SIZE
            # Only correlation identifiers and observed status. Do not copy
            # prompts, responses, tool parameters or saved checkpoint contents.
            fields = ("chat_id", "agent_id", "turn_id", "status", "started_at", "finished_at", "checkpoint_saved")
            return {
                "batch": self._incident_summary(batch),
                "tasks": [
                    {key: item.get(key) for key in fields}
                    for item in (tasks or [])[offset:offset + INCIDENT_PAGE_SIZE]
                ],
                "page_size": INCIDENT_PAGE_SIZE,
            }

    async def stop(self, actor: str, reason: str = "maintenance") -> dict:
        async with self._lock:
            previous = await self._refresh(await self._load())
            if previous["paused"] and previous["last_stop"]:
                if reason != "maintenance" and previous["last_stop"].get("reason") != reason:
                    raise PortalIncidentChanged
                # A retry cannot overwrite an incomplete batch with zero runs.
                return self._public(previous, self.timeout_seconds)
            start = time.monotonic()
            last = {
                "id": uuid.uuid4().hex, "at": time.time(), "actor": actor,
                "reason": reason, "tasks": None, "elapsed_ms": None,
            }
            # Record the freeze before requesting cancellations. A restart
            # during the batch must not silently reopen chat admission.
            frozen = {
                "paused": True, "last_stop": last,
                "history": self._batches(previous)[:_HISTORY_LIMIT],
            }
            await self._save(frozen)
            snapshots = await asyncio.gather(*(
                tracker.request_portal_stops(hold_output=reason != "maintenance")
                for tracker in list(self._trackers)
            ))
            runs = {
                (index, chat_id): run
                for index, worker in enumerate(snapshots)
                for chat_id, run in worker.items()
            }
            if runs:
                await asyncio.wait({run.task for run in runs.values()}, timeout=1.0)
            tasks = []
            pending = {}
            for key, run in runs.items():
                status = run.stop_status()
                entry = {"tracker": key[0], "chat_id": key[1], **self._run_snapshot(run, status)}
                if run.portal_turn:
                    entry.update(agent_id=run.portal_turn[0], turn_id=run.portal_turn[1])
                tasks.append(entry)
                if status == "accepted":
                    pending[key] = run
            result = {**frozen, "last_stop": {
                **last, "tasks": tasks, "elapsed_ms": round((time.monotonic() - start) * 1000),
            }}
            await self._save(result)
            self._pending.update(pending)
            return self._public(result, self.timeout_seconds)

    async def recall(self, workspace, chat, turn_id: str) -> str:
        async with self._lock:
            # Check before stopping: a stale tab must not cancel a newer turn.
            turn = portal_turn_status(await workspace.session.get_session_state_dict(
                chat.session_id, chat.user_id, chat.channel,
            ))
            if not turn or turn["id"] != turn_id:
                return "stale"
            if turn["recalled"]:
                return await self._restore(workspace, chat, turn_id)
            tracker = workspace.task_tracker
            status = await tracker.stop_run(chat.id)
            if status == "accepted" or await tracker.get_status(chat.id) == "running":
                raise PortalChatStopPending
            return await self._restore(workspace, chat, turn_id)

    @staticmethod
    async def _restore(workspace, chat, turn_id: str) -> str:
        status, empty = await workspace.session.recall_portal_turn(chat, turn_id)
        if empty and chat.name != EMPTY_RECALLED_CHAT_NAME:
            # A first turn may also have been copied into the chat title.
            await workspace.chat_manager.patch_chat(chat.id, ChatUpdate(name=EMPTY_RECALLED_CHAT_NAME))
        return status

    async def rollback(self, actor: str, batch_id: str, resolve_target) -> dict:
        async with self._lock:
            state = await self._refresh(await self._load())
            last = state["last_stop"]
            if not state["paused"] or not last or last["id"] != batch_id or not last["tasks"]:
                raise PortalRollbackUnavailable
            if last.get("reason", "maintenance") != "maintenance":
                raise PortalIncidentReviewRequired
            if self._pending:
                raise PortalChatStopPending
            tasks = []
            for item in last["tasks"]:
                if "turn_id" not in item or item.get("rollback_status") in {"recalled", "skipped"}:
                    tasks.append(item)
                    continue
                if item["status"] == "unknown":
                    result = "skipped"
                else:
                    try:
                        target = await resolve_target(item["agent_id"], item["chat_id"])
                        if target is None:
                            result = "skipped"
                        else:
                            workspace, chat = target
                            if await workspace.task_tracker.get_status(chat.id) == "running":
                                result = "failed"
                            else:
                                result = await self._restore(workspace, chat, item["turn_id"])
                                if result == "stale":
                                    result = "skipped"
                    except Exception:
                        logger.exception("Portal chat rollback failed for chat %s", item["chat_id"])
                        result = "failed"
                tasks.append({**item, "rollback_status": result})
            state = {**state, "last_stop": {
                **last, "tasks": tasks, "rollback": {"at": time.time(), "actor": actor},
            }}
            await self._save(state)
            return self._public(state, self.timeout_seconds)

    async def reopen(self, actor: str | None = None, *, reviewed_batch: str | None = None) -> dict:
        async with self._lock:
            state = await self._refresh(await self._load())
            last = state["last_stop"]
            if reviewed_batch is not None and (not state["paused"] or not last or last["id"] != reviewed_batch):
                raise PortalIncidentChanged
            if not state["paused"]:
                return self._public(state, self.timeout_seconds)
            if last and last.get("reason", "maintenance") != "maintenance" and reviewed_batch is None:
                raise PortalIncidentReviewRequired
            if self._pending or await self._active_count():
                raise PortalChatStopPending
            result = {**state, "paused": False}
            if last:
                result["last_stop"] = {**last, "resume": {"at": time.time(), "actor": actor}}
            await self._save(result)
            return self._public(result, self.timeout_seconds)
