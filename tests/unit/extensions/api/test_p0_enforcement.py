# -*- coding: utf-8 -*-
"""High-risk boundaries cannot be disabled by prompts, kwargs or HTTP verbs."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from qwenpaw.extensions.api.access_session import (
    AccessIdentity,
    CURRENT_IDENTITY,
)
from qwenpaw.extensions.api.delete_block_middleware import (
    DeleteBlockMiddleware,
)
from qwenpaw.extensions.security import execution_policy


def test_mcp_empty_or_unknown_transport_cannot_bypass_command_policy(strict):
    from qwenpaw.extensions.security.mcp_boundary import validate_endpoint

    with pytest.raises(PermissionError):
        validate_endpoint(
            {
                "transport": "",
                "url": "http://localhost/sse",
                "command": "npx",
                "args": ["unapproved"],
            }
        )
    with pytest.raises(PermissionError):
        validate_endpoint(
            {"transport": "unknown", "url": "http://localhost/sse"}
        )


def test_backup_root_and_key_files_are_never_readable_by_tools(
    strict, monkeypatch, tmp_path
):
    backup = tmp_path / "working.backups"
    monkeypatch.setattr(execution_policy, "BACKUP_DIR", backup)
    for name in (".signing_key", "restore/.master_key", "export.tar.gz"):
        with pytest.raises(PermissionError):
            execution_policy.check_path(str(backup / name))


def test_nonproduction_approval_keeps_native_single_user_workflow(monkeypatch):
    from qwenpaw.app.routers.approval import _require_approval_owner

    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "false")
    _require_approval_owner(
        SimpleNamespace(state=SimpleNamespace()),
        SimpleNamespace(extra={}),
    )


async def test_mcp_session_endpoints_cannot_change_credential_origin(strict):
    from qwenpaw.drivers.handlers.mcp_stateful_client import HttpStatefulClient
    import httpx

    client = HttpStatefulClient(
        name="fixture", transport="sse", url="http://localhost:8080/sse"
    )
    await client._check_request_origin(
        httpx.Request("POST", "http://localhost:8080/messages")
    )
    with pytest.raises(PermissionError):
        await client._check_request_origin(
            httpx.Request("POST", "https://external.example/messages")
        )


@pytest.fixture
def strict(monkeypatch):
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "7,8")
    reset = CURRENT_IDENTITY.set(None)
    try:
        yield
    finally:
        CURRENT_IDENTITY.reset(reset)


async def test_secret_attachment_is_rejected_before_media_error_fallback(
    strict, monkeypatch, tmp_path
):
    from agentscope.message import Msg, DataBlock
    from agentscope.message._block import URLSource
    from qwenpaw.hooks.request_setup.media_hook import MediaProcessHook

    secret = tmp_path / "working.secret"
    monkeypatch.setattr(execution_policy, "SECRET_DIR", secret)
    message = Msg(
        name="user",
        role="user",
        content=[
            DataBlock(
                source=URLSource(
                    url=(secret / ".master_key").as_uri(),
                    media_type="text/plain",
                ),
                media_type="text/plain",
            )
        ],
    )
    ctx = SimpleNamespace(input_msgs=[message])
    with pytest.raises(PermissionError):
        await MediaProcessHook().run(ctx)


@pytest.mark.parametrize(
    "command",
    [
        "id",
        "curl https://external.example",
        "python -c 'print(1)'",
        "python safe.py | head",
        "python safe.py; id",
        "qwenpaw agents create",
        "/tmp/qwenpaw agents list",
        "qwenpaw agents chat --base-url https://external.example",
        "python get_alarms.py --api_b https://external.example",
    ],
)
def test_arbitrary_shell_is_denied_even_for_admin(strict, command):
    with pytest.raises(PermissionError):
        execution_policy.check_shell(command)


def test_only_integrity_checked_scripts_are_executable(
    strict, tmp_path, monkeypatch
):
    script = tmp_path / "get_alarms.py"
    script.write_text("print('fixture')")
    monkeypatch.setenv(
        "QWENPAW_ALLOWED_SCRIPT_HASHES",
        json.dumps(
            {
                str(script): hashlib.sha256(script.read_bytes()).hexdigest(),
            }
        ),
    )
    execution_policy.check_shell(f"python {script}")
    script.write_text("print('modified')")
    with pytest.raises(PermissionError, match="完整性"):
        execution_policy.check_shell(f"python {script}")
    with pytest.raises(PermissionError):
        execution_policy.check_shell(f"python {script} --token secret")


def test_managed_knowledge_query_is_allowed_but_tampering_and_redirects_are_denied(
    strict,
    tmp_path,
    monkeypatch,
):
    working = tmp_path / "working"
    seed = tmp_path / "seed"
    relative = (
        "workspaces/fault/skills/alarm-analyst/scripts/query_knowledge.py"
    )
    source = (
        Path(__file__).parents[4] / "deploy-all/qwenpaw/working" / relative
    )
    script = working / relative
    script.parent.mkdir(parents=True)
    script.write_bytes(source.read_bytes())
    digest = hashlib.sha256(script.read_bytes()).hexdigest()
    seed.mkdir()
    (seed / "seed-manifest.json").write_text(
        json.dumps(
            {
                "managed_files": {relative: {"sha256": digest}},
                "managed_skills": {
                    "workspaces/fault/skills/alarm-analyst": {
                        "files": {relative: digest}
                    }
                },
            }
        )
    )
    monkeypatch.setattr(execution_policy, "WORKING_DIR", working)
    monkeypatch.setenv("QWENPAW_SKILL_SEED_PATH", str(seed))
    monkeypatch.setenv("QWENPAW_ALLOWED_SCRIPT_HASHES", "{}")
    execution_policy.check_shell(f'python {script} --query "数据库 锁等待"')
    with pytest.raises(PermissionError):
        execution_policy.check_shell(
            f"python {script} --api-base-url https://external.example --query test"
        )
    script.write_text("print('modified')")
    with pytest.raises(PermissionError):
        execution_policy.check_shell(f"python {script} --query test")


async def test_unknown_and_write_tools_require_trusted_admin(strict):
    with pytest.raises(PermissionError):
        await execution_policy.check_tool("delete_resource", {"id": "one"})
    with pytest.raises(PermissionError):
        await execution_policy.check_tool("evil__getDeleteEverything", {})


async def test_readonly_declaration_cannot_override_a_named_write(
    strict, monkeypatch
):
    monkeypatch.setenv("QWENPAW_READONLY_TOOL_NAMES", "delete_resource")
    with pytest.raises(PermissionError):
        await execution_policy.check_tool("delete_resource", {})


async def test_encoded_secret_paths_are_rejected_at_guard_and_file_access(
    strict, monkeypatch, tmp_path
):
    from qwenpaw.agents.tools.file_io import _resolve_file_path

    secret = tmp_path / "working.secret"
    monkeypatch.setattr(execution_policy, "SECRET_DIR", secret)
    encoded = str(tmp_path / "working%2esecret" / "auth.json")
    for tool in ("send_file_to_user", "read_file"):
        with pytest.raises(PermissionError):
            await execution_policy.check_tool(tool, {"file_path": encoded})
    with pytest.raises(PermissionError):
        _resolve_file_path(encoded)
    with pytest.raises(PermissionError):
        await execution_policy.check_tool(
            "read_file", {"file_path": "/proc/self/environ"}
        )


def test_mcp_boundaries_deny_third_party_and_unapproved_processes(
    strict, monkeypatch
):
    from qwenpaw.extensions.security.mcp_boundary import validate_endpoint

    with pytest.raises(PermissionError):
        validate_endpoint(
            {"transport": "sse", "url": "https://third-party.example/sse"}
        )
    with pytest.raises(PermissionError):
        validate_endpoint(
            {"transport": "stdio", "command": "npx", "args": ["unapproved"]}
        )
    validate_endpoint(
        {
            "transport": "sse",
            "url": "http://mcp.namespace.svc.cluster.local/sse",
        }
    )
    monkeypatch.setenv("QWENPAW_MCP_ALLOWED_HOSTS", "higress-gateway")
    validate_endpoint(
        {"transport": "sse", "url": "http://higress-gateway/sse"}
    )


async def test_write_revalidates_before_requesting_approval(
    strict, monkeypatch
):
    identity = AccessIdentity(user={"userId": 7}, inoe_token="fixture-token")
    reset = CURRENT_IDENTITY.set(identity)
    check = AsyncMock(return_value={"code": 200, "user": {"userId": 7}})
    monkeypatch.setattr(execution_policy, "_validate_inoe_token", check)
    try:
        assert (
            await execution_policy.check_tool("delete_resource", {"id": "one"})
            is True
        )
        check.assert_awaited_once()
        check.side_effect = HTTPException(401, "expired")
        with pytest.raises(HTTPException):
            await execution_policy.check_tool("delete_resource", {"id": "one"})
    finally:
        CURRENT_IDENTITY.reset(reset)


async def test_approval_level_off_cannot_bypass_production_write_boundary(
    strict,
):
    from qwenpaw.governance import tool_adapter
    from agentscope.permission import PermissionBehavior

    tool = SimpleNamespace(
        name="delete_resource",
        _qp_request_context={
            "approval_level": "off",
        },
    )
    result = await tool_adapter._policy_tool_check_permissions(tool, {})
    assert result.behavior == PermissionBehavior.DENY


@pytest.mark.parametrize(
    "path",
    [
        "/api/chats/batch-delete",
        "/api/agents/fault/chats/batch-delete",
        "/api/skills/pool/batch-delete",
        "/portal-api/knowledge-base/sources/delete",
        "/copaw-api/api/backup/delete",
    ],
)
def test_post_deletions_are_not_a_delete_policy_bypass(monkeypatch, path):
    monkeypatch.setenv("QWENPAW_DELETE_OPS_DISABLED", "true")
    app = FastAPI()
    app.add_middleware(DeleteBlockMiddleware)

    @app.post("/{path:path}")
    async def delete(path: str):
        pytest.fail("Deletion must not reach endpoint")

    response = TestClient(app).post(path, json={})
    assert response.status_code == 403
    assert response.json()["code"] == "DELETION_DISABLED"


async def test_approval_actor_cannot_select_another_owner(strict):
    from qwenpaw.app.routers.approval import _require_approval_owner

    pending = SimpleNamespace(extra={"auth_user_id": "7"})
    request = Request(
        {
            "type": "http",
            "headers": [],
            "state": {
                "access_identity": AccessIdentity(
                    user={"userId": 8}, inoe_token="two"
                ),
            },
        }
    )
    with pytest.raises(HTTPException) as error:
        _require_approval_owner(request, pending)
    assert error.value.status_code == 403
    request.state.access_identity = AccessIdentity(
        user={"userId": 7},
        inoe_token="one",
    )
    _require_approval_owner(request, pending)


async def test_security_bootstrap_params_cannot_be_changed_in_env_api(
    monkeypatch,
):
    from qwenpaw.app.routers import envs

    monkeypatch.setattr(envs, "load_envs", lambda: {"USER_SETTING": "keep"})
    monkeypatch.setattr(
        envs, "save_envs", lambda values: pytest.fail("Must not save")
    )
    with pytest.raises(HTTPException) as error:
        await envs.batch_save_envs(
            {
                "USER_SETTING": "keep",
                "QWENPAW_SSO_TOKEN_REQUIRED": "false",
            }
        )
    assert error.value.status_code == 403


def test_skill_environment_cannot_temporarily_promote_a_user(
    strict, monkeypatch, tmp_path
):
    from qwenpaw.agents.skill_system import registry
    import os

    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "7")
    monkeypatch.setattr(
        registry,
        "read_skill_manifest",
        lambda path: {
            "skills": {
                "demo": {
                    "config": {"QWENPAW_ADMIN_INOE_USER_IDS": "9"},
                    "requirements": {
                        "require_envs": ["QWENPAW_ADMIN_INOE_USER_IDS"]
                    },
                }
            },
        },
    )
    monkeypatch.setattr(
        registry, "resolve_effective_skills", lambda *args: ["demo"]
    )
    with pytest.raises(PermissionError):
        with registry.apply_skill_config_env_overrides(tmp_path, "console"):
            pytest.fail("Unsafe override must not enter agent execution")
    assert os.environ["QWENPAW_ADMIN_INOE_USER_IDS"] == "7"
