"""Production policy and adapter approval binding without business writes."""

import asyncio
import hashlib
import json
import shlex
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from agentscope.message import TextBlock, ToolResultState
from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.tool import ToolChunk
from fastapi import HTTPException
import pytest

from qwenpaw.agents.tools.file_io import write_file
from qwenpaw.extensions.api.access_session import (
    AccessIdentity,
    CURRENT_IDENTITY,
)
from qwenpaw.extensions.security import execution_policy
from qwenpaw.governance import tool_adapter


@pytest.fixture
def approval(monkeypatch, tmp_path):
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    from qwenpaw.config import runtime_boundary_policy

    monkeypatch.setattr(runtime_boundary_policy, "policy_path", lambda: tmp_path / "boundary-policy.json")
    monkeypatch.delenv("QWENPAW_CONTROLLED_WORKSPACE_FILES", raising=False)
    monkeypatch.delenv("COPAW_CONTROLLED_WORKSPACE_FILES", raising=False)
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "1")
    monkeypatch.delenv("QWENPAW_READONLY_TOOL_NAMES", raising=False)
    monkeypatch.setattr(execution_policy, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(execution_policy, "SECRET_DIR", tmp_path / "secrets")
    monkeypatch.setattr(execution_policy, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(
        execution_policy, "get_current_workspace_dir", lambda: tmp_path
    )
    script = (
        tmp_path / "skills/zgops-cmdb-import/scripts/resource_import_bridge.py"
    )
    script.parent.mkdir(parents=True)
    script.write_text("# Integrity fixture; never executed.\n")
    monkeypatch.setenv(
        "QWENPAW_ALLOWED_SCRIPT_HASHES",
        json.dumps(
            {str(script): hashlib.sha256(script.read_bytes()).hexdigest()}
        ),
    )
    context = tmp_path / "import.json"
    context.write_text('{"files": [], "marker": "reviewed"}')
    params = {
        "command": shlex.join(
            ["python3", str(script), "import", "--context-file", str(context)]
        ),
        "cwd": str(tmp_path),
    }
    identity = AccessIdentity(
        user={"userId": 1},
        inoe_token="fixture-upstream-token",
        access_token="fixture-local-token",
    )
    identity_token = CURRENT_IDENTITY.set(identity)
    store = SimpleNamespace(resolve=Mock())
    monkeypatch.setattr(execution_policy, "get_access_store", lambda: store)
    validate = AsyncMock(return_value={"userId": 1})
    monkeypatch.setattr(execution_policy, "_validate_inoe_token", validate)
    monkeypatch.setattr(
        execution_policy.sso_settings_store,
        "get_userinfo_url",
        lambda: "http://fixture.invalid/userinfo",
    )
    executing = []

    async def execute_shell_command(command: str, cwd: str) -> ToolChunk:
        """Record invocation without running a shell or changing resources."""
        executing.append((command, cwd))
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[TextBlock(text="executed")],
        )

    governor = SimpleNamespace(
        workspace_dir=tmp_path,
        policy=SimpleNamespace(execution_level="off"),
        assert_policy=Mock(),
        audit=Mock(),
        audit_log=SimpleNamespace(record_execution=Mock()),
    )
    tool = tool_adapter.PolicyGuardedTool(
        execute_shell_command,
        governor=governor,
        request_context={
            "approval_level": "off",
            "agent_id": "gateway",
            "session_id": "approval-fixture",
        },
    )
    waiting = asyncio.Event()
    respond = asyncio.Event()
    requests = []

    async def ask(**kwargs):
        requests.append(kwargs)
        waiting.set()
        await respond.wait()
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW, message="fixture approved"
        )

    real_ask = tool_adapter._ask_user_approval
    monkeypatch.setattr(tool_adapter, "_ask_user_approval", ask)
    yield SimpleNamespace(
        real_ask=real_ask,
        tool=tool,
        params=params,
        context=context,
        executing=executing,
        waiting=waiting,
        respond=respond,
        requests=requests,
        governor=governor,
        store=store,
        validate=validate,
    )
    CURRENT_IDENTITY.reset(identity_token)


