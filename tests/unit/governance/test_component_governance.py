# -*- coding: utf-8 -*-
"""Evidence tests use real managed writes and never call external services."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from qwenpaw.app import agent_context
from qwenpaw.app.routers import component_governance, mcp, providers, skills
from qwenpaw.extensions.api.component_audit_middleware import (
    ComponentAuditMiddleware,
)
from qwenpaw.governance import component_events, component_scan
from qwenpaw.local_models import llamacpp, manager, resource_policy
from qwenpaw.providers import provider_manager


@pytest.fixture
def app_and_db(monkeypatch, tmp_path):
    monkeypatch.setattr(component_events, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(provider_manager, "SECRET_DIR", tmp_path / "secrets")
    monkeypatch.setattr(
        manager, "DEFAULT_LOCAL_PROVIDER_DIR", tmp_path / "local"
    )
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "admin")
    agent_dir = tmp_path / "query"
    agent_dir.mkdir()
    agent = SimpleNamespace(agent_id="query", workspace_dir=agent_dir)
    monkeypatch.setattr(
        agent_context, "get_agent_for_request", AsyncMock(return_value=agent)
    )
    monkeypatch.setattr(
        mcp, "_agent_for_request", AsyncMock(return_value=agent)
    )
    monkeypatch.setattr(skills, "schedule_agent_reload", lambda *_: None)
    # These management APIs don't perform a remote capability probe in this test.
    add_builtin = provider_manager.ProviderManager._add_builtin
    monkeypatch.setattr(
        provider_manager.ProviderManager,
        "_add_builtin",
        lambda instance, provider: add_builtin(
            instance, provider.model_copy(deep=True)
        ),
    )
    app = FastAPI()
    app.state.provider_manager = provider_manager.ProviderManager()
    app.state.local_model_manager = manager.LocalModelManager()
    app.add_middleware(ComponentAuditMiddleware)

    @app.middleware("http")
    async def authenticated(request: Request, call_next):
        # Simulate the verified identity injected by the existing SSO layer.
        from qwenpaw.extensions.api.access_session import AccessIdentity

        account = request.headers.get("x-test-verified")
        if account:
            request.state.access_identity = AccessIdentity(
                {"userId": account}, ""
            )
        return await call_next(request)

    for router in (
        providers.router,
        skills.router,
        mcp.router,
        component_governance.router,
    ):
        app.include_router(router, prefix="/api")
    return app, tmp_path


def test_real_mutations_feed_both_views(app_and_db):
    app, workspace = app_and_db
    prefix = "/api/security/governance"
    model = {
        "id": "audit-demo-model",
        "name": "Audit test model",
        "supports_multimodal": False,
    }
    skill = {
        "name": "audit-unit-skill",
        "content": "---\nname: audit-unit-skill\ndescription: Audit unit test skill.\n---\n\nOriginal body.\n",
        "enable": False,
    }
    endpoint = {
        "client_key": "audit-unit-mcp",
        "client": {
            "name": "Test MCP",
            "transport": "streamable_http",
            "url": "https://test.example.invalid/mcp",
            "enabled": False,
            "headers": {"Authorization": "Bearer test-secret-never-log"},
        },
    }
    with TestClient(app, headers={"x-test-verified": "admin"}) as client:
        assert client.get(f"{prefix}/changes").json()["total"] == 0
        created = client.post("/api/models/openai/models", json=model)
        assert created.status_code == 201, created.text
        active = client.put(
            "/api/models/active",
            json={
                "provider_id": "openai",
                "model": model["id"],
                "scope": "global",
            },
        )
        assert active.status_code == 200, active.text
        switched = client.put(
            "/api/models/active",
            json={
                "provider_id": "openai",
                "model": "gpt-4o",
                "scope": "global",
            },
        )
        assert switched.status_code == 200, switched.text
        assert client.post("/api/skills", json=skill).status_code == 200
        skill["content"] = skill["content"].replace(
            "Original body.", "New body."
        )
        assert client.put("/api/skills/save", json=skill).status_code == 200
        assert (
            client.put("/api/skills/save", json=skill).status_code == 200
        )  # same-value save
        assert client.delete(f"/api/skills/{skill['name']}").status_code == 200
        created = client.post("/api/mcp", json=endpoint)
        assert created.status_code == 201, created.text
        assert (
            client.put(
                "/api/mcp/audit-unit-mcp", json={"description": "edited"}
            ).status_code
            == 200
        )
        assert client.delete("/api/mcp/audit-unit-mcp").status_code == 200
        assert (
            client.post("/api/models/not-real/models", json=model).status_code
            == 404
        )
        result = client.get(f"{prefix}/changes?view=supply&limit=100").json()
        events = result["records"]
        assert result["total"] == 9, events
        assert [(e["kind"], e["action"]) for e in reversed(events)] == [
            ("model", "add"),
            ("model", "add"),
            ("model", "update"),
            ("skill", "add"),
            ("skill", "update"),
            ("skill", "remove"),
            ("mcp", "add"),
            ("mcp", "update"),
            ("mcp", "remove"),
        ]
        assert {e["subject"] for e in events} == {"inoe:admin"}
        assert events[-3]["before"]["model"] == model["id"]
        assert events[-3]["after"]["model"] == "gpt-4o"
        assert client.get(f"{prefix}/changes?view=config").json()["total"] == 9
        denied = client.get(
            f"{prefix}/changes", headers={"x-test-verified": "not-admin"}
        )
        assert denied.status_code == 403
    database = (
        workspace / "governance" / "component-governance.db"
    ).read_bytes()
    for secret in (
        b"test-secret-never-log",
        b"test.example.invalid",
        b"Original body",
        b"New body",
    ):
        assert secret not in database


def test_scan_report_persists_and_protects_last_success(
    app_and_db, monkeypatch
):
    app, _ = app_and_db
    prefix = "/api/security/governance/scan"
    report = {
        "checked_at": component_events.now(),
        "rows": [
            component_scan.row(
                "model", "test", "global", "not_covered", "不适用本检测器"
            ),
        ],
    }
    expected = {**report, "rows": [{**report["rows"][0], "scope_name": "全局"}]}
    monkeypatch.setattr(component_scan, "run_scan", lambda *args: report)
    with TestClient(app, headers={"x-test-verified": "admin"}) as client:
        assert client.get(prefix).json() == {"report": None}
        assert (
            client.post(
                prefix, headers={"Origin": "https://foreign.invalid"}
            ).status_code
            == 403
        )
        assert client.post(prefix).json() == {"report": expected}
        assert client.get(prefix).json() == {"report": expected}
        monkeypatch.setattr(
            component_scan,
            "run_scan",
            lambda *args: (_ for _ in ()).throw(RuntimeError("failed")),
        )
        assert client.post(prefix).status_code == 503
        assert client.get(prefix).json() == {"report": expected}


def test_osv_uses_installed_versions_and_never_marks_partial_clear(
    monkeypatch,
):
    packages = [
        SimpleNamespace(metadata={"Name": name}, version="2.3.4")
        for name in ("A_Pkg", "B_Pkg", "C_Pkg")
    ]
    monkeypatch.setattr(
        component_scan.metadata, "distributions", lambda: packages
    )

    def handler(request):
        assert str(request.url) == component_scan.OSV_ENDPOINT
        queries = json.loads(request.content)["queries"]
        assert queries[0] == {
            "version": "2.3.4",
            "package": {"name": "a-pkg", "ecosystem": "PyPI"},
        }
        return httpx.Response(
            200,
            json={
                "results": [
                    {},
                    {"vulns": [{"id": "GHSA-example"}]},
                    {"next_page_token": "more"},
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rows = component_scan.scan_dependencies(client)
    assert [r["status"] for r in rows] == ["clear", "findings", "incomplete"]
    assert rows[1]["findings"] == ["GHSA-example"]
    monkeypatch.delenv("QWENPAW_GOVERNANCE_OSV_ENABLED", raising=False)
    monkeypatch.delenv("COPAW_GOVERNANCE_OSV_ENABLED", raising=False)
    assert component_scan.scan_dependencies()[0]["status"] == "not_covered"


def test_skill_scan_reports_clean_and_incomplete(tmp_path):
    skill_dir = tmp_path / "clear"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "A short skill document.", encoding="utf-8"
    )
    rows = component_scan.scan_skills([("query", tmp_path)])
    assert [(r["name"], r["status"]) for r in rows] == [("clear", "clear")]
    (skill_dir / "large.py").write_bytes(b" " * (1024 * 1024 + 1))
    assert (
        component_scan.scan_skills([("query", tmp_path)])[0]["status"]
        == "incomplete"
    )


def test_local_policy_is_saved_and_blocks_launch(app_and_db):
    app, workspace = app_and_db
    path = "/api/security/governance/local-access"
    with TestClient(app, headers={"x-test-verified": "admin"}) as client:
        assert client.get(path).json()["running"] is False
        assert client.put(path, json={"mode": "deny"}).json()["mode"] == "deny"
        assert (
            client.get("/api/security/governance/changes").json()["records"][
                0
            ]["kind"]
            == "local"
        )
    restarted = manager.LocalModelManager()
    assert restarted.get_config().access_mode == "deny"
    assert (
        json.loads((workspace / "local" / "config.json").read_text())[
            "access_mode"
        ]
        == "deny"
    )
    with pytest.raises(RuntimeError, match="禁止"):
        restarted.start_model_download("test/model")


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX permissions")
def test_local_model_directory_and_file_permissions(monkeypatch, tmp_path):
    root = tmp_path / "local_models"
    monkeypatch.setattr(resource_policy, "DEFAULT_LOCAL_PROVIDER_DIR", root)
    resource_policy.protect_storage()
    assert root.stat().st_mode & 0o777 == 0o700
    (root / "models").mkdir()
    model = root / "models" / "demo.gguf"
    model.touch()
    resource_policy.protect_model_file(model)
    assert model.stat().st_mode & 0o777 == 0o400
    other = tmp_path / "outside.gguf"
    other.touch()
    with pytest.raises(RuntimeError, match="拒绝加载"):
        resource_policy.protect_model_file(other)


@pytest.mark.asyncio
async def test_llamacpp_does_not_accept_unprotected_inference_api(monkeypatch):
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        assert kwargs["trust_env"] is False
        return real_client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200))
        )

    monkeypatch.setattr(llamacpp.httpx, "AsyncClient", fake_client)
    with pytest.raises(RuntimeError, match="未通过鉴权"):
        await llamacpp.LlamaCppBackend._verify_private_api(43210, "unit-key")


@pytest.mark.asyncio
async def test_llamacpp_authentication_requires_the_service_key(monkeypatch):
    real_client = httpx.AsyncClient
    received = []

    def handler(request):
        assert request.url.host == "127.0.0.1"
        received.append(request.headers.get("Authorization"))
        return httpx.Response(
            200 if received[-1] == "Bearer unit-key" else 401
        )

    def fake_client(*args, **kwargs):
        assert kwargs["trust_env"] is False
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(llamacpp.httpx, "AsyncClient", fake_client)
    await llamacpp.LlamaCppBackend._verify_private_api(43210, "unit-key")
    assert received == [None, "Bearer unit-key"]


def test_prompt_and_security_writes_log_only_change_summaries(app_and_db):
    from qwenpaw.agents.memory.agent_md_manager import AgentMdManager
    from qwenpaw.config import Config, save_config

    app, workspace = app_and_db
    cfg = Config()
    cfg_path = workspace / "config.json"
    save_config(cfg, cfg_path)
    new_setting = not cfg.security.file_guard.allow_preview_outside_workspace

    @app.post("/unit/config")
    def save_real_config():
        text = "internal-only-prompt-text"
        AgentMdManager(workspace).write_working_md("AGENTS", text)
        cfg.security.file_guard.allow_preview_outside_workspace = new_setting
        save_config(cfg, cfg_path)

    with TestClient(app, headers={"x-test-verified": "admin"}) as client:
        assert client.post("/unit/config").status_code == 200
        assert client.post("/unit/config").status_code == 200
        response = client.get("/api/security/governance/changes?view=config")
        assert [
            (e["kind"], e["fields"]) for e in response.json()["records"]
        ] == [
            ("config", ["security"]),
            ("prompt", ["content"]),
        ]
        assert (
            client.get("/api/security/governance/changes?view=supply").json()[
                "total"
            ]
            == 0
        )
    raw = (workspace / "governance" / "component-governance.db").read_bytes()
    assert b"internal-only-prompt-text" not in raw


def test_governance_disposition_requires_latest_finding_and_applies_real_controls(app_and_db, monkeypatch):
    from qwenpaw.agents.skill_system.store import get_workspace_skill_manifest_path
    from qwenpaw.extensions.security import call_admission

    app, root = app_and_db
    workspace = root / "query"
    monkeypatch.setattr(call_admission, "WORKING_DIR", root)
    monkeypatch.setattr(component_governance, "_workspaces", lambda: {"query": workspace})
    monkeypatch.setattr(component_governance, "schedule_agent_reload", lambda *_: None)
    prefix = "/api/security/governance"
    body = {
        "name": "review-skill", "enable": False,
        "content": "---\nname: review-skill\ndescription: Unit test skill.\n---\n\nExample.\n",
    }
    connection = {
        "client_key": "review-mcp", "client": {"name": "Test Connection", "transport": "streamable_http", "url": "https://example.invalid/mcp", "enabled": False},
    }
    checked_at = component_events.now()
    with TestClient(app, headers={"x-test-verified": "admin"}) as client:
        assert client.post("/api/skills", json=body).status_code == 200
        manifest = get_workspace_skill_manifest_path(workspace)
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["skills"][body["name"]]["enabled"] = True
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        assert client.post("/api/mcp", json=connection).status_code in {200, 201}
        component_events.save_scan({"checked_at": checked_at, "rows": [
            component_scan.row("skill", "review-skill", "query", "findings", "synthetic condition"),
            component_scan.row("mcp", "review-mcp", "query", "findings", "synthetic condition"),
            component_scan.row("dependency", "some-package", "全局", "findings", "manual only"),
            component_scan.row("skill", "review-skill", "query", "clear", "no finding"),
        ]})
        endpoint = f"{prefix}/scan/disposition"
        assert client.post(endpoint, headers={"x-test-verified": "other"}, json={"checked_at": checked_at, "index": 0}).status_code == 403
        assert client.post(endpoint, headers={"Origin": "https://foreign.invalid"}, json={"checked_at": checked_at, "index": 0}).status_code == 403
        assert client.post(endpoint, json={"checked_at": "old-report", "index": 0}).status_code == 409
        for index in [2, 3, 40]:
            assert client.post(endpoint, json={"checked_at": checked_at, "index": index}).status_code == 409
        for index in [0, 1]:
            response = client.post(endpoint, json={"checked_at": checked_at, "index": index})
            assert response.status_code == 200, response.text
            assert response.json()["report"]["rows"][index]["action"]["done"]
        assert not json.loads(manifest.read_text(encoding="utf-8"))["skills"][body["name"]]["enabled"]
        assert (workspace / "skills" / body["name"] / "SKILL.md").exists()
        assert call_admission.blocked_by(call_admission.Target("mcp_tool", "test", "review-mcp"))
        records = client.get(f"{prefix}/changes").json()["records"]
        assert any(record["target"] == "review-skill" and record["scope_name"] == "数据分析专家" for record in records)
        assert any(record["target"] == "review-mcp" and record["after"] == {"isolated": True} for record in records)


def test_local_download_controls_persist_and_leave_cached_mode_available(app_and_db, monkeypatch):
    app, _ = app_and_db
    monkeypatch.setattr(manager, "protect_storage", lambda: None)
    runtime = app.state.local_model_manager
    path = "/api/security/governance/local-access"
    with TestClient(app, headers={"x-test-verified": "admin"}) as client:
        resp = client.put(path, json={"mode": "managed", "allow_downloads": False})
        assert resp.status_code == 200 and resp.json()["allow_downloads"] is False
        assert client.get(path).json()["allow_downloads"] is False
        runtime._require_local_storage()
        with pytest.raises(RuntimeError, match="禁止下载"):
            runtime.start_model_download("demo/model")
        assert client.put(path, json={"mode": "deny"}).status_code == 200
        with pytest.raises(RuntimeError, match="禁止受管本地模型"):
            runtime._require_local_storage()
    assert manager.LocalModelManager().get_config().allow_downloads is False


def test_workspace_display_names_are_read_only(tmp_path):
    workspaces = {key: tmp_path / key for key in ("gateway", "custom", "retired")}
    for key, name in (("gateway", "gateway"), ("custom", "值班助手")):
        workspace = workspaces[key]
        workspace.mkdir()
        (workspace / "agent.json").write_text(
            json.dumps({"name": name}), encoding="utf-8",
        )
    report = {"rows": [
        component_scan.row("skill", "sample", key, "clear", "none")
        for key in ("gateway", "custom", "retired", "技能池 1", "fault", "order")
    ]}
    result = component_governance._scan_view(report, workspaces)["report"]
    assert [row["scope_name"] for row in result["rows"]] == [
        "智观AI", "值班助手", "数字员工", "技能池 1", "故障分析专家", "工单处置专员",
    ]
    assert not workspaces["retired"].exists()
