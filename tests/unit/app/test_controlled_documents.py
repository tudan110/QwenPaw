"""Exercise controlled business operations through the real Portal access policy."""

from concurrent.futures import ThreadPoolExecutor
import time
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from qwenpaw.app.routers import controlled_documents as api
from qwenpaw.app.routers.console import router as console_router
from qwenpaw.extensions.api import controlled_documents as store
from qwenpaw.extensions.api import sso_settings_store, text_privacy
from qwenpaw.governance import component_events
from qwenpaw.extensions.api.sso_token_middleware import SsoTokenMiddleware

BASE = "/api/portal/controlled-documents"
A = {"X-Inoe-Token": "owner"}
B = {"X-Inoe-Token": "viewer"}
ADMIN = {"X-Inoe-Token": "reviewer"}
SECRET = "password: example-control-check-123"
PRIVACY = "联系手机号：19900000000\n商业秘密：DEMO-PRICE"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STORE_DIR", tmp_path / "secret")
    monkeypatch.setattr(component_events, "WORKING_DIR", tmp_path / "audit")
    monkeypatch.setenv("QWENPAW_CONTROLLED_DOCUMENTS", "true")
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", "true")
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "reviewer,reviewer2")
    monkeypatch.setenv("QWENPAW_BROWSER_ORIGINS", "http://testserver")
    realm = lambda: "https://example.invalid/userinfo"
    monkeypatch.setattr(api, "get_userinfo_url", realm)
    monkeypatch.setattr(sso_settings_store, "get_userinfo_url", realm)

    async def validate(token, url, *, use_cache):
        if token not in {"owner", "viewer", "reviewer", "reviewer2"}:
            raise HTTPException(401)
        return {"userId": token}

    application = FastAPI()
    application.add_middleware(SsoTokenMiddleware, validator=AsyncMock(validate=AsyncMock(side_effect=validate)))
    application.include_router(api.router, prefix="/api")
    application.include_router(console_router, prefix="/api")
    with TestClient(application, base_url="http://testserver", headers={"Origin": "http://testserver"}) as client:
        yield client


def post(client, path, headers=A, status=200, **body):
    response = client.post(BASE + path, headers=headers, json=body or None)
    assert response.status_code == status, response.text
    return response


def get(client, path, headers=A, status=200):
    response = client.get(BASE + path, headers=headers)
    assert response.status_code == status, response.text
    return response.json()


def create(client, content=SECRET, owner=A):
    return post(client, "/documents", owner, 201, title="测试资料", content=content).json()["id"]


def operation(client, kind, targets, owner=A, **extra):
    return post(client, "/operations", owner, 201, kind=kind, targets=targets, **extra).json()["id"]


def approve(client, identifier, owner=A):
    assert post(client, f"/operations/{identifier}/confirm", owner).json()["status"] == "pending_review"
    post(client, f"/operations/{identifier}/execute", owner, 403)
    post(client, f"/admin/review/{identifier}", ADMIN, approve=True)


def test_auth_owner_and_sensitive_export(client, monkeypatch):
    get(client, "/state", {}, 401)
    identifier = create(client, PRIVACY)
    path = f"/documents/{identifier}"
    assert get(client, "/state", B)["documents"] == []
    get(client, path, ADMIN, 404)  # Admin cannot read other users' originals.
    assert get(client, path)["content"] == "联系手机号：[手机号已遮蔽]\n[商业秘密已遮蔽]"
    post(client, "/operations", B, 404, kind="export", targets=[identifier])
    op = operation(client, "export", [identifier])
    post(client, f"/operations/{op}/download", A, 403)
    approve(client, op)
    post(client, f"/operations/{op}/execute")
    response = post(client, f"/operations/{op}/download")
    assert response.text == PRIVACY and response.headers["cache-control"] == "no-store"
    post(client, f"/operations/{op}/download", A, 403)
    state = get(client, "/admin/state", ADMIN)
    assert any(item["action"] == "export.download" and item["result"] == "success" for item in state["events"])
    assert "19900000000" not in str(state) and "DEMO-PRICE" not in str(state)
    get(client, "/admin/state", A, 403)
    response = client.post(BASE + "/documents", headers={**A, "Origin": "https://foreign.invalid"}, json={"title": "x", "content": "y"})
    assert response.status_code == 403
    monkeypatch.setattr(api, "get_userinfo_url", lambda: "https://other.invalid/userinfo")
    assert not get(client, "/admin/state", ADMIN)["events"]
    get(client, path, A, 404)