async def _start_approval(approval):
    task = asyncio.create_task(
        approval.tool.check_permissions(approval.params)
    )
    await asyncio.wait_for(approval.waiting.wait(), timeout=2)
    return task


async def _approve(approval):
    task = await _start_approval(approval)
    approval.respond.set()
    result = await task
    assert result.behavior == PermissionBehavior.ALLOW


async def test_mandatory_admin_approval_ignores_disabled_approval_level(
    approval,
):
    task = await _start_approval(approval)
    assert not task.done()
    assert approval.executing == []
    assert len(approval.requests) == 1
    request = approval.requests[0]
    assert request["source"] == "production_boundary"
    assert request["tc_spec"].target == approval.params["command"]
    assert request["tc_spec"].raw_params == approval.params
    assert str(approval.context) in request["governance_reason"]
    assert hashlib.sha256(approval.context.read_bytes()).hexdigest() in (
        request["governance_reason"]
    )
    approval.governor.assert_policy.assert_not_called()

    approval.respond.set()
    assert (await task).behavior == PermissionBehavior.ALLOW
    assert approval.executing == []


async def test_approved_import_executes_once_and_replay_is_denied(approval):
    await _approve(approval)
    result = await approval.tool(**approval.params)
    assert result.state == ToolResultState.SUCCESS
    assert approval.executing == [
        (approval.params["command"], approval.params["cwd"])
    ]
    with pytest.raises(PermissionError, match="已审批"):
        await approval.tool(**approval.params)
    assert len(approval.executing) == 1
    assert approval.validate.await_count == 3


async def test_approved_import_clears_previous_read_sandbox(approval):
    # A reused tool can retain fallback state from an earlier read. Its
    # read-only mount configuration must not leak into this approved import.
    approval.tool._qp_sandbox_mode = True
    approval.tool._qp_sandbox_config = object()

    await _approve(approval)
    assert approval.tool._qp_sandbox_mode is False
    assert approval.tool._qp_sandbox_config is None
    # The fixture function intentionally accepts only command/cwd. Injecting
    # the stale sandbox_config would raise TypeError instead of executing.
    result = await approval.tool(**approval.params)
    assert result.state == ToolResultState.SUCCESS
    assert len(approval.executing) == 1


async def test_json_changed_during_approval_invalidates_execution(approval):
    task = await _start_approval(approval)
    approval.context.write_text('{"files": [], "marker": "changed"}')
    approval.respond.set()
    assert (await task).behavior == PermissionBehavior.ALLOW

    with pytest.raises(PermissionError, match="输入文件内容"):
        await approval.tool(**approval.params)
    assert approval.executing == []
    assert approval.tool._qp_p0_approved_params is None


async def test_parameters_changed_while_waiting_invalidate_execution(approval):
    task = await _start_approval(approval)
    # The same caller-owned dict is retained by the displayed ToolCallSpec.
    # Approval must hold a deep copy, rather than accepting this mutation.
    approval.params["timeout"] = 30
    approval.respond.set()
    assert (await task).behavior == PermissionBehavior.ALLOW

    with pytest.raises(PermissionError, match="执行参数"):
        await approval.tool(**approval.params)
    assert approval.executing == []


async def test_local_expiry_before_execution_denies_approved_call(
    approval,
):
    await _approve(approval)
    approval.store.resolve.side_effect = HTTPException(401, "session expired")

    with pytest.raises(HTTPException) as raised:
        await approval.tool(**approval.params)
    assert raised.value.status_code == 401
    assert approval.store.resolve.call_count == 2
    assert approval.validate.await_count == 1
    assert approval.executing == []


async def test_upstream_auth_expiry_before_execution_denies_approved_call(
    approval,
):
    await _approve(approval)
    approval.validate.side_effect = HTTPException(401, "upstream expired")

    with pytest.raises(HTTPException) as raised:
        await approval.tool(**approval.params)
    assert raised.value.status_code == 401
    assert approval.validate.await_count == 2
    assert approval.executing == []


