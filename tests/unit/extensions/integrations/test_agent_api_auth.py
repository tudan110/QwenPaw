# -*- coding: utf-8 -*-
"""User credentials survive collaboration and child processes, not globals."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from qwenpaw.agents.tools import agent_management, shell
from qwenpaw.extensions.api.inoe_settings_store import CURRENT_REQUEST_TOKEN
from qwenpaw.extensions.integrations.agent_api_auth import (
    agent_api_headers,
    get_request_token,
    sandbox_request_environment,
    subprocess_request_environment,
)
from qwenpaw.sandbox import SandboxConfig, SandboxMode

URL = "http://127.0.0.1:8088/api"


@pytest.fixture
def credential(monkeypatch):
    monkeypatch.delenv("QWENPAW_REQUEST_INOE_TOKEN", raising=False)
    monkeypatch.delenv("COPAW_REQUEST_INOE_TOKEN", raising=False)
    reset = CURRENT_REQUEST_TOKEN.set("user-token")
    try:
        yield
    finally:
        CURRENT_REQUEST_TOKEN.reset(reset)


def test_context_token_is_not_replaced_by_shared_environment(
    credential, monkeypatch
):
    monkeypatch.setenv("INOE_API_TOKEN", "shared-token")
    monkeypatch.setenv("QWENPAW_REQUEST_INOE_TOKEN", "other-token")
    assert agent_api_headers(URL, URL) == {"X-Inoe-Token": "user-token"}


@pytest.mark.parametrize(
    "target",
    [
        "http://external.example/api",
        "http://127.0.0.1:9000/api",
        "https://127.0.0.1:8088/api",
        "http://name:password@127.0.0.1:8088/api",
        "http://localhost.attacker.example:8088/api",
    ],
)
def test_credentials_are_not_forwarded_to_arbitrary_targets(
    credential, target
):
    with pytest.raises(ValueError, match="untrusted agent API"):
        agent_api_headers(target, URL)


def test_loopback_alias_is_allowed(credential):
    assert agent_api_headers("http://localhost:8088/api", URL) == {
        "X-Inoe-Token": "user-token"
    }


def test_child_environment_is_local_and_overrides_stale_script_token(
    credential,
):
    original = {"PATH": "original", "INOE_API_TOKEN": "stale-token"}
    child = subprocess_request_environment(original)
    assert original == {"PATH": "original", "INOE_API_TOKEN": "stale-token"}
    assert child["INOE_API_TOKEN"] == "user-token"
    assert child["QWENPAW_REQUEST_INOE_TOKEN"] == "user-token"


@pytest.mark.parametrize(
    "env_key", ["QWENPAW_REQUEST_INOE_TOKEN", "COPAW_REQUEST_INOE_TOKEN"]
)
def test_cli_reads_the_explicit_child_request_credential(monkeypatch, env_key):
    reset = CURRENT_REQUEST_TOKEN.set(None)
    try:
        monkeypatch.setenv(env_key, "Bearer child-token")
        assert get_request_token() == "child-token"
        assert agent_api_headers(URL, URL) == {"X-Inoe-Token": "child-token"}
    finally:
        CURRENT_REQUEST_TOKEN.reset(reset)


def test_no_shared_admin_fallback_without_request_identity(monkeypatch):
    reset = CURRENT_REQUEST_TOKEN.set(None)
    try:
        monkeypatch.delenv("QWENPAW_REQUEST_INOE_TOKEN", raising=False)
        monkeypatch.delenv("COPAW_REQUEST_INOE_TOKEN", raising=False)
        monkeypatch.setenv("INOE_API_TOKEN", "shared-admin")
        assert agent_api_headers(URL, URL) == {}
    finally:
        CURRENT_REQUEST_TOKEN.reset(reset)


def test_sandbox_is_copied_and_explicit_masks_are_preserved(credential):
    original = SandboxConfig(mode=SandboxMode.NONE, workspace_dir="/tmp")
    result = sandbox_request_environment(original)
    assert original.env_vars == {}
    assert result.env_vars["INOE_API_TOKEN"] == "user-token"
    for key in ["INOE_API_TOKEN", "QWENPAW_REQUEST_INOE_TOKEN"]:
        masked = SandboxConfig(
            mode=SandboxMode.NONE, workspace_dir="/tmp", env_vars={key: ""}
        )
        assert sandbox_request_environment(masked).env_vars == {key: ""}
    allowlist = SandboxConfig(
        mode=SandboxMode.NONE,
        workspace_dir="/tmp",
        env_mode="allowlist",
        env_vars={"PATH": "allowed"},
    )
    assert sandbox_request_environment(allowlist).env_vars == {
        "PATH": "allowed"
    }


async def test_all_collaboration_api_paths_forward_user_credentials(
    credential, monkeypatch
):
    requests = []
    real_client = httpx.Client

    def handler(request):
        requests.append(request)
        assert request.headers["X-Inoe-Token"] == "user-token"
        if request.url.path.endswith("/agents"):
            return httpx.Response(200, json={"agents": [{"id": "fault"}]})
        if request.url.path.endswith("/task"):
            return httpx.Response(200, json={"task_id": "task"})
        if "/task/" in request.url.path:
            return httpx.Response(200, json={"status": "finished"})
        return httpx.Response(
            200,
            text="data: "
            + json.dumps(
                {
                    "status": "completed",
                    "output": [
                        {"content": [{"type": "text", "text": "done"}]}
                    ],
                }
            )
            + "\n\n",
        )

    monkeypatch.setattr(agent_management, "read_last_api", lambda: None)
    monkeypatch.setattr(
        agent_management.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    assert (await agent_management.list_agents()).state is not None
    monkeypatch.setattr(
        agent_management,
        "resolve_calling_agent_id",
        lambda _from_agent=None: "gateway",
    )
    reply = await agent_management.chat_with_agent("fault", "help")
    assert "done" in reply.content[0].text
    payload = {"input": [], "session_id": "session"}
    for operation, args in [
        (
            agent_management.collect_final_agent_chat_response,
            (None, payload, "fault", 30),
        ),
        (agent_management.stream_agent_chat, (None, payload, "fault", 30)),
        (
            agent_management.submit_agent_chat_task,
            (None, payload, "fault", 30),
        ),
        (
            agent_management.get_agent_chat_task_status,
            (None, "task", "fault", 30),
        ),
    ]:
        await asyncio.to_thread(operation, *args)
    assert len(requests) == 7
    assert all(
        request.headers.get("X-Agent-Id") == "fault"
        for request in requests
        if not request.url.path.endswith("/agents")
    )


async def test_shell_passes_credentials_only_to_child(
    credential, monkeypatch, tmp_path
):
    process = AsyncMock()
    process.communicate.return_value = (b"ok", b"")
    process.returncode = 0
    create = AsyncMock(return_value=process)
    monkeypatch.setattr(shell.asyncio, "create_subprocess_shell", create)
    monkeypatch.setenv("INOE_API_TOKEN", "global-token")
    await shell.execute_shell_command("echo ok", timeout=5, cwd=tmp_path)
    env = create.await_args.kwargs["env"]
    assert env["INOE_API_TOKEN"] == "user-token"
    assert env["QWENPAW_REQUEST_INOE_TOKEN"] == "user-token"
    import os

    assert os.environ["INOE_API_TOKEN"] == "global-token"


def test_generic_cli_uses_the_same_request_credential(credential, monkeypatch):
    from qwenpaw.cli.http import client
    monkeypatch.setattr(agent_management, "read_last_api", lambda: None)
    with client("http://127.0.0.1:8088") as http_client:
        assert http_client.headers["X-Inoe-Token"] == "user-token"


def test_raw_request_does_not_inherit_another_local_session(credential):
    from qwenpaw.extensions.api.access_session import AccessIdentity, CURRENT_IDENTITY
    reset = CURRENT_IDENTITY.set(AccessIdentity(
        user={"userId": 7}, inoe_token="user-token",
    ))
    try:
        child = subprocess_request_environment({
            "QWENPAW_REQUEST_ACCESS_TOKEN": "stale-other-user",
            "COPAW_REQUEST_ACCESS_TOKEN": "stale-other-user",
        })
        assert "QWENPAW_REQUEST_ACCESS_TOKEN" not in child
        assert "COPAW_REQUEST_ACCESS_TOKEN" not in child
        assert child["INOE_API_TOKEN"] == "user-token"
    finally:
        CURRENT_IDENTITY.reset(reset)