def test_shared_preview_expires_and_is_revocable(client):
    identifier = create(client)
    path = f"/documents/{identifier}"
    get(client, path, B, 404)
    op = operation(client, "share", [identifier], recipient="viewer", minutes=1)
    approve(client, op)
    post(client, f"/operations/{op}/execute")
    assert get(client, path, B)["masked"]
    post(client, "/operations", B, 404, kind="export", targets=[identifier])
    grant = get(client, "/state")["grants"][0]["id"]
    post(client, f"/grants/{grant}/revoke", B, 404)
    post(client, f"/grants/{grant}/revoke")
    get(client, path, B, 404)
    op = operation(client, "share", [identifier], recipient="viewer", minutes=1)
    approve(client, op)
    post(client, f"/operations/{op}/execute")
    actor = store.Actor(api.get_userinfo_url(), "owner")
    with store.connection(actor) as db:
        db.execute("UPDATE grants SET expires=?", (time.time() - 1,))
    get(client, path, B, 404)
    assert get(client, "/state", B)["documents"] == []


@pytest.mark.parametrize("approve_request", [True, False])
def test_admin_can_review_own_request(client, approve_request):
    identifier = create(client, PRIVACY, owner=ADMIN)
    op = operation(client, "export", [identifier], ADMIN)
    review_path = f"/admin/review/{op}"
    post(client, review_path, ADMIN, 409, approve=approve_request)
    post(client, f"/operations/{op}/confirm", ADMIN)
    post(client, review_path, A, 403, approve=approve_request)
    post(client, f"/operations/{op}/execute", ADMIN, 403)

    result = post(client, review_path, ADMIN, approve=approve_request).json()
    assert result["reviewer"] == "reviewer"
    assert result["status"] == ("ready" if approve_request else "rejected")
    assert any(
        row["action"] == "operation.review" and row["object_id"] == op
        and row["subject"] == "reviewer"
        and row["result"] == ("success" if approve_request else "rejected")
        for row in get(client, "/admin/state", ADMIN)["events"]
    )
    if approve_request:
        assert post(client, f"/operations/{op}/execute", ADMIN).json()["status"] == "export_ready"
    else:
        post(client, f"/operations/{op}/execute", ADMIN, 409)


@pytest.mark.parametrize("value,label", [
    ("SYSTEM_TOKEN: SAMPLE-VALUE", "系统令牌"),
    ("SERVICE_API_KEY='SAMPLE-VALUE'", "密钥"),
    ('"database_url": "SAMPLE-VALUE"', "核心配置"),
    ("SERVICE_PASSWORD=SAMPLE-VALUE", "凭据"),
    ("serviceApiKey:\n  SAMPLE-VALUE", "密钥"),
    ("核心配置：\n  host: SAMPLE-VALUE-A\n  cluster: SAMPLE-VALUE-B", "核心配置"),
    ('"core_config": {\n  "host": "SAMPLE-VALUE-A",\n  "cluster": "SAMPLE-VALUE-B"\n}', "核心配置"),
])
def test_technical_secret_cannot_be_exported(client, value, label):
    identifier = create(client, value)
    preview = get(client, f"/documents/{identifier}")
    assert preview["labels"] == [label] and preview["masked"]
    assert "SAMPLE-VALUE" not in preview["content"]
    assert preview["raw_export_allowed"] is False
    assert get(client, "/state")["documents"][0]["raw_export_allowed"] is False
    blocked = post(client, "/operations", A, 403, kind="export", targets=[identifier])
    assert "禁止导出原文" in blocked.json()["detail"]
    assert not get(client, "/state")["operations"]


def test_multiline_pem_masks_overlapping_credential_field():
    text = "api_key: -----BEGIN RSA PRIVATE KEY-----\nSYNTHETIC-KEY-BODY\n-----END RSA PRIVATE KEY-----\n可公开文本"
    assert set(store.classify(text)) == {"密钥", "私钥文件"}
    assert store.mask(text) == "[密钥已遮蔽]\n可公开文本"
    assert "SYNTHETIC-KEY-BODY" not in store.mask(text.split("-----END")[0])


def test_download_rechecks_legacy_grants(client):
    tech = create(client, "ordinary data before policy change")
    op = operation(client, "export", [tech])
    post(client, f"/operations/{op}/confirm")
    post(client, f"/operations/{op}/execute")
    actor = store.Actor(api.get_userinfo_url(), "owner")
    with store.connection(actor) as db:
        db.execute("UPDATE documents SET content=? WHERE id=?", ("核心配置：SAMPLE-CFG", tech))
        db.execute("UPDATE operations SET reviewer=? WHERE id=?", ("reviewer", op))
    response = post(client, f"/operations/{op}/download", A, 403)
    assert "禁止导出原文" in response.json()["detail"] and "SAMPLE-CFG" not in response.text
    assert get(client, "/state")["operations"][0]["status"] == "export_ready"

    privacy = create(client, "ordinary data before policy change")
    share = operation(client, "share", [privacy], recipient="viewer")
    export = operation(client, "export", [privacy])
    post(client, f"/operations/{share}/confirm")
    post(client, f"/operations/{export}/confirm")
    post(client, f"/operations/{export}/execute")
    with store.connection(actor) as db:
        db.execute("UPDATE documents SET content=? WHERE id=?", (PRIVACY, privacy))
    assert "复核" in post(client, f"/operations/{export}/download", A, 403).json()["detail"]
    assert "复核" in post(client, f"/operations/{share}/execute", A, 403).json()["detail"]
    assert not get(client, "/state")["grants"]