@pytest.mark.parametrize("inline_flag", [False, True])
async def test_changed_import_attachment_invalidates_approval(
    approval, tmp_path, inline_flag
):
    attachment = tmp_path / "resources.xlsx"
    attachment.write_bytes(b"reviewed fixture workbook")
    approval.context.write_text(
        json.dumps({"files": [{"path": str(attachment)}]})
    )
    if inline_flag:
        args = shlex.split(approval.params["command"])
        index = args.index("--context-file")
        args.pop(index + 1)
        args[index] = f"--context-file={approval.context}"
        approval.params["command"] = shlex.join(args)
    await _approve(approval)
    attachment.write_bytes(b"changed fixture workbook")

    with pytest.raises(PermissionError, match="输入文件内容"):
        await approval.tool(**approval.params)
    assert approval.executing == []


async def test_ordinary_user_cannot_request_import_approval(approval):
    token = CURRENT_IDENTITY.set(
        AccessIdentity(user={"userId": 2}, inoe_token="fixture")
    )
    try:
        result = await approval.tool.check_permissions(approval.params)
    finally:
        CURRENT_IDENTITY.reset(token)

    assert result.behavior == PermissionBehavior.DENY
    assert approval.requests == []
    assert approval.executing == []


@pytest.fixture
def legacy_shell(approval, tmp_path, monkeypatch):
    # Exercise the POSIX admission path without mutating the shared sys module.
    monkeypatch.setattr(execution_policy, "sys", SimpleNamespace(platform="linux"))
    skill = tmp_path / "skills/zgops-cmdb-import"
    command = "cd skills/zgops-cmdb-import && " + shlex.join([
        "python3", "scripts/resource_import_bridge.py", "import",
        "--context-file", str(approval.context),
    ])
    approval.params.update(command=command, cwd=str(tmp_path))
    return approval, skill


async def test_legacy_shell_dispatches_only_normalized_approved_command(legacy_shell):
    approval, skill = legacy_shell
    # Direct execution must still require approval.
    with pytest.raises(PermissionError, match="审批"):
        await approval.tool(**approval.params)
    assert approval.executing == []
    await _approve(approval)
    result = await approval.tool(**approval.params)
    assert result.state == ToolResultState.SUCCESS
    [(command, cwd)] = approval.executing
    assert shlex.split(command) == [
        "python3", "scripts/resource_import_bridge.py", "import",
        "--context-file", str(approval.context),
    ]
    assert Path(cwd) == skill
    assert approval.requests[0]["tc_spec"].raw_params == {"cwd": cwd, "command": command}


@pytest.mark.parametrize("case", ["pipe", "extra_command", "outside", "modified_script", "ordinary_user"])
async def test_legacy_shell_rejection_never_dispatches_or_requests_approval(legacy_shell, case):
    approval, skill = legacy_shell
    identity_token = None
    if case == "pipe":
        approval.params["command"] += " | cat"
    elif case == "extra_command":
        approval.params["command"] += " && echo extra"
    elif case == "outside":
        approval.params["command"] = approval.params["command"].replace(
            "cd skills/zgops-cmdb-import", "cd ..",
        )
    elif case == "modified_script":
        (skill / "scripts/resource_import_bridge.py").write_text("# modified fixture\n")
    else:
        identity_token = CURRENT_IDENTITY.set(
            AccessIdentity(user={"userId": 2}, inoe_token="fixture"),
        )
    try:
        decision = await approval.tool.check_permissions(approval.params)
        assert decision.behavior == PermissionBehavior.DENY
        with pytest.raises(PermissionError):
            await approval.tool(**approval.params)
    finally:
        if identity_token is not None:
            CURRENT_IDENTITY.reset(identity_token)
    assert approval.executing == []
    assert approval.requests == []


@pytest.fixture
def ordinary_web(approval):
    token = CURRENT_IDENTITY.set(
        AccessIdentity(user={"userId": 2}, inoe_token="fixture")
    )
    yield approval
    CURRENT_IDENTITY.reset(token)


_WEB_ID_KEYS = (
    "--monitor-id",
    "--run-id",
    "monitor_id",
    "run_id",
    "monitorId",
    "runId",
)


