import pytest

from qwenpaw.extensions.security.operation_intent import ApprovalReceipts


def test_receipt_is_bound_to_parameters_actor_and_epoch_and_single_use():
    receipts = ApprovalReceipts()
    receipts.issue("write_file", {"content": "one", "file_path": "a.txt"}, "7", "s", 2)
    with pytest.raises(PermissionError):
        receipts.consume(
            "write_file", {"content": "two", "file_path": "a.txt"}, "7", "s", 2
        )
    with pytest.raises(PermissionError):
        receipts.consume(
            "write_file", {"content": "one", "file_path": "a.txt"}, "8", "s", 2
        )
    receipts.consume(
        "write_file", {"file_path": "a.txt", "content": "one"}, "7", "s", 2
    )
    with pytest.raises(PermissionError):
        receipts.consume(
            "write_file", {"content": "one", "file_path": "a.txt"}, "7", "s", 2
        )


def test_freeze_cycle_and_expiry_invalidate_previous_approval():
    receipts = ApprovalReceipts()
    receipts.issue("write_file", {"content": "one"}, "7", "s", 2)
    with pytest.raises(PermissionError):
        receipts.consume("write_file", {"content": "one"}, "7", "s", 4)
    receipts.issue("write_file", {}, "7", "s", 4, ttl=-1)
    with pytest.raises(PermissionError):
        receipts.consume("write_file", {}, "7", "s", 4)


def test_file_changes_after_review_invalidate_intent(monkeypatch, tmp_path):
    from qwenpaw.config import context
    from qwenpaw.extensions.security.operation_intent import bind_resources

    monkeypatch.setattr(context, "get_current_workspace_dir", lambda: tmp_path)
    path = tmp_path / "report.txt"
    path.write_text("before")
    params = {"file_path": "report.txt", "content": "approved"}
    receipt = ApprovalReceipts()
    receipt.issue("write_file", bind_resources("write_file", params), "7", "s", 0)
    path.write_text("another editor changed this")
    with pytest.raises(PermissionError):
        receipt.consume("write_file", bind_resources("write_file", params), "7", "s", 0)


async def test_expired_pending_cannot_be_approved():
    import asyncio
    import time
    from qwenpaw.app.approvals.service import ApprovalService, PendingApproval
    from qwenpaw.security.tool_guard.approval import ApprovalDecision

    service = ApprovalService()
    pending = PendingApproval(
        "r",
        "s",
        "s",
        "a",
        "7",
        "console",
        "a",
        "Write",
        time.time() - 600,
        asyncio.get_running_loop().create_future(),
    )
    service._pending["r"] = pending
    resolved = await service.resolve_request("r", ApprovalDecision.APPROVED)
    assert resolved.status == "timeout"
    assert pending.future.result() == ApprovalDecision.TIMEOUT


async def test_freeze_invalidation_denies_all_waiting_approvals():
    import asyncio
    import time
    from qwenpaw.app.approvals.service import ApprovalService, PendingApproval
    from qwenpaw.security.tool_guard.approval import ApprovalDecision

    service = ApprovalService()
    pending = PendingApproval(
        "r",
        "s",
        "s",
        "a",
        "7",
        "console",
        "a",
        "Write",
        time.time(),
        asyncio.get_running_loop().create_future(),
    )
    service._pending["r"] = pending
    assert await service.cancel_all_pending() == 1
    assert await service.get_request("r") is None
    assert pending.future.result() == ApprovalDecision.DENIED


async def test_guarded_tool_executes_only_once_after_parameter_bound_approval(
    monkeypatch, tmp_path
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from agentscope.permission import PermissionBehavior, PermissionDecision
    from qwenpaw.extensions.api.access_session import AccessIdentity, CURRENT_IDENTITY
    from qwenpaw.extensions.security import execution_policy
    from qwenpaw.governance import tool_adapter
    from qwenpaw.governance.audit import AuditLog

    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "7")
    monkeypatch.setattr(
        execution_policy, "get_current_workspace_dir", lambda: str(tmp_path)
    )
    monkeypatch.setattr(
        execution_policy,
        "_validate_inoe_token",
        AsyncMock(return_value={"code": 200, "user": {"userId": 7}}),
    )
    monkeypatch.setattr(
        tool_adapter,
        "_ask_user_approval",
        AsyncMock(
            return_value=PermissionDecision(
                behavior=PermissionBehavior.ALLOW, message="approved"
            )
        ),
    )
    calls = []

    async def write_file(file_path: str, content: str):
        """Write a controlled report."""
        calls.append((file_path, content))
        return "written"

    log = AuditLog._create(tmp_path / "audit.db")
    governor = SimpleNamespace(
        workspace_dir=tmp_path, audit_log=log, policy=SimpleNamespace()
    )
    tool = tool_adapter.PolicyGuardedTool(
        write_file, governor=governor, request_context={"session_id": "s"}
    )
    token = CURRENT_IDENTITY.set(
        AccessIdentity(user={"userId": 7}, inoe_token="fixture")
    )
    try:
        decision = await tool.check_permissions(
            {"file_path": "report.txt", "content": "one"}
        )
        assert decision.behavior == PermissionBehavior.ALLOW
        with pytest.raises(PermissionError):
            await tool(file_path="report.txt", content="changed")
        assert not calls
        await tool(file_path="report.txt", content="one")
        with pytest.raises(PermissionError):
            await tool(file_path="report.txt", content="one")
        assert calls == [("report.txt", "one")]
        assert log.query()[1] == 2  # start + actual result
    finally:
        CURRENT_IDENTITY.reset(token)
        log.close()
