# -*- coding: utf-8 -*-
"""Task tracker for background runs: streaming, reconnect, multi-subscriber.

For internal streaming runs, ``run_key`` is typically ``ChatSpec.id``
(chat_id). For externally-managed tasks (registered via
:meth:`TaskTracker.register_external_task`), ``run_key`` is an opaque
identifier chosen by the caller (e.g. a UUID prefixed with ``"ext-"``).
Per run: task, queues, event buffer. Reconnects get buffer replay + new
events. Cleanup when task completes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import weakref
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)

_SENTINEL = None


@dataclass
class _RunState:
    """Per-run state (task, queues, buffer), guarded by tracker lock."""

    task: asyncio.Future
    queues: list[asyncio.Queue] = field(default_factory=list)
    buffer: list[str] = field(default_factory=list)
    start_time: Optional[datetime] = None
    finish_time: Optional[datetime] = None
    stop_requested: bool = False
    outcome: str = "completed"


class TaskTracker:
    """Per-workspace tracker: run_key -> RunState.

    All mutations to _runs under _lock. Producer broadcasts under lock.
    Subscribers use unbounded per-connection queues; disconnect removes them
    via :meth:`detach_subscriber`.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._runs: dict[str, _RunState] = {}
        self._global_last_run_at: Optional[datetime] = None
        self._global_last_finish_at: Optional[datetime] = None

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    async def get_status(self, run_key: str) -> str:
        """Return ``'idle'`` or ``'running'``."""
        async with self._lock:
            state = self._runs.get(run_key)
        if state is None or state.task.done():
            return "idle"
        return "running"

    async def get_global_status(self) -> dict:
        """Get global agent status summary.

        Returns:
            dict with keys:
                - status: 'idle' | 'running'
                - running_task_count: int
                - last_run_at: Optional[datetime]
                - last_finish_at: Optional[datetime]
        """
        async with self._lock:
            running_count = sum(
                1 for state in self._runs.values() if not state.task.done()
            )
            status = "running" if running_count > 0 else "idle"

            return {
                "status": status,
                "running_task_count": running_count,
                "last_run_at": self._global_last_run_at,
                "last_finish_at": self._global_last_finish_at,
            }

    async def has_active_tasks(self) -> bool:
        """Check if any tasks are currently running.

        Returns:
            bool: True if any tasks are active, False otherwise
        """
        async with self._lock:
            for state in self._runs.values():
                if not state.task.done():
                    return True
            return False

    async def list_active_tasks(self) -> list[str]:
        """List all currently running task keys.

        Returns:
            list[str]: List of active run_keys
        """
        async with self._lock:
            return [
                run_key
                for run_key, state in self._runs.items()
                if not state.task.done()
            ]

    async def wait_all_done(self, timeout: float = 300.0) -> bool:
        """Wait for all active tasks to complete.

        Args:
            timeout: Maximum time to wait in seconds (default: 300s = 5min)

        Returns:
            bool: True if all tasks completed, False if timeout occurred
        """

        async def _wait_loop() -> None:
            while await self.has_active_tasks():
                await asyncio.sleep(0.5)

        try:
            await asyncio.wait_for(_wait_loop(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def register_external_task(self, run_key: str) -> None:
        """Register an externally-managed task so it is visible to
        :meth:`has_active_tasks` and :meth:`wait_all_done`.

        This is used for tasks managed outside of QwenPaw's own streaming
        pipeline (e.g. background tasks dispatched through a third-party
        scheduler).  The caller **must** call
        :meth:`unregister_external_task` when the task completes.

        Args:
            run_key: Unique identifier for the external task.
        """
        start_time = datetime.now(timezone.utc)
        async with self._lock:
            if run_key in self._runs and not self._runs[run_key].task.done():
                logger.debug(
                    "External task already registered: %s",
                    run_key,
                )
                return
            # Use an unresolved Future as the "task" — it stays not-done
            # until unregister_external_task resolves it.
            future: asyncio.Future = asyncio.get_running_loop().create_future()
            self._runs[run_key] = _RunState(
                task=future,
                queues=[],
                buffer=[],
                start_time=start_time,
            )
            self._global_last_run_at = start_time
            logger.debug("Registered external task: %s", run_key)

    async def unregister_external_task(self, run_key: str) -> None:
        """Mark an externally-managed task as done and remove it.

        Sends the sentinel value to any subscriber queues so their
        :meth:`stream_from_queue` consumers terminate cleanly instead of
        hanging. Idempotent — safe to call even if *run_key* was never
        registered or was already unregistered.

        Args:
            run_key: Unique identifier previously passed to
                :meth:`register_external_task`.
        """
        finish_time = datetime.now(timezone.utc)
        async with self._lock:
            state = self._runs.pop(run_key, None)
            if state is None:
                return
            # Notify any subscriber queues so consumers exit cleanly.
            for q in state.queues:
                q.put_nowait(_SENTINEL)
            if not state.task.done():
                state.task.set_result(None)
            state.finish_time = finish_time
            self._global_last_finish_at = finish_time
            logger.debug("Unregistered external task: %s", run_key)

    async def attach(self, run_key: str) -> asyncio.Queue | None:
        """Attach to an existing run.

        Returns a new queue pre-filled with the event buffer, or ``None``
        if no run is active for *run_key*.
        """
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None or state.task.done():
                return None
            q: asyncio.Queue = asyncio.Queue()
            for sse in state.buffer:
                q.put_nowait(sse)
            state.queues.append(q)
            return q

    async def detach_subscriber(
        self,
        run_key: str,
        queue: asyncio.Queue,
    ) -> None:
        """Remove *queue* from *run_key*'s subscriber list.

        Idempotent if the run ended or *queue* was already removed.
        """
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None:
                return
            try:
                state.queues.remove(queue)
            except ValueError:
                pass

    async def _request_cancellation(self, run_key: str) -> _RunState | None:
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None or state.task.done():
                return None
            # An external placeholder isn't a handle to the actual job.
            if not isinstance(state.task, asyncio.Task):
                return None
            if not state.stop_requested:
                state.stop_requested = state.task.cancel()
            return state if state.stop_requested else None

    async def request_stop(self, run_key: str) -> bool:
        """Preserve the legacy acknowledgement of local cancellation requests."""
        return await self._request_cancellation(run_key) is not None

    async def stop_run(self, run_key: str, timeout: float = 1.0) -> str:
        """Observe the exact local run, bounded by the control response budget."""
        state = await self._request_cancellation(run_key)
        if state is None:
            return "not_running"
        _, pending = await asyncio.wait({state.task}, timeout=timeout)
        if pending:
            return "accepted"
        if state.task.cancelled():
            return "cancelled"
        return state.outcome

    async def attach_or_start(
        self,
        run_key: str,
        payload: Any,
        stream_fn: Callable[..., Coroutine],
        *,
        join_existing: bool = True,
    ) -> tuple[asyncio.Queue | None, bool]:
        """Attach to an existing run or start a new one.

        Returns ``(queue, is_new_run)``; the queue is None when busy and
        the caller opted out of joining the existing run.
        """
        async with self._lock:
            state = self._runs.get(run_key)
            if state is not None and not state.task.done():
                if not join_existing:
                    return None, False
                q: asyncio.Queue = asyncio.Queue()
                for sse in state.buffer:
                    q.put_nowait(sse)
                state.queues.append(q)
                return q, False

            my_queue: asyncio.Queue = asyncio.Queue()
            run = _RunState(
                task=asyncio.Future(),  # placeholder, replaced below
                queues=[my_queue],
                buffer=[],
            )
            self._runs[run_key] = run

            tracker_ref = weakref.ref(self)

            async def _producer() -> None:
                start_time = datetime.now(timezone.utc)

                try:
                    tracker = tracker_ref()
                    if tracker is not None:
                        async with tracker.lock:
                            run.start_time = start_time
                            # pylint: disable=protected-access
                            tracker._global_last_run_at = start_time

                    async with aclosing(stream_fn(payload)) as stream:
                        async for sse in stream:
                            tracker = tracker_ref()
                            if tracker is None:
                                return
                            async with tracker.lock:
                                run.buffer.append(sse)
                                for q in run.queues:
                                    q.put_nowait(sse)
                except asyncio.CancelledError:
                    run.outcome = "cancelled"
                    logger.debug("run cancelled run_key=%s", run_key)
                except Exception:
                    run.outcome = "failed"
                    logger.exception("run error run_key=%s", run_key)
                    err_sse = (
                        "data: "
                        f"{json.dumps({'error': 'internal server error'})}\n\n"
                    )
                    tracker = tracker_ref()
                    if tracker is not None:
                        async with tracker.lock:
                            run.buffer.append(err_sse)
                            for q in run.queues:
                                q.put_nowait(err_sse)
                finally:
                    finish_time = datetime.now(timezone.utc)
                    tracker = tracker_ref()
                    if tracker is not None:
                        async with tracker.lock:
                            run.finish_time = finish_time
                            # pylint: disable=protected-access
                            tracker._global_last_finish_at = finish_time
                            for q in run.queues:
                                q.put_nowait(_SENTINEL)
                            # pylint: disable=protected-access
                            if tracker._runs.get(run_key) is run:
                                tracker._runs.pop(run_key, None)

            run.task = asyncio.create_task(_producer())

            def finish_unstarted(task: asyncio.Task) -> None:
                # If cancelled before the first step, _producer never gets a
                # chance to close the queue. Don't touch a later run's state.
                tracker = tracker_ref()
                if tracker is None or not task.cancelled() or run.finish_time:
                    return

                async def cleanup() -> None:
                    async with tracker.lock:
                        run.finish_time = datetime.now(timezone.utc)
                        tracker._global_last_finish_at = run.finish_time
                        for queue in run.queues:
                            queue.put_nowait(_SENTINEL)
                        if tracker._runs.get(run_key) is run:
                            tracker._runs.pop(run_key, None)

                asyncio.create_task(cleanup())

            run.task.add_done_callback(finish_unstarted)
            return my_queue, True

    async def stream_from_queue(
        self,
        queue: asyncio.Queue,
        run_key: str,
    ) -> AsyncGenerator[str, None]:
        """Yield SSE strings from *queue* until the sentinel ``None``.

        Always detaches *queue* from *run_key* when this stream ends or is
        closed (including client disconnect), so reconnects do not leak queues.
        """
        try:
            while True:
                try:
                    event = await queue.get()
                    if event is _SENTINEL:
                        break
                    yield event
                except asyncio.CancelledError:
                    break
        finally:
            await self.detach_subscriber(run_key, queue)
