"""Durable-outbox forwarding to an explicitly configured HTTPS collector.

The collector must commit to independently protected retention before replying
with event_id and the SHA-256 of the exact submitted payload. HTTP success
alone is not an archive acknowledgement. Local code cannot certify a remote
collector's retention lock or operator separation.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from urllib.parse import urlsplit

import httpx

from ..constant import EnvVarLoader
from .audit import AuditLog

logger = logging.getLogger(__name__)


async def forward_once(log: AuditLog, client: httpx.AsyncClient, url: str) -> int:
    target = urlsplit(url)
    if (
        target.scheme != "https"
        or not target.hostname
        or target.username
        or target.password
        or target.query
        or target.fragment
    ):
        raise ValueError(
            "Audit collector requires an exact HTTPS URL without credentials/query"
        )
    token = EnvVarLoader.get_str("QWENPAW_AUDIT_ARCHIVE_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    count = 0
    for item in log.pending_archive():
        payload = item["payload"].encode()
        digest = hashlib.sha256(payload).hexdigest()
        response = await client.post(
            url,
            content=payload,
            headers={
                **headers,
                "Idempotency-Key": item["event_id"],
                "X-Content-SHA256": digest,
            },
            follow_redirects=False,
        )
        response.raise_for_status()
        receipt = response.json()
        if (
            receipt.get("event_id") != item["event_id"]
            or receipt.get("sha256") != digest
        ):
            raise ValueError("Collector did not acknowledge the exact durable event")
        log.acknowledge_archive(item["event_id"])
        count += 1
    return count


async def run_forwarder():
    url = EnvVarLoader.get_str("QWENPAW_AUDIT_ARCHIVE_URL", "")
    if not url:
        logger.warning("Audit collector not configured; durable local queue retained")
        return
    from ..extensions.security.egress_policy import controlled_async_client

    async with controlled_async_client(
        control_exempt=True, timeout=15, trust_env=False, follow_redirects=False
    ) as client:
        while True:
            try:
                log = AuditLog.get_instance()
                await forward_once(log, client, url)
                status = log.archive_status()
                if status["pending"]:
                    logger.warning("Audit archive backlog: %d", status["pending"])
            except asyncio.CancelledError:
                raise
            except Exception:
                # URLs, credentials and exception bodies are not log content.
                logger.error("Audit archive unavailable; queued evidence retained")
            await asyncio.sleep(15)
