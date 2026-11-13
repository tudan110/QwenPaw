"""Real routes must enforce the reviewed authentication boundaries."""

import io
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers import agents, backup, config, files
from qwenpaw.backup._ops import storage
from qwenpaw.backup._utils import constants as backup_constants
from qwenpaw.backup.models import BackupMeta
from qwenpaw.config.config import AgentProfileConfig, ChannelConfig, FeishuConfig
from qwenpaw.extensions.api.sso_token_middleware import SsoTokenMiddleware
from qwenpaw.extensions.security import execution_policy


@pytest.fixture
def routes(tmp_path, monkeypatch):
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", "true")
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "1")
    profile = AgentProfileConfig(
        id="gateway",
        name="Gateway",
        channels=ChannelConfig(feishu=FeishuConfig(app_secret="fixture-secret")),
    )
    workspace = SimpleNamespace(config=profile, agent_id="gateway")
    monkeypatch.setattr(agents, "load_agent_config", lambda _: profile)
    monkeypatch.setattr(config, "get_available_channels", lambda: ["feishu"])
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_agent_for_request",
        AsyncMock(return_value=workspace),
    )
    monkeypatch.setattr(config, "schedule_agent_reload", lambda *args: None)
    monkeypatch.setattr("qwenpaw.config.config.save_agent_config", lambda *args: None)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    with zipfile.ZipFile(backup_dir / "fixture.zip", "w") as archive:
        archive.writestr(
            "meta.json", BackupMeta(id="fixture", name="Fixture").model_dump_json()
        )
        archive.writestr("data/secrets/.master_key", "fixture-key")
    monkeypatch.setattr(backup_constants, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(storage, "BACKUP_DIR", backup_dir)
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.setattr(files, "_ALLOWED_ROOT", working)
    monkeypatch.setattr(execution_policy, "WORKING_DIR", working)
    app = FastAPI()
    validator = AsyncMock()
    validator.validate.side_effect = lambda token, *args, **kwargs: {
        "userId": 1 if token == "admin" else 2,
    }
    app.add_middleware(SsoTokenMiddleware, validator=validator)
    for router in (agents.router, config.router, backup.router, files.router):
        app.include_router(router, prefix="/api")
    app.include_router(config.router, prefix="/api/agents/{agentId}")
    return TestClient(app), profile, working


@pytest.mark.parametrize(
    "path",
    [
        "/api/backups",
        "/api/backups/fixture",
        "/api/backups/fixture/export",
        "/api/config/channels",
        "/api/config/channels/feishu",
        "/api/agents/gateway/config/channels",
        "/api/agents/gateway",
    ],
)
@pytest.mark.parametrize("sso_required", [True, False])
def test_sensitive_routes_require_admin_even_when_sso_disabled(
    routes, monkeypatch, path, sso_required
):
    client, _, _ = routes
    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", str(sso_required).lower())
    headers = {"X-Inoe-Token": "ordinary"} if sso_required else {}
    assert client.get(path, headers=headers).status_code == 403


def test_admin_can_export_backup(routes):
    client, _, _ = routes
    response = client.get(
        "/api/backups/fixture/export", headers={"X-Inoe-Token": "admin"}
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.read("data/secrets/.master_key") == b"fixture-key"


@pytest.mark.parametrize(
    "path",
    [
        "/api/agents/gateway",
        "/api/config/channels",
        "/api/config/channels/feishu",
    ],
)
def test_config_responses_mask_secrets_without_mutating_runtime(routes, path):
    client, profile, _ = routes
    response = client.get(path, headers={"X-Inoe-Token": "admin"})
    assert response.status_code == 200
    assert "fixture-secret" not in response.text
    assert "***" in response.text
    assert profile.channels.feishu.app_secret == "fixture-secret"


def test_masked_channel_update_preserves_existing_secret(routes):
    client, profile, _ = routes
    response = client.put(
        "/api/config/channels/feishu",
        headers={"X-Inoe-Token": "admin"},
        json={"app_secret": "***", "app_id": "updated"},
    )
    assert response.status_code == 200
    assert profile.channels.feishu.app_secret == "fixture-secret"
    assert profile.channels.feishu.app_id == "updated"
    assert "fixture-secret" not in response.text


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize(
    "filename",
    [
        "extensions/settings/settings.db",
        "extensions/settings/settings.db-wal",
        "workspaces/gateway/agent.json",
        "config.json",
    ],
)
def test_preview_blocks_configuration_and_database_sidecars(routes, method, filename):
    client, _, working = routes
    target = working / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("fixture-secret")
    response = client.request(
        method,
        "/api/files/preview/" + quote(str(target), safe=""),
        headers={"X-Inoe-Token": "ordinary"},
    )
    assert response.status_code == 403
    assert b"fixture-secret" not in response.content


def test_preview_allows_media_and_rejects_symlink_escape(routes, tmp_path):
    client, _, working = routes
    media = working / "media"
    media.mkdir()
    report = media / "result.txt"
    report.write_text("safe output")
    headers = {"X-Inoe-Token": "ordinary"}
    response = client.get(
        "/api/files/preview/" + quote(str(report), safe=""), headers=headers
    )
    assert response.status_code == 200
    assert response.text == "safe output"
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    link = media / "escape.txt"
    link.symlink_to(outside)
    assert (
        client.get(
            "/api/files/preview/" + quote(str(link), safe=""), headers=headers
        ).status_code
        == 403
    )


def test_nested_config_redaction_preserves_secrets_by_identity_on_reorder():
    from qwenpaw.extensions.security.configuration_secrets import (
        redact_configuration,
        restore_configuration_secrets,
    )

    previous = {
        "clients": [
            {"name": "one", "env": {"CUSTOM_CREDENTIAL": "one-secret"}},
            {"name": "two", "apiKey": "two-secret"},
        ]
    }
    masked = redact_configuration(previous)
    assert "one-secret" not in str(masked)
    assert "two-secret" not in str(masked)
    masked["clients"].reverse()
    restored = restore_configuration_secrets(masked, previous)
    assert restored["clients"][0]["apiKey"] == "two-secret"
    assert restored["clients"][1]["env"]["CUSTOM_CREDENTIAL"] == "one-secret"
    assert previous["clients"][0]["env"]["CUSTOM_CREDENTIAL"] == "one-secret"
