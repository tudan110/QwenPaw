"""Actual lease store/middleware/auth helpers; unrelated runtime is isolated."""

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
import importlib.util
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request

ROOT = Path(__file__).resolve().parents[3] / "src/qwenpaw"


@pytest.fixture
def flow(monkeypatch, tmp_path):
    def module(name, **values):
        result = ModuleType(name)
        result.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, result)
        return result

    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, ROOT / path)
        result = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, result)
        spec.loader.exec_module(result)
        return result

    for package in (
        "qwenpaw",
        "qwenpaw.extensions",
        "qwenpaw.extensions.api",
        "qwenpaw.extensions.integrations",
        "qwenpaw.extensions.security",
        "qwenpaw.security",
        "qwenpaw.agents",
        "qwenpaw.agents.tools",
        "qwenpaw.config",
        "qwenpaw.runtime",
        "qwenpaw.utils",
        "agentscope",
        "qwenpaw.app",
        "qwenpaw.app.crons",
    ):
        module(package, __path__=[])
    module(
        "qwenpaw.constant",
        SECRET_DIR=tmp_path,
        EnvVarLoader=SimpleNamespace(
            get_str=os.environ.get,
        ),
    )
    module(
        "qwenpaw.security.secret_store",
        decrypt=lambda x: x,
        encrypt=lambda x: x,
        is_encrypted=lambda x: False,
    )
    inoe = module(
        "qwenpaw.extensions.api.inoe_settings_store",
        CURRENT_REQUEST_TOKEN=ContextVar("request", default=None),
    )
    module(
        "qwenpaw.extensions.api.sso_settings_store",
        get_userinfo_url=lambda: "http://userinfo.invalid",
    )
    module(
        "qwenpaw.extensions.security.execution_policy", enabled=lambda: True
    )
    module(
        "qwenpaw.extensions.api.model_access",
        verify_model_service_key=lambda x: False,
    )

    @dataclass
    class SandboxConfig:
        env_vars: dict = field(default_factory=dict)
        env_mode: str = "inherit"

    module("qwenpaw.sandbox", SandboxConfig=SandboxConfig)
    access = load(
        "qwenpaw.extensions.api.access_session",
        "extensions/api/access_session.py",
    )
    policy = load(
        "qwenpaw.extensions.api.access_policy",
        "extensions/api/access_policy.py",
    )
    load("qwenpaw.extensions.api.sso_auth", "extensions/api/sso_auth.py")
    lease = load(
        "qwenpaw.extensions.api.collaboration_access",
        "extensions/api/collaboration_access.py",
    )
    inoe.has_user_inoe_context = lambda: (
        access.CURRENT_IDENTITY.get().source != lease.SOURCE
        if access.CURRENT_IDENTITY.get() is not None
        else inoe.CURRENT_REQUEST_TOKEN.get() is not None
    )
    auth = load(
        "qwenpaw.extensions.integrations.agent_api_auth",
        "extensions/integrations/agent_api_auth.py",
    )
    middleware = load(
        "qwenpaw.extensions.api.sso_token_middleware",
        "extensions/api/sso_token_middleware.py",
    )
    module("qwenpaw.config.utils", read_last_api=lambda: ("127.0.0.1", 8088))
    module(
        "qwenpaw.runtime.tool_registry",
        tool_descriptor=lambda **kw: lambda fn: fn,
    )
    module("qwenpaw.utils.http", trust_env_for_url=lambda url: False)
    module(
        "agentscope.message",
        TextBlock=lambda **kw: kw,
        ToolResultState=SimpleNamespace(SUCCESS="success"),
    )
    module("agentscope.tool", ToolChunk=lambda **kw: SimpleNamespace(**kw))
    agents = load(
        "qwenpaw.agents.tools.agent_management",
        "agents/tools/agent_management.py",
    )
    trace = module("qwenpaw.app.inbox_trace_store")
    for name in (
        "append_trace_from_session_delta",
        "create_trace",
        "finalize_trace",
        "read_session_messages",
    ):
        setattr(trace, name, AsyncMock(return_value=[]))
    module("qwenpaw.app.crons.models", CronJobSpec=object)
    cron = load("qwenpaw.app.crons.executor", "app/crons/executor.py")
    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", "true")
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "7")
    for name in (
        auth._REQUEST_TOKEN_ENV,
        auth._ACCESS_TOKEN_ENV,
        lease.ENV_KEY,
    ):
        monkeypatch.delenv(name, raising=False)
    validator = AsyncMock()
    validator.validate.return_value = {"userId": 7}
    app = FastAPI()
    app.add_middleware(middleware.SsoTokenMiddleware, validator=validator)

    @app.api_route("/{path:path}", methods=["GET", "POST", "DELETE"])
    async def endpoint(request: Request, path: str):
        await asyncio.sleep(0)
        headers = await asyncio.to_thread(
            auth.agent_api_headers,
            "http://127.0.0.1:8088/api",
            "http://localhost:8088",
        )
        return {
            "source": access.CURRENT_IDENTITY.get().source,
            "admin": access.CURRENT_IDENTITY.get().is_admin,
            "headers": headers,
        }

    return SimpleNamespace(
        lease=lease,
        access=access,
        auth=auth,
        policy=policy,
        inoe=inoe,
        app=app,
        validator=validator,
        middleware=middleware,
        agents=agents,
        cron=cron,
        SandboxConfig=SandboxConfig,
    )


