import hashlib

import httpx
import pytest

from qwenpaw.governance.audit import AuditLog
from qwenpaw.governance.audit_forwarder import forward_once
from qwenpaw.governance.policy import ToolCallSpec


async def test_only_exact_collector_receipt_acknowledges_event(tmp_path):
    log = AuditLog._create(tmp_path / "audit.db")
    log.execution_event("w", ToolCallSpec("Read", "a", "agent", "session"), "started")

    async def reject_receipt(request):
        return httpx.Response(
            200,
            json={"event_id": request.headers["Idempotency-Key"], "sha256": "wrong"},
        )

    async def accept_receipt(request):
        return httpx.Response(
            200,
            json={
                "event_id": request.headers["Idempotency-Key"],
                "sha256": hashlib.sha256(request.content).hexdigest(),
            },
        )

    try:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(reject_receipt)
        ) as client:
            with pytest.raises(ValueError):
                await forward_once(log, client, "https://audit.example/events")
        assert log.archive_status()["pending"] == 1
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(accept_receipt)
        ) as client:
            assert await forward_once(log, client, "https://audit.example/events") == 1
        assert log.archive_status()["pending"] == 0
    finally:
        log.close()
