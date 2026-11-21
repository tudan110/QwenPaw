"""Portal API for owner-scoped documents, approvals and recoverable batch jobs."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from functools import wraps
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...extensions.api import controlled_documents as store
from ...extensions.api import sensitive_data_governance as sensitive
from ...extensions.api import text_privacy
from ...extensions.api.access_policy import require_browser_origin
from ...extensions.api.access_session import CURRENT_IDENTITY
from ...extensions.api.sso_settings_store import get_userinfo_url
from ...extensions.security.execution_policy import enabled as production_guards


async def current_actor(request: Request, response: Response) -> AsyncIterator[store.Actor]:
    from ...config.runtime_boundary_policy import flag_enabled

    if not flag_enabled("controlled_documents"):
        raise HTTPException(404, "受控资料未启用")
    if not production_guards():
        raise HTTPException(503, "受控资料要求启用生产保护")
    yield _verified_actor(request, response)


def _verified_actor(request: Request, response: Response) -> store.Actor:
    identity = CURRENT_IDENTITY.get()
    if identity is None or not identity.user_id or identity.source not in {"inoe", "qwenpaw", "mixed"}:
        raise HTTPException(401, "请先通过智观认证")
    if request.method != "GET":
        require_browser_origin(request)
    response.headers["Cache-Control"] = "no-store"
    return store.Actor(get_userinfo_url(), identity.user_id, identity.is_admin)


Actor = Annotated[store.Actor, Depends(current_actor)]


async def admin_actor(actor: Actor) -> store.Actor:
    if not actor.admin:
        raise HTTPException(403, "需要智观 AI 管理员权限")
    return actor


Admin = Annotated[store.Actor, Depends(admin_actor)]


async def privacy_admin_actor(request: Request, response: Response) -> store.Actor:
    return await admin_actor(_verified_actor(request, response))


PrivacyAdmin = Annotated[store.Actor, Depends(privacy_admin_actor)]
router = APIRouter(prefix="/portal/controlled-documents", tags=["controlled-documents"])


class DocumentInput(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=store.MAX_TEXT)


class OperationInput(BaseModel):
    kind: Literal["export", "share", "archive"]
    targets: list[str] = Field(min_length=1, max_length=store.MAX_BATCH)
    recipient: str | None = Field(default=None, max_length=80)
    minutes: int = Field(default=15, ge=1, le=60)


class ReviewInput(BaseModel):
    approve: bool


class EmergencyInput(BaseModel):
    active: bool


class PolicyInput(BaseModel):
    batch_cap: int = Field(ge=2, le=store.MAX_BATCH)
    alert_limit: int = Field(ge=2, le=10)


def with_errors(func):
    # Translate errors only after the transaction has logged/committed the decision.
    @wraps(func)
    def translate(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except store.Rejected as exc:
            return JSONResponse({"detail": str(exc)}, status_code=exc.status, headers={"Cache-Control": "no-store"})
        except (text_privacy.PrivacyBlocked, text_privacy.PrivacyUnavailable) as exc:
            status = 422 if isinstance(exc, text_privacy.PrivacyBlocked) else 503
            return JSONResponse({"detail": str(exc)}, status_code=status, headers={"Cache-Control": "no-store"})

    return translate


@router.get("/state")
def state(actor: Actor) -> dict:
    with store.connection(actor) as db:
        docs = store.rows(db, """SELECT id,owner,title,labels,created,archive_op FROM documents
             WHERE owner=? OR (archive_op IS NULL AND id IN
                (SELECT document_id FROM grants WHERE recipient=? AND revoked IS NULL AND expires>?))
             ORDER BY created DESC LIMIT 300""", (actor.key, actor.key, time.time()))
        ops = store.rows(db, "SELECT * FROM operations WHERE owner=? ORDER BY created DESC LIMIT 50", (actor.key,))
        grants = store.rows(db, """SELECT g.id,g.document_id,g.recipient_label,g.expires,g.revoked,g.owner,d.title
            FROM grants g JOIN documents d ON d.id=g.document_id
            WHERE g.owner=? OR (g.recipient=? AND g.revoked IS NULL AND g.expires>? AND d.archive_op IS NULL)
            ORDER BY g.expires DESC LIMIT 100""", (actor.key, actor.key, time.time()))
        return {
            "actor": actor.subject,
            "admin": actor.admin,
            "policy": store.current_policy(db),
            "security_hold": store.on_hold(db, actor),
            "documents": [store.document_summary(row, actor) for row in docs],
            "operations": [store.operation_summary(row) for row in ops],
            "grants": [{**{field: row[field] for field in row.keys() if field != "owner"},
                        "title": store.mask(row["title"]), "outgoing": row["owner"] == actor.key} for row in grants],
        }


@router.post("/documents", status_code=201)
@with_errors
def create_document(body: DocumentInput, actor: Actor) -> dict:
    identifier = uuid4().hex
    title = body.title.strip()
    with store.transaction(actor, "document.create", identifier) as db:
        if not title or not body.content.strip() or "\0" in body.content or store.classify(title):
            raise store.Rejected(422, "请输入有效的 UTF-8 纯文本；标题不得包含敏感信息")
        text_privacy.check_sync("documents", {"title": title, "content": body.content})
        count = store.one(db, "SELECT count(*) AS n FROM documents WHERE owner=?", (actor.key,))["n"]
        if count >= 250:
            raise store.Rejected(409, "受控资料存储已满，请联系管理员按留存策略处理")
        now = time.time()
        labels = store.classify(body.content)
        db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,NULL)",
                   (identifier, actor.key, title, body.content, json.dumps(labels), now))
        store.event(db, actor, "document.create", identifier, "success", "、".join(labels) or "未命中分类规则")
        return {"id": identifier, "title": title, "labels": labels, "owner": True, "archived": False, "created": now,
                "raw_export_allowed": not store.NON_EXPORTABLE_LABELS.intersection(labels)}


@router.get("/documents/{identifier}")
@with_errors
def read_document(identifier: str, actor: Actor) -> dict:
    with store.transaction(actor, "document.read", identifier) as db:
        preview = store.read_preview(db, actor, identifier)
        store.event(db, actor, "document.read", identifier, "success", "本人或限时授权的脱敏预览")
        return preview


class PublishInput(BaseModel):
    reviewed_for_sharing: Literal[True]


@router.post("/admin/documents/{identifier}/publish")
@with_errors
def publish_to_knowledge_base(identifier: str, body: PublishInput, actor: Admin) -> dict:
    from ...extensions.integrations import knowledge_base

    with store.transaction(actor, "document.publish_knowledge", identifier) as db:
        store.assert_open(db, actor)
        doc = store.owned_document(db, actor, identifier)
        try:
            result = knowledge_base.manual_entry(
                {"title": store.mask(doc["title"]), "content": store.mask(doc["content"]), "tags": ["受控资料发布"]},
                controlled_document_id=identifier,
            )
        except ValueError as exc:
            raise store.Rejected(409, str(exc)) from exc
        store.event(db, actor, "document.publish_knowledge", identifier, "success", f"知识库资料 #{result['id']}")
        return {"source_id": result["id"], "already_published": bool(result.get("already_published"))}


@router.post("/operations", status_code=201)
@with_errors
def request_operation(body: OperationInput, actor: Actor) -> dict:
    with store.transaction(actor, "operation.request") as db:
        store.assert_open(db, actor)
        targets = list(dict.fromkeys(body.targets))
        if len(targets) != len(body.targets) or (body.kind != "archive" and len(targets) != 1):
            raise store.Rejected(422, "资料不可重复，导出和共享一次只能选择一项")
        cap = store.current_policy(db)["batch_cap"]
        if len(targets) > cap:
            raise store.Rejected(422, f"超过单批上限 {cap} 项，请分成多批分别复核与执行")
        documents = [store.owned_document(db, actor, identifier) for identifier in targets]
        if body.kind == "export":
            store.assert_raw_export_allowed(documents[0])
        recipient = body.recipient.strip() if body.recipient else None
        if body.kind == "share" and (not recipient or recipient == actor.subject or not re.fullmatch(r"[a-zA-Z0-9_.@-]+", recipient)):
            raise store.Rejected(422, "请输入本认证来源下另一账号的智观用户 ID")
        if body.kind != "share":
            recipient = None
        risk = body.kind == "archive" or any(store.document_labels(doc) for doc in documents)
        identifier, now = uuid4().hex, time.time()
        db.execute("""INSERT INTO operations(id,owner,subject,kind,targets,sensitive,recipient,recipient_label,
                      minutes,status,created,updated,expires) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (identifier, actor.key, actor.subject, body.kind, json.dumps(targets), int(risk),
                    actor.key_for(recipient) if recipient else None, recipient, body.minutes if recipient else None,
                    "pending_confirm", now, now, now + store.APPROVAL_SECONDS))
        store.event(db, actor, f"{body.kind}.request", identifier, "pending", "需要管理员复核" if risk else "需本人确认")
        return store.operation_summary(store.owned_operation(db, actor, identifier))