@pytest.mark.parametrize("key", _WEB_ID_KEYS)
@pytest.mark.parametrize(
    "value",
    [
        "../dashboard",
        "..%2fadmin",
        "run?delete=1",
        "run#fragment",
        "monitor\\runs",
        "monitor\n",
    ],
)
async def test_web_mcp_read_rejects_path_and_query_injection(
    ordinary_web, key, value
):
    with pytest.raises(PermissionError, match="ID 格式"):
        await execution_policy.check_tool(
            "web-check-app__getMonitor", {key: value}
        )
    ordinary_web.validate.assert_not_awaited()


@pytest.mark.parametrize("key", _WEB_ID_KEYS)
async def test_web_mcp_read_accepts_opaque_id_aliases(ordinary_web, key):
    assert (
        await execution_policy.check_tool(
            "web-check-app__getMonitor", {key: "monitor_42-uuid"}
        )
        is False
    )
    ordinary_web.validate.assert_not_awaited()


async def test_web_mcp_list_without_id_remains_readable(ordinary_web):
    assert (
        await execution_policy.check_tool("web-check-app__listMonitors", {})
        is False
    )
    ordinary_web.validate.assert_not_awaited()


@pytest.mark.parametrize("filename", ["tmp.txt", "tmp.md"])
async def test_create_empty_file_defaults_to_normal_flow(approval, tmp_path, filename):
    from qwenpaw.governance.policy import load_governance_policy

    approval.governor.policy = load_governance_policy(str(tmp_path), str(tmp_path))
    approval.governor.assert_policy = approval.governor.policy.evaluate
    tool = tool_adapter.PolicyGuardedTool(
        write_file, governor=approval.governor,
        request_context={"approval_level": "auto"},
    )
    params = {"file_path": filename, "content": ""}
    assert not execution_policy.workspace_file_approval_enabled()
    approval.respond.set()  # Fail the no-approval assertion rather than hang on regression.
    assert (await tool.check_permissions(params)).behavior == PermissionBehavior.ALLOW
    assert (await tool(**params)).state == ToolResultState.SUCCESS
    assert (tmp_path / filename).read_bytes() == b""
    assert not approval.requests
    approval.validate.assert_not_awaited()


@pytest.mark.parametrize("filename", ["tmp.txt", "tmp.md"])
async def test_create_empty_file_uses_existing_approval(approval, tmp_path, monkeypatch, filename):
    monkeypatch.setenv("QWENPAW_CONTROLLED_WORKSPACE_FILES", "true")
    approval.tool = tool_adapter.PolicyGuardedTool(
        write_file, governor=approval.governor,
        request_context={"approval_level": "off", "agent_id": "gateway", "session_id": "empty-file"},
    )
    approval.params = {"file_path": filename, "content": ""}
    target = tmp_path / filename
    assert (await write_file(**approval.params)).state == ToolResultState.ERROR
    with pytest.raises(PermissionError, match="已审批"):
        await approval.tool(**approval.params)
    task = await _start_approval(approval)
    assert not target.exists()
    assert approval.requests[0]["source"] == "production_boundary"
    assert "不覆盖" in approval.requests[0]["governance_reason"]
    approval.respond.set()
    assert (await task).behavior == PermissionBehavior.ALLOW
    assert (await approval.tool(**approval.params)).state == ToolResultState.SUCCESS
    assert target.read_bytes() == b""
    target.write_text("existing content")
    with pytest.raises(PermissionError, match="不允许覆盖"):
        await approval.tool(**approval.params)
    assert target.read_text() == "existing content"


async def test_file_created_while_approval_pending_cannot_be_overwritten(approval, tmp_path, monkeypatch):
    monkeypatch.setenv("QWENPAW_CONTROLLED_WORKSPACE_FILES", "true")
    from qwenpaw.agents.tools.file_io import _create_empty_file

    approval.tool = tool_adapter.PolicyGuardedTool(
        write_file, governor=approval.governor, request_context={},
    )
    approval.params = {"file_path": "tmp.txt", "content": ""}
    task = await _start_approval(approval)
    target = tmp_path / "tmp.txt"
    target.write_text("existing content")
    approval.respond.set()
    assert (await task).behavior == PermissionBehavior.ALLOW
    with pytest.raises(PermissionError, match="不允许覆盖"):
        await approval.tool(**approval.params)
    with pytest.raises(FileExistsError):
        _create_empty_file(target)
    assert target.read_text() == "existing content"


