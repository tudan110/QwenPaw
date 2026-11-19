"""Observe tool execution without treating a policy ALLOW or stream as success."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterable, Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


def _outcome(state: str | None) -> str:
    if state == "interrupted":
        return "cancelled"
    if state == "running":
        return "returned"
    return state if state in {"success", "error", "denied", "cancelled"} else "unconfirmed"


async def audit_call(
    execute: Callable[[], Awaitable[Any]],
    record: Callable[[str, str], None],
    terminal_state: Callable[[Any], str | None],
) -> Any:
    """Journal before execution and record at most one observed terminal result."""
    call_id = uuid.uuid4().hex
    record(call_id, "started")  # A failed pre-execution journal prevents execution.

    def finish(status: str) -> None:
        try:
            record(call_id, status)
        except Exception:
            # Preserve the real tool result and avoid an automatic retry of
            # an operation that may already have executed. "started" remains.
            logger.error("Tool outcome could not be persisted: call_id=%s", call_id)

    try:
        result = await execute()
    except asyncio.CancelledError:
        finish("cancelled")
        raise
    except Exception:
        finish("error")
        raise

    if not isinstance(result, AsyncIterable):
        finish(_outcome(terminal_state(result)))
        return result

    async def observe():
        status = "unconfirmed"
        recorded = False
        iterator = aiter(result)
        try:
            async for chunk in iterator:
                state = terminal_state(chunk)
                if state == "running":
                    # AgentScope also uses RUNNING for plain yielded strings.
                    # Only exhaustion proves that this iterator finished.
                    status = "returned"
                elif state is not None and not recorded:
                    # Consumers are allowed to stop iteration at the last chunk.
                    finish(_outcome(state))
                    recorded = True
                yield chunk
        except GeneratorExit:
            status = "unconfirmed"
            raise
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except Exception:
            status = "error"
            raise
        finally:
            if not recorded:
                finish(status)
            close = getattr(iterator, "aclose", None)
            if close is not None:
                await close()

    return observe()