@router.post("/operations/{identifier}/confirm")
@with_errors
def confirm_operation(identifier: str, actor: Actor) -> dict:
    with store.transaction(actor, "operation.confirm", identifier) as db:
        row = store.owned_operation(db, actor, identifier)
        store.assert_live(row, "pending_confirm")
        db.execute("UPDATE operations SET status=?,updated=? WHERE id=?",
                   ("pending_review" if row["sensitive"] else "ready", time.time(), identifier))
        store.event(db, actor, "operation.confirm", identifier, "success", "申请人确认影响与目标")
        return store.operation_summary(store.owned_operation(db, actor, identifier))


@router.post("/admin/review/{identifier}")
@with_errors
def review_operation(identifier: str, body: ReviewInput, actor: Admin) -> dict:
    with store.transaction(actor, "operation.review", identifier) as db:
        row = store.one(db, "SELECT * FROM operations WHERE id=?", (identifier,))
        if row is None:
            raise store.Rejected(404, "申请不存在")
        store.assert_live(row, "pending_review")
        db.execute("UPDATE operations SET status=?,reviewer=?,updated=? WHERE id=?",
                   ("ready" if body.approve else "rejected", actor.subject, time.time(), identifier))
        store.event(db, actor, "operation.review", identifier, "success" if body.approve else "rejected")
        return store.operation_summary(store.one(db, "SELECT * FROM operations WHERE id=?", (identifier,)))