async def test_scheduled_client_nested_http_and_revocation(flow, monkeypatch):
    lease = flow.lease
    with lease.scheduled_collaboration("job", 120):
        token = lease.CURRENT_COLLABORATION_TOKEN.get()
        with flow.agents.create_agent_api_client(None) as client:
            headers = dict(client.headers)
            assert headers[lease.HEADER.lower()] == token
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=flow.app), base_url="http://test"
        ) as client:
            for method, path in (
                ("GET", "/api/agents"),
                ("POST", "/api/console/chat"),
                ("POST", "/api/agents/fault/console/chat/task"),
                ("GET", "/api/console/chat/task/task-123456abcdef"),
            ):
                response = await client.request(method, path, headers=headers)
                assert response.status_code == 200, response.text
                assert response.json() == {
                    "source": lease.SOURCE,
                    "admin": False,
                    "headers": {lease.HEADER: token},
                }
            child = await asyncio.create_task(
                asyncio.to_thread(
                    flow.auth.agent_api_headers,
                    "http://127.0.0.1:8088/api",
                    "http://localhost:8088",
                )
            )
            assert child == {lease.HEADER: token}
    assert lease.CURRENT_COLLABORATION_TOKEN.get() == ""
    assert flow.access.CURRENT_IDENTITY.get() is None
    with pytest.raises(HTTPException) as exc:
        lease.resolve_lease(token, "GET", "/api/agents")
    assert exc.value.status_code == 401
    flow.validator.validate.assert_not_awaited()


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/providers", "GET"),
        ("/api/agents/fault", "GET"),
        ("/api/agents", "POST"),
        ("/api/console/chat/stop", "POST"),
        ("/api/console/upload", "POST"),
        ("/api/fork/agent", "POST"),
        ("/api/console/chat/task/task-123456abcdef/extra", "GET"),
    ],
)
async def test_scope_enforced_even_guards_and_sso_disabled(
    flow, monkeypatch, path, method
):
    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", "false")
    monkeypatch.setattr(
        sys.modules["qwenpaw.extensions.security.execution_policy"],
        "enabled",
        lambda: False,
    )
    with flow.lease.scheduled_collaboration("job", 120):
        token = flow.lease.CURRENT_COLLABORATION_TOKEN.get()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=flow.app), base_url="http://test"
        ) as client:
            response = await client.request(
                method, path, headers={flow.lease.HEADER: token}
            )
            assert response.status_code == 403
            assert token not in response.text