def test_sensitive_governance_checks_are_guarded_isolated_and_audited(client, monkeypatch):
    path = "/admin/sensitive-data"
    get(client, path, {}, 401)
    get(client, path, A, 403)
    post(client, path + "/check", B, 403)
    assert client.post(BASE + path + "/check", headers={**ADMIN, "Origin": "https://foreign.invalid"}).status_code == 403
    catalog = get(client, path, ADMIN)
    assert catalog["categories"] and catalog["approval_seconds"] > 0
    policy = get(client, path + "/policy", ADMIN)
    assert {item["id"] for item in policy["scenes"]} == {
        "chat_input", "model_context", "documents", "knowledge", "query_results",
        "exports", "logs", "cache", "debug",
    }
    document_id = create(client, owner=ADMIN)
    post(client, "/admin/emergency", ADMIN, active=True)
    assert get(client, path, ADMIN)["emergency"]
    before = get(client, "/state", ADMIN)
    response = post(client, path + "/check", ADMIN, document_id=document_id, subject="viewer", approve=True)
    assert response.headers["cache-control"] == "no-store"
    check_run = response.json()
    checks = check_run["checks"]
    assert [check["decision"] for check in checks] == ["allowed", "denied", "allowed", "denied", "allowed", "denied", "denied"]
    assert all(check["passed"] for check in checks)
    assert "禁止导出原文" in checks[-1]["reason"]
    assert {"系统令牌", "密钥", "核心配置"} == set(check_run["samples"][1]["labels"])
    assert "[手机号已遮蔽]" in check_run["samples"][0]["preview"]
    assert "[系统令牌已遮蔽]" in check_run["samples"][1]["preview"]
    assert get(client, "/state", ADMIN) == before
    oversight = get(client, "/admin/state", ADMIN)
    assert not oversight["incidents"] and not oversight["reviews"]
    events = {event["id"]: event for event in oversight["events"] if event["object_id"] == check_run["run_id"]}
    assert len(events) == len(checks)
    for check in checks:
        event = events[check["event_id"]]
        assert event["subject"] == "reviewer" and event["result"] == "pass"
        assert event["action"] == f"sensitive.self_check.{check['key']}"
    for original in ("DEMO-TOKEN", "DEMO-KEY", "DEMO-CONFIG", "19900000000", "DEMO-QUOTE-NOT-REAL", SECRET):
        assert original not in response.text and original not in str(oversight)
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "false")
    get(client, path, ADMIN, 503)
    post(client, path + "/check", ADMIN, 503)
    monkeypatch.setenv("QWENPAW_CONTROLLED_DOCUMENTS", "false")
    get(client, path, ADMIN, 404)
    post(client, path + "/check", ADMIN, 404)


def wait_cursor(client, op, minimum):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = next(row for row in get(client, "/state")["operations"] if row["id"] == op)
        if result["cursor"] >= minimum:
            return result
        time.sleep(0.025)
    pytest.fail("No durable progress from the live archive worker")


def test_live_batch_pause_resume_shutdown_and_rollback(client):
    ids = [create(client, f"normal {i}") for i in range(4)]
    op = operation(client, "archive", ids)
    approve(client, op)
    with ThreadPoolExecutor(max_workers=1) as executor:
        starting = executor.submit(post, client, f"/operations/{op}/execute")
        wait_cursor(client, op, 1)
        paused = post(client, f"/operations/{op}/control/pause").json()
        assert paused["status"] == "paused" and 1 <= paused["cursor"] < len(ids)
        starting.result(timeout=7)
        documents = get(client, "/state")["documents"]
        assert sum(doc["archived"] for doc in documents) == paused["cursor"]
        resumed = executor.submit(post, client, f"/operations/{op}/control/resume")
        wait_cursor(client, op, paused["cursor"] + 1)
        assert post(client, "/admin/emergency", ADMIN, active=True).json()["affected"] == 1
        resumed.result(timeout=7)
        frozen = next(row for row in get(client, "/state")["operations"] if row["id"] == op)
        assert frozen["status"] == "paused" and frozen["cursor"] < len(ids)
        post(client, f"/operations/{op}/control/resume", A, 423)
        post(client, "/operations", A, 423, kind="archive", targets=ids[:1])
        post(client, "/admin/emergency", ADMIN, active=False)
        post(client, f"/operations/{op}/control/resume")
    assert all(doc["archived"] for doc in get(client, "/state")["documents"])
    post(client, f"/operations/{op}/control/rollback")
    assert all(not doc["archived"] for doc in get(client, "/state")["documents"])
    assert get(client, f"/documents/{ids[-1]}")["content"] == "normal 3"