async def run_archive(actor: store.Actor, identifier: str, lease: str) -> None:
    # SQLite mutations are synchronous and short, and do not block streaming chat.
    # Each transaction rechecks the lease and control state before applying a change.
    for _ in range(store.MAX_BATCH):
        await asyncio.sleep(1)
        if not await asyncio.to_thread(store.step_archive, actor, identifier, lease):
            return


def claim_archive(db, row, actor: store.Actor, tasks: BackgroundTasks) -> None:
    store.assert_open(db, actor)
    now = time.time()
    lease = uuid4().hex
    db.execute("UPDATE operations SET status='running',lease=?,lease_until=?,updated=? WHERE id=?",
               (lease, now + store.LEASE_SECONDS, now, row["id"]))
    store.event(db, actor, "archive.resume" if row["cursor"] else "archive.start", row["id"], "success", "从持久化检查点开始")
    tasks.add_task(run_archive, actor, row["id"], lease)


@router.post("/operations/{identifier}/execute")
@with_errors
def execute_operation(identifier: str, actor: Actor, background_tasks: BackgroundTasks) -> dict:
    with store.transaction(actor, "operation.execute", identifier) as db:
        store.assert_open(db, actor)
        row = store.owned_operation(db, actor, identifier)
        if row["status"] == "pending_review":
            raise store.Rejected(403, "未完成管理员复核，禁止执行", security=True)
        store.assert_live(row, "ready")
        targets = json.loads(row["targets"])
        documents = [store.owned_document(db, actor, target) for target in targets]
        now = time.time()
        if row["kind"] == "archive":
            if len(targets) > store.current_policy(db)["batch_cap"]:
                raise store.Rejected(422, "策略已变，请在新上限内重新提交")
            claim_archive(db, row, actor, background_tasks)
        elif row["kind"] == "share":
            store.assert_sensitive_review(row, documents)
            if store.one(db, """SELECT 1 FROM grants WHERE document_id=? AND recipient=?
                        AND revoked IS NULL AND expires>?""", (targets[0], row["recipient"], now)):
                raise store.Rejected(409, "该账号已有有效授权，请先撤销旧授权")
            db.execute("INSERT INTO grants VALUES (?,?,?,?,?,?,NULL)",
                       (uuid4().hex, targets[0], actor.key, row["recipient"], row["recipient_label"], now + 60 * row["minutes"]))
            db.execute("UPDATE operations SET status='completed',updated=? WHERE id=?", (now, identifier))
            store.event(db, actor, "grant.issue", targets[0], "success", identifier)
        else:
            store.assert_raw_export_allowed(documents[0])
            store.assert_sensitive_review(row, documents)
            db.execute("UPDATE operations SET status='export_ready',updated=? WHERE id=?", (now, identifier))
            store.event(db, actor, "export.authorize", targets[0], "success", identifier)
        return store.operation_summary(store.owned_operation(db, actor, identifier))