async def test_invalid_expired_mixed_and_forged_payload(flow, monkeypatch):
    token = flow.lease.issue_lease("job", 10)
    with flow.access.get_access_store()._connect() as conn:
        row = conn.execute(
            "SELECT token_hash FROM collaboration_leases"
        ).fetchone()
        assert row["token_hash"] != token
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=flow.app), base_url="http://test"
    ) as client:
        assert (
            await client.post(
                "/api/console/chat", json={"source": "cron", "user_id": "7"}
            )
        ).status_code == 401
        for headers in (
            {flow.lease.HEADER: "qc1.invalid"},
            {flow.lease.HEADER: token, "X-Inoe-Token": "user"},
        ):
            assert (
                await client.post("/api/console/chat", headers=headers)
            ).status_code == 401
        monkeypatch.setattr(flow.lease.time, "time", lambda: 10**12)
        assert (
            await client.get("/api/agents", headers={flow.lease.HEADER: token})
        ).status_code == 401


async def test_online_and_service_requests_do_not_mix(flow):
    token = flow.lease.issue_lease("job", 120)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=flow.app), base_url="http://test"
    ) as client:
        user, service = await asyncio.gather(
            client.post(
                "/api/console/chat", headers={"X-Inoe-Token": "user-token"}
            ),
            client.post(
                "/api/console/chat", headers={flow.lease.HEADER: token}
            ),
        )
    assert user.json()["headers"] == {"X-Inoe-Token": "user-token"}
    assert service.json()["headers"] == {flow.lease.HEADER: token}
    assert flow.access.CURRENT_IDENTITY.get() is None
    assert flow.lease.CURRENT_COLLABORATION_TOKEN.get() == ""


@pytest.mark.parametrize("exception", [RuntimeError, asyncio.CancelledError])
async def test_cron_executor_revokes_on_failure_and_cancel(flow, exception):
    executor = flow.cron.CronExecutor(workspace=None, channel_manager=None)
    observed = []

    async def fail(job):
        observed.append(flow.lease.CURRENT_COLLABORATION_TOKEN.get())
        raise exception()

    executor._execute = fail
    job = SimpleNamespace(
        id="job",
        task_type="agent",
        runtime=SimpleNamespace(timeout_seconds=120),
    )
    with pytest.raises(exception):
        await executor.execute(job)
    assert observed[0]
    with pytest.raises(HTTPException):
        flow.lease.resolve_lease(observed[0], "GET", "/api/agents")
    assert flow.access.CURRENT_IDENTITY.get() is None


async def test_stream_error_is_not_rewritten_as_auth_response(flow):
    messages = []

    async def broken(scope, receive, send):
        await send(
            {"type": "http.response.start", "status": 200, "headers": []}
        )
        raise ValueError("stream failed")

    token = flow.lease.issue_lease("job", 120)
    middleware = flow.middleware.SsoTokenMiddleware(
        broken, validator=flow.validator
    )
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/console/chat",
        "scheme": "http",
        "server": ("test", 80),
        "query_string": b"",
        "headers": [(flow.lease.HEADER.lower().encode(), token.encode())],
    }

    async def send(message):
        messages.append(message)

    with pytest.raises(ValueError, match="stream failed"):
        await middleware(scope, AsyncMock(), send)
    assert len(messages) == 1
    assert flow.access.CURRENT_IDENTITY.get() is None