@pytest.mark.parametrize("path, content", [
    ("../tmp.txt", ""), ("subdir/tmp.txt", ""), ("config.py", ""),
    (".env", ""), ("nul.txt", ""), (".hidden.txt", ""),
    ("tmp.txt", "not an empty file"), ("AGENTS.md", ""), ("profile.MD", ""),
])
async def test_file_workflow_does_not_admit_other_writes(approval, path, content):
    with pytest.raises(PermissionError):
        await execution_policy.check_tool("write_file", {"file_path": path, "content": content})
    assert not approval.requests


async def test_registered_custom_script_requires_bound_approval(approval, tmp_path, monkeypatch):
    script = tmp_path / "custom_action.py"
    script.write_bytes(b"# original fixture\n")

    def pin_hash():
        monkeypatch.setenv("QWENPAW_ALLOWED_SCRIPT_HASHES", json.dumps({
            str(script.resolve()): hashlib.sha256(script.read_bytes()).hexdigest(),
        }))

    approval.params = {"command": "python custom_action.py", "cwd": str(tmp_path)}
    with pytest.raises(PermissionError):
        execution_policy.check_shell(**approval.params)
    pin_hash()
    await _approve(approval)
    assert str(script) in approval.requests[0]["governance_reason"]
    assert (await approval.tool(**approval.params)).state == ToolResultState.SUCCESS
    assert len(approval.executing) == 1

    await _approve(approval)
    script.write_bytes(b"# modified fixture\n")
    pin_hash()
    with pytest.raises(PermissionError, match="输入文件内容"):
        await approval.tool(**approval.params)
    assert len(approval.executing) == 1


@pytest.mark.parametrize("mode", ["false", "true"])
async def test_explicit_tool_denial_still_overrides_file_approval(approval, tmp_path, monkeypatch, mode):
    monkeypatch.setenv("QWENPAW_CONTROLLED_WORKSPACE_FILES", mode)
    from qwenpaw.extensions.security import call_admission

    monkeypatch.setattr(call_admission, "WORKING_DIR", tmp_path)
    call_admission.save_rule(
        call_admission.Target("tool", "write_file"), revision=0, decision="deny",
        risk="high", reason="fixture deny", actor="fixture-admin",
    )
    tool = tool_adapter.PolicyGuardedTool(write_file, governor=approval.governor, request_context={})
    result = await tool.check_permissions({"file_path": "tmp.txt", "content": ""})
    assert result.behavior == PermissionBehavior.DENY
    assert not approval.requests
    assert not (tmp_path / "tmp.txt").exists()


async def test_fallback_cannot_run_custom_script_without_approval(approval, tmp_path, monkeypatch):
    from qwenpaw.runtime.tool_guard import GuardedFunctionTool

    script = tmp_path / "custom_action.py"
    script.write_bytes(b"# approval fixture\n")
    monkeypatch.setenv("QWENPAW_ALLOWED_SCRIPT_HASHES", json.dumps({
        str(script): hashlib.sha256(script.read_bytes()).hexdigest(),
    }))

    async def execute_shell_command(command: str, cwd: str) -> ToolChunk:
        pytest.fail("Approval-required scripts must not run in the fallback wrapper")

    tool = GuardedFunctionTool(execute_shell_command)
    params = {"command": "python custom_action.py", "cwd": str(tmp_path)}
    result = await tool.check_permissions(params)
    assert result.behavior == PermissionBehavior.DENY
    assert "审批服务当前不可用" in result.message
    with pytest.raises(PermissionError, match="审批服务当前不可用"):
        await tool(**params)