@router.post("/operations/{identifier}/download")
@with_errors
def download_document(identifier: str, actor: Actor) -> Response:
    with store.transaction(actor, "export.download", identifier) as db:
        doc = store.consume_export(db, actor, identifier)
        text_privacy.check_sync("exports", {"title": doc["title"], "content": doc["content"]})
        store.event(db, actor, "export.download", doc["id"], "success", identifier)
        return Response(doc["content"], media_type="text/plain", headers={
            "Content-Disposition": f'attachment; filename="document-{doc["id"]}.txt"',
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        })


@router.post("/operations/{identifier}/control/{action}")
@with_errors
def control_operation(identifier: str, action: Literal["pause", "resume", "stop", "rollback"],
                      actor: Actor, background_tasks: BackgroundTasks) -> dict:
    requested = time.monotonic()
    with store.transaction(actor, f"operation.{action}", identifier) as db:
        row = store.owned_operation(db, actor, identifier)
        state = store.operation_summary(row)["status"]
        now = time.time()
        if action == "stop" and state in {"pending_confirm", "pending_review", "ready", "export_ready"}:
            next_state = "stopped"
        elif row["kind"] != "archive":
            raise store.Rejected(409, "此操作不支持该控制；已共享资料可在授权列表撤销")
        elif action == "pause" and state == "running":
            next_state = "paused"
        elif action == "stop" and state in {"running", "interrupted", "paused", "conflict"}:
            next_state = "stopped"
        elif action == "resume" and state in {"paused", "interrupted"} and row["expires"] > now:
            if len(json.loads(row["targets"])) > store.current_policy(db)["batch_cap"]:
                raise store.Rejected(422, "策略已变，请回退并按新上限重新提交")
            claim_archive(db, row, actor, background_tasks)
            return store.operation_summary(store.owned_operation(db, actor, identifier))
        elif action == "rollback" and state in {"paused", "stopped", "interrupted", "conflict", "completed"} and row["cursor"]:
            restored = db.execute("UPDATE documents SET archive_op=NULL WHERE archive_op=? AND owner=?", (identifier, actor.key)).rowcount
            store.event(db, actor, "archive.restore", identifier, "success", f"恢复 {restored} 项")
            next_state = "rolled_back"
        else:
            raise store.Rejected(409, "当前状态不允许该控制，或原执行授权已过期")
        elapsed = int((time.monotonic() - requested) * 1000)
        db.execute("UPDATE operations SET status=?,lease=NULL,lease_until=NULL,updated=?,control_ms=? WHERE id=?",
                   (next_state, now, elapsed, identifier))
        store.event(db, actor, f"operation.{action}", identifier, "success", next_state)
        return store.operation_summary(store.owned_operation(db, actor, identifier))


@router.post("/grants/{identifier}/revoke")
@with_errors
def revoke_grant(identifier: str, actor: Actor) -> dict:
    with store.transaction(actor, "grant.revoke", identifier) as db:
        now = time.time()
        changed = db.execute("UPDATE grants SET revoked=? WHERE id=? AND owner=? AND revoked IS NULL", (now, identifier, actor.key)).rowcount
        if not changed:
            raise store.Rejected(404, "授权不存在或不可撤销", security=True)
        store.event(db, actor, "grant.revoke", identifier, "success")
        return {"revoked": now}


@router.get("/admin/sensitive-data/policy")
def read_privacy_policy(actor: PrivacyAdmin) -> dict:
    return text_privacy.status()


