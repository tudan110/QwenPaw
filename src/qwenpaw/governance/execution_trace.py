"""Execution ancestry carried only inside trusted request tasks."""

from contextvars import ContextVar

CURRENT_EXECUTION_TRACE: ContextVar[str] = ContextVar(
    "qwenpaw_execution_trace", default=""
)