def test_threshold_rejection_alert_and_policy_restore(client):
    ids = [create(client, f"normal {i}") for i in range(3)]
    post(client, "/admin/policy", ADMIN, batch_cap=2, alert_limit=2)
    deny = post(client, "/operations", A, 422, kind="archive", targets=ids).json()
    assert "分成多批" in deny["detail"]
    for _ in range(2):
        get(client, f"/documents/{ids[0]}", B, 404)
    state = get(client, "/admin/state", ADMIN)
    assert len(state["incidents"]) == 1
    assert get(client, "/state", B)["security_hold"]
    post(client, "/operations", B, 423, kind="archive", targets=ids[:1])
    incident = state["incidents"][0]
    assert incident["threshold"] == 2 and incident["subject"] == "viewer"
    assert any(row["id"] == incident["event_id"] and row["result"] == "blocked" for row in state["events"])
    post(client, f"/admin/incidents/{incident['id']}/resolve", ADMIN)
    assert not get(client, "/state", B)["security_hold"]
    revision = state["revisions"][0]
    restored = post(client, f"/admin/policy/{revision['id']}/restore", ADMIN).json()
    assert restored["batch_cap"] == 10 and restored["alert_limit"] == 3
    assert get(client, "/admin/state", ADMIN)["incidents"][0]["resolved"]
    operation(client, "archive", ids)


def test_text_only_portal_sample_rejects_attachment_upload(client, monkeypatch):
    monkeypatch.setenv("QWENPAW_TRUSTED_CHAT_TEXT_GUARD", "true")
    monkeypatch.setenv("QWENPAW_TRUSTED_CHAT_ISOLATION", "true")
    response = client.post("/api/console/upload", headers=A, files={"file": ("sample.txt", b"sample")})
    assert response.status_code == 415
    assert "unsupported-media" in response.json()["detail"]


def test_sensitive_data_policy_is_admin_only_and_independent_of_documents(client, monkeypatch):
    monkeypatch.setenv("QWENPAW_CONTROLLED_DOCUMENTS", "false")
    path = "/admin/sensitive-data/policy"
    get(client, path, {}, 401)
    get(client, path, A, 403)
    assert get(client, path, ADMIN)["policy"]["model_context"] == "off"
    values = dict(revision=0, builtin=[], custom_fields=["客户编号"], chat_input="observe", model_context="block")
    post(client, path, A, 403, **values)
    assert client.post(BASE + path, headers={**ADMIN, "Origin": "https://foreign.invalid"}, json=values).status_code == 403
    post(client, path, ADMIN, 422, **{**values, "custom_fields": [".*"]})
    post(client, path, ADMIN, 422, **{**values, "custom_fields": []})
    post(client, path, ADMIN, 422, **{**values, "builtin": ["不存在的规则"]})
    response = post(client, path, ADMIN, **values)
    assert response.headers["Cache-Control"] == "no-store"
    saved = response.json()["policy"]
    assert {key: saved[key] for key in values} == {**values, "revision": 1}
    new_scenes = {"documents", "knowledge", "query_results", "exports", "logs", "cache", "debug"}
    assert all(saved[scene] == "off" for scene in new_scenes)
    post(client, path, ADMIN, 409, **values)
    assert get(client, path, ADMIN)["policy"]["custom_fields"] == ["客户编号"]



def test_document_policy_blocks_save_and_independently_rechecks_approved_download(client):
    policy = "/admin/sensitive-data/policy"
    sample = "客户编号：DEMO-PRIVATE"
    body = dict(builtin=[], custom_fields=["客户编号"])
    identifier = create(client, sample)
    op = operation(client, "export", [identifier])
    assert post(client, f"/operations/{op}/confirm").json()["status"] == "ready"
    post(client, f"/operations/{op}/execute")

    post(client, policy, ADMIN, **body, documents="block")
    response = post(client, "/documents", A, 422, title="另外一份资料", content=sample)
    assert "阻止保存" in response.json()["detail"] and "DEMO-PRIVATE" not in response.text
    assert len(get(client, "/state")["documents"]) == 1

    post(client, policy, ADMIN, **body, revision=1, documents="off", exports="block")
    response = post(client, f"/operations/{op}/download", A, 422)
    assert "阻止导出" in response.json()["detail"] and "Content-Disposition" not in response.headers
    post(client, policy, ADMIN, **body, revision=2, exports="off")
    assert post(client, f"/operations/{op}/download").text == sample
    assert {hit["scene"] for hit in text_privacy.status()["hits"]} == {"documents", "exports"}