def test_credentials_stay_scoped_and_trusted(flow, monkeypatch):
    lease = flow.lease
    with lease.scheduled_collaboration("job", 120):
        token = lease.CURRENT_COLLABORATION_TOKEN.get()
        with pytest.raises(ValueError):
            flow.auth.agent_api_headers(
                "http://evil.invalid/api", "http://localhost:8088"
            )
        child = flow.auth.subprocess_request_environment(
            {
                "INOE_API_TOKEN": "business",
                "QWENPAW_REQUEST_ACCESS_TOKEN": "stale",
            }
        )
        assert child[lease.ENV_KEY] == token
        assert child["INOE_API_TOKEN"] == "business"
        assert "QWENPAW_REQUEST_ACCESS_TOKEN" not in child
    identity = flow.access.AccessIdentity(
        user={"userId": 7}, inoe_token="user"
    )
    reset = flow.access.CURRENT_IDENTITY.set(identity)
    request = flow.inoe.CURRENT_REQUEST_TOKEN.set("user")
    try:
        monkeypatch.setenv(lease.ENV_KEY, token)
        with lease.scheduled_collaboration("manual", 120):
            assert flow.access.CURRENT_IDENTITY.get() is identity
            assert lease.CURRENT_COLLABORATION_TOKEN.get() == ""
        assert flow.auth.agent_api_headers(
            "http://localhost:8088/api", "http://localhost:8088"
        ) == {"X-Inoe-Token": "user"}
        config = flow.SandboxConfig(
            env_vars={lease.ENV_KEY: token, "QWENPAW_REQUEST_INOE_TOKEN": ""}
        )
        result = flow.auth.sandbox_request_environment(config)
        assert result.env_vars[lease.ENV_KEY] == ""
        assert result.env_vars["COPAW_REQUEST_COLLABORATION_TOKEN"] == ""
    finally:
        flow.inoe.CURRENT_REQUEST_TOKEN.reset(request)
        flow.access.CURRENT_IDENTITY.reset(reset)
    assert flow.policy.protected_env_key(lease.ENV_KEY)


async def test_scheduled_run_discards_ambient_admin_but_manual_retains_it(
    flow,
):
    executor = flow.cron.CronExecutor(workspace=None, channel_manager=None)
    identity = flow.access.AccessIdentity(
        user={"userId": 7}, inoe_token="user"
    )
    observed = []

    async def succeed(job):
        observed.append(
            (
                flow.access.CURRENT_IDENTITY.get(),
                flow.inoe.CURRENT_REQUEST_TOKEN.get(),
                flow.lease.CURRENT_COLLABORATION_TOKEN.get(),
            )
        )
        return {"delivery_status": "success"}

    executor._execute = succeed
    job = SimpleNamespace(
        id="job",
        task_type="agent",
        runtime=SimpleNamespace(timeout_seconds=120),
    )
    identity_ctx = flow.access.CURRENT_IDENTITY.set(identity)
    request_ctx = flow.inoe.CURRENT_REQUEST_TOKEN.set("user")
    try:
        assert await executor.execute(job, scheduled=True) == {
            "delivery_status": "success"
        }
        service, business_token, lease = observed[-1]
        assert not service.is_admin
        assert business_token == ""
        assert lease
        with pytest.raises(HTTPException):
            flow.lease.resolve_lease(lease, "GET", "/api/agents")
        assert flow.access.CURRENT_IDENTITY.get() is identity
        assert await executor.execute(job, scheduled=False) == {
            "delivery_status": "success"
        }
        assert observed[-1] == (identity, "user", "")
    finally:
        flow.inoe.CURRENT_REQUEST_TOKEN.reset(request_ctx)
        flow.access.CURRENT_IDENTITY.reset(identity_ctx)


async def test_fork_api_forwards_online_credentials(flow, monkeypatch):
    request_ctx = flow.inoe.CURRENT_REQUEST_TOKEN.set("user-token")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        flow.agents.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    try:
        assert await flow.agents._call_fork_api("fault", "session") == {
            "ok": True
        }
        assert requests[0].headers["X-Inoe-Token"] == "user-token"
    finally:
        flow.inoe.CURRENT_REQUEST_TOKEN.reset(request_ctx)


def test_lease_is_masked_in_config_and_output(flow, monkeypatch):
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, ROOT / path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    binding = ModuleType("qwenpaw.drivers.adapters.mcp_binding")
    binding.PUBLIC_HEADER_KEYS = set()
    monkeypatch.setitem(sys.modules, binding.__name__, binding)
    secrets = load(
        "qwenpaw.extensions.security.configuration_secrets",
        "extensions/security/configuration_secrets.py",
    )
    redactor = load(
        "test_collaboration_redactor",
        "extensions/security/output_guard/redactor.py",
    )
    token = flow.lease.issue_lease("job", 120)
    assert (
        secrets.redact_configuration({"headers": {flow.lease.HEADER: token}})[
            "headers"
        ][flow.lease.HEADER]
        == "***"
    )
    masked, _ = redactor.redact(token)
    assert token not in masked
