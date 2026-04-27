"""Lifecycle for the knowledge_kb subsystem.

Owns startup (init_db, reap orphan jobs, import builtin packs) and is wired
into qwenpaw.app._app via a startup hook so the KB is ready before the first
request lands.
"""

from __future__ import annotations

import logging

from . import core

logger = logging.getLogger(__name__)


_started = False


def startup() -> None:
    """Idempotent startup: init schema, reap orphan jobs, import builtins."""
    global _started  # pylint: disable=global-statement
    if _started:
        return
    try:
        # Touch directories so they exist before any handler hits the disk.
        core.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        core.BUILTIN_KB_DIR.mkdir(parents=True, exist_ok=True)

        core.init_db()
        reaped = core.reap_orphan_jobs()
        if reaped > 0:
            logger.info(
                "knowledge_kb: reaped %d orphan ingestion job(s)",
                reaped,
            )
        result = core.import_enabled_builtin_packs(force=False)
        logger.info(
            "knowledge_kb: ready (db=%s, builtin_pack_result=%s)",
            core.DB_PATH,
            result,
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("knowledge_kb: startup failed: %s", exc)
        # Do not raise — KB failure shouldn't take down qwenpaw.
        return
    _started = True


def shutdown() -> None:
    """Currently a no-op (per-request SQLite connections close themselves)."""