async def test_fallback_preserves_file_controls(approval, tmp_path, monkeypatch):
    from qwenpaw.runtime.tool_guard import GuardedFunctionTool

    tool = GuardedFunctionTool(write_file)
    monkeypatch.setattr(type(tool), "_resolve_execution_level", lambda self: "bypass")
    params = {"file_path": "normal.md", "content": ""}
    assert (await tool.check_permissions(params)).behavior == PermissionBehavior.ALLOW
    assert (await tool(**params)).state == ToolResultState.SUCCESS
    assert (tmp_path / "normal.md").read_bytes() == b""
    assert (await tool.check_permissions({**params, "file_path": "../skip.txt"})).behavior == PermissionBehavior.DENY
    assert (await tool.check_permissions({**params, "content": "nonempty"})).behavior == PermissionBehavior.DENY

    monkeypatch.setenv("QWENPAW_CONTROLLED_WORKSPACE_FILES", "true")
    params["file_path"] = "controlled.txt"
    decision = await tool.check_permissions(params)
    assert decision.behavior == PermissionBehavior.DENY
    assert "当前审批流程不可用" in decision.message
    with pytest.raises(PermissionError, match="当前审批流程不可用"):
        await tool(**params)
    assert not (tmp_path / "controlled.txt").exists()


@pytest.mark.parametrize("action", ["approve", "deny"])
async def test_controlled_file_approval_visible_to_requesting_admin(approval, tmp_path, monkeypatch, action):
    import httpx
    from fastapi import FastAPI, Request
    from qwenpaw.app import approvals
    from qwenpaw.app.routers import approval as approval_api

    monkeypatch.setenv("QWENPAW_CONTROLLED_WORKSPACE_FILES", "true")
    monkeypatch.setattr(tool_adapter, "_ask_user_approval", approval.real_ask)
    service = approvals.ApprovalService()
    monkeypatch.setattr(approvals, "get_approval_service", lambda: service)
    monkeypatch.setattr(approval_api, "get_approval_service", lambda: service)
    app = FastAPI()
    app.include_router(approval_api.router)
    identity = CURRENT_IDENTITY.get()

    @app.middleware("http")
    async def bind_test_identity(request: Request, call_next):
        request.state.access_identity = SimpleNamespace(
            is_admin=True,
            user_id=identity.user_id if not request.headers.get("X-Other-Admin") else "other",
        )
        return await call_next(request)

    ready = asyncio.Event()
    real_create = service.create_pending

    async def create_pending(**kwargs):
        pending = await real_create(**kwargs)
        ready.set()
        return pending

    monkeypatch.setattr(service, "create_pending", create_pending)
    tool = tool_adapter.PolicyGuardedTool(
        write_file, governor=approval.governor,
        request_context={"agent_id": "gateway", "session_id": "active-chat", "channel": "console"},
    )
    params = {"file_path": "example.md", "content": ""}
    target = tmp_path / "example.md"
    task = asyncio.create_task(tool.check_permissions(params))
    try:
        await asyncio.wait_for(ready.wait(), timeout=2)
        assert not target.exists()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for session, headers in [("another-chat", {}), ("active-chat", {"X-Other-Admin": "yes"})]:
                response = await client.get("/approval/list", params={"session_id": session}, headers=headers)
                assert response.status_code == 200 and response.json()["pending_approvals"] == []
            response = await client.get("/approval/list", params={"session_id": "active-chat"})
            assert response.status_code == 200
            [pending] = response.json()["pending_approvals"]
            assert pending["tool_name"] == "Write"
            assert pending["owner_agent_id"] == "gateway"
            assert pending["tool_source"] == "production_boundary"
            decision = await client.post(f"/approval/{action}", json={
                "request_id": pending["request_id"], "session_id": "active-chat",
            })
            assert decision.status_code == 200
        result = await asyncio.wait_for(task, timeout=2)
        if action == "approve":
            assert result.behavior == PermissionBehavior.ALLOW
            assert (await tool(**params)).state == ToolResultState.SUCCESS
            assert target.read_bytes() == b""
        else:
            assert result.behavior == PermissionBehavior.DENY
            assert "管理员已拒绝本次审批" in result.message
            assert not target.exists()
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