@router.post("/admin/sensitive-data/policy")
@with_errors
def update_privacy_policy(body: text_privacy.PrivacyPolicy, actor: PrivacyAdmin) -> dict:
    text_privacy.save(body, f"inoe:{actor.subject}")
    return text_privacy.status()


@router.get("/admin/sensitive-data")
def sensitive_data_status(actor: Admin) -> dict:
    with store.connection(actor) as db:
        return sensitive.status(db, actor)


@router.post("/admin/sensitive-data/check")
@with_errors
def check_sensitive_data(actor: Admin) -> dict:
    return sensitive.run_check(actor)


@router.get("/admin/state")
def admin_state(actor: Admin) -> dict:
    with store.connection(actor) as db:
        pending = store.rows(db, "SELECT * FROM operations WHERE status='pending_review' AND expires>? ORDER BY created LIMIT 100", (time.time(),))
        return {
            "reviews": [store.operation_summary(row) for row in pending],
            "incidents": [dict(row) for row in store.rows(db, """SELECT id,subject,count,threshold,event_id,created,resolved,resolver
                    FROM incidents ORDER BY created DESC LIMIT 50""")],
            "events": [dict(row) for row in store.rows(db, """SELECT id,subject,action,object_id,result,reason,created
                       FROM events ORDER BY created DESC LIMIT 100""")],
            "revisions": [{**dict(row), "before": json.loads(row["before"]), "after": json.loads(row["after"])}
                          for row in store.rows(db, "SELECT * FROM revisions ORDER BY created DESC LIMIT 30")],
        }


@router.post("/admin/emergency")
@with_errors
def set_emergency(body: EmergencyInput, actor: Admin) -> dict:
    with store.transaction(actor, "emergency.set") as db:
        db.execute("UPDATE policy SET emergency=? WHERE id=1", (int(body.active),))
        affected = 0
        if body.active:
            # Worker steps and control share the same transaction boundary, so
            # no steps can commit after this control has been acknowledged.
            active = store.rows(db, "SELECT id FROM operations WHERE status='running'")
            affected = db.execute("""UPDATE operations SET status='paused',lease=NULL,lease_until=NULL,updated=?
                                    WHERE status='running'""", (time.time(),)).rowcount
            for row in active:
                store.event(db, actor, "archive.emergency_pause", row["id"], "success")
        store.event(db, actor, "emergency.set", "-", "success", "关停，已保留检查点" if body.active else "解除，不自动续跑")
        return {"active": body.active, "affected": affected}


def set_policy(db, actor, values, restored_from=None) -> dict:
    before = store.current_policy(db)
    db.execute("UPDATE policy SET batch_cap=?,alert_limit=? WHERE id=1", (values["batch_cap"], values["alert_limit"]))
    after = store.current_policy(db)
    identifier = uuid4().hex
    db.execute("INSERT INTO revisions VALUES (?,?,?,?,?,?)",
               (identifier, actor.subject, json.dumps(before), json.dumps(after), time.time(), restored_from))
    store.event(db, actor, "policy.restore" if restored_from else "policy.change", identifier, "success", restored_from)
    return after


@router.post("/admin/policy")
@with_errors
def update_policy(body: PolicyInput, actor: Admin) -> dict:
    with store.transaction(actor, "policy.change") as db:
        return set_policy(db, actor, body.model_dump())


@router.post("/admin/policy/{identifier}/restore")
@with_errors
def restore_policy(identifier: str, actor: Admin) -> dict:
    with store.transaction(actor, "policy.restore", identifier) as db:
        old = store.one(db, "SELECT before FROM revisions WHERE id=?", (identifier,))
        if old is None:
            raise store.Rejected(404, "策略版本不存在")
        return set_policy(db, actor, json.loads(old["before"]), identifier)


@router.post("/admin/incidents/{identifier}/resolve")
@with_errors
def resolve_incident(identifier: str, actor: Admin) -> dict:
    with store.transaction(actor, "incident.resolve", identifier) as db:
        now = time.time()
        if not db.execute("UPDATE incidents SET resolved=?,resolver=? WHERE id=? AND resolved IS NULL",
                          (now, actor.subject, identifier)).rowcount:
            raise store.Rejected(404, "没有可处置的告警")
        store.event(db, actor, "incident.resolve", identifier, "success")
        return {"resolved": now}
