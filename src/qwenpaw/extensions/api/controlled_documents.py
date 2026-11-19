"""Data and policy for the Portal's controlled document workspace."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import uuid4

from ...constant import SECRET_DIR

STORE_DIR = SECRET_DIR / "controlled-documents"
MAX_TEXT = 32_000
MAX_BATCH = 20
APPROVAL_SECONDS = 900
LEASE_SECONDS = 15

# Identify bounded patterns; do not claim to recognize arbitrary secrets or PII.
PATTERNS = {
    "身份证号": re.compile(r"(?<!\d)\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![\dXx])"),
    "银行卡号": re.compile(r"(?i)(?:银行卡(?:号)?|bank card)\s*[:：]\s*[0-9 -]{13,25}"),
    "手机号": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "位置轨迹": re.compile(r"(?:行踪轨迹|精确位置|经纬度)\s*[:：][^\r\n]+"),
    "凭据": re.compile(r"(?i)(?:password|api[_ -]?key|access[_ -]?token|密钥|令牌|密码)\s*[:：=]\s*[^\s，,;；]+|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"),
    "商业秘密": re.compile(r"(?:商业秘密|机密数据)\s*[:：][^\r\n]+"),
    "生物识别声明": re.compile(r"(?:生物识别信息|指纹特征|人脸特征)\s*[:：][^\r\n]+"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
    content TEXT NOT NULL, labels TEXT NOT NULL, created REAL NOT NULL,
    archive_op TEXT
);
CREATE INDEX IF NOT EXISTS documents_owner ON documents(owner, created);
CREATE TABLE IF NOT EXISTS operations (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, subject TEXT NOT NULL,
    kind TEXT NOT NULL, targets TEXT NOT NULL, sensitive INTEGER NOT NULL,
    recipient TEXT, recipient_label TEXT, minutes INTEGER,
    status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
    expires REAL NOT NULL, reviewer TEXT, cursor INTEGER NOT NULL DEFAULT 0,
    lease TEXT, lease_until REAL, control_ms INTEGER
);
CREATE INDEX IF NOT EXISTS operations_owner ON operations(owner, created);
CREATE TABLE IF NOT EXISTS grants (
    id TEXT PRIMARY KEY, document_id TEXT NOT NULL, owner TEXT NOT NULL,
    recipient TEXT NOT NULL, recipient_label TEXT NOT NULL, expires REAL NOT NULL,
    revoked REAL
);
CREATE INDEX IF NOT EXISTS grants_incoming ON grants(recipient, document_id);
CREATE INDEX IF NOT EXISTS grants_active ON grants(document_id, expires);
CREATE TABLE IF NOT EXISTS policy (
    id INTEGER PRIMARY KEY CHECK(id=1), batch_cap INTEGER NOT NULL,
    alert_limit INTEGER NOT NULL, emergency INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO policy(id,batch_cap,alert_limit) VALUES (1,10,3);
CREATE TABLE IF NOT EXISTS revisions (
    id TEXT PRIMARY KEY, subject TEXT NOT NULL, before TEXT NOT NULL,
    after TEXT NOT NULL, created REAL NOT NULL, restored_from TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY, principal TEXT NOT NULL, subject TEXT NOT NULL,
    action TEXT NOT NULL, object_id TEXT NOT NULL, result TEXT NOT NULL,
    reason TEXT, created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS events_actor ON events(principal, result, created);
CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY, principal TEXT NOT NULL, subject TEXT NOT NULL,
    count INTEGER NOT NULL, threshold INTEGER NOT NULL, event_id TEXT NOT NULL,
    created REAL NOT NULL, resolved REAL, resolver TEXT
);
CREATE INDEX IF NOT EXISTS incidents_open ON incidents(principal, resolved);
"""


class Rejected(Exception):
    def __init__(self, status: int, message: str, *, security: bool = False):
        super().__init__(message)
        self.status = status
        self.security = security


@dataclass(frozen=True)
class Actor:
    realm: str
    subject: str
    admin: bool = False

    def key_for(self, subject: str) -> str:
        return hashlib.sha256(f"{self.realm}\0{subject}".encode()).hexdigest()

    @property
    def key(self) -> str:
        return self.key_for(self.subject)


def classify(text: str) -> list[str]:
    return [label for label, rule in PATTERNS.items() if rule.search(text)]


def mask(text: str) -> str:
    for label, rule in PATTERNS.items():
        text = rule.sub(f"[{label}已遮蔽]", text)
    return text


def safe_target(value: str) -> str:
    return value if re.fullmatch(r"[a-f0-9]{32}", value) else "-"


def one(db, sql, args=()):
    return db.execute(sql, args).fetchone()


def rows(db, sql, args=()):
    return db.execute(sql, args).fetchall()


def current_policy(db) -> dict:
    return dict(one(db, "SELECT batch_cap,alert_limit,emergency FROM policy WHERE id=1"))


def event(db, actor: Actor, action: str, target: str, result: str, reason=None) -> str:
    identifier = uuid4().hex
    db.execute(
        "INSERT INTO events VALUES (?,?,?,?,?,?,?,?)",
        (identifier, actor.key, actor.subject, action, safe_target(target), result, reason, time.time()),
    )
    return identifier


def security_alert(db, actor: Actor, event_id: str) -> None:
    now = time.time()
    threshold = current_policy(db)["alert_limit"]
    previous = one(db, "SELECT max(resolved) AS last FROM incidents WHERE principal=?", (actor.key,))
    count = one(db, "SELECT count(*) AS n FROM events WHERE principal=? AND result='blocked' AND created>?",
                (actor.key, max(now - 300, previous["last"] or 0)))["n"]
    if count >= threshold and not on_hold(db, actor):
        incident_id = uuid4().hex
        db.execute("INSERT INTO incidents VALUES (?,?,?,?,?,?,?,NULL,NULL)",
                   (incident_id, actor.key, actor.subject, count, threshold, event_id, now))
        active = rows(db, "SELECT id FROM operations WHERE owner=? AND status='running'", (actor.key,))
        db.execute("UPDATE operations SET status='paused',lease=NULL,lease_until=NULL,updated=? WHERE owner=? AND status='running'",
                   (now, actor.key))
        for row in active:
            event(db, actor, "archive.security_pause", row["id"], "success", incident_id)
        event(db, actor, "incident.hold", incident_id, "success", "已冻结该账号的导出、共享和批量归档")


def on_hold(db, actor: Actor) -> bool:
    return one(db, "SELECT 1 FROM incidents WHERE principal=? AND resolved IS NULL", (actor.key,)) is not None


@contextmanager
def connection(actor: Actor):
    realm = hashlib.sha256(actor.realm.encode()).hexdigest()
    path = STORE_DIR / f"{realm}.sqlite3"
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        # Passive reads should not take schema write locks after initialization.
        if one(db, "PRAGMA user_version")[0] == 0:
            db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nPRAGMA user_version=1;\nCOMMIT;")
        yield db
    finally:
        db.close()


@contextmanager
def transaction(actor: Actor, action: str, target: str = "-"):
    with connection(actor) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
        except Rejected as exc:
            db.rollback()
            db.execute("BEGIN IMMEDIATE")
            identifier = event(db, actor, action, target, "blocked" if exc.security else "rejected", str(exc))
            if exc.security:
                security_alert(db, actor, identifier)
            db.commit()
            raise
        else:
            db.commit()


def owned_document(db, actor: Actor, identifier: str):
    doc = one(db, "SELECT * FROM documents WHERE id=? AND owner=? AND archive_op IS NULL",
              (identifier, actor.key))
    if doc is None:
        raise Rejected(404, "资料不存在或不可访问", security=True)
    return doc


def accessible_document(db, actor: Actor, identifier: str):
    doc = one(db, "SELECT * FROM documents WHERE id=? AND archive_op IS NULL", (identifier,))
    if doc is None or (doc["owner"] != actor.key and not one(
        db, "SELECT 1 FROM grants WHERE document_id=? AND recipient=? AND revoked IS NULL AND expires>?",
        (identifier, actor.key, time.time()),
    )):
        raise Rejected(404, "资料不存在或不可访问", security=True)
    return doc


def document_summary(doc, actor: Actor) -> dict:
    own = doc["owner"] == actor.key
    return {
        "id": doc["id"], "title": doc["title"], "labels": json.loads(doc["labels"]),
        "owner": own, "archived": bool(doc["archive_op"]), "created": doc["created"],
    }


def operation_summary(record) -> dict:
    item = dict(record)
    item["targets"] = json.loads(item["targets"])
    if item["status"] in ("pending_confirm", "pending_review", "ready", "export_ready") and item["expires"] <= time.time():
        item["status"] = "expired"
    elif item["status"] == "running" and item["lease_until"] <= time.time():
        item["status"] = "interrupted"
    for private in ("owner", "recipient", "lease", "lease_until"):
        item.pop(private)
    return item


def owned_operation(db, actor: Actor, identifier: str):
    row = one(db, "SELECT * FROM operations WHERE id=? AND owner=?", (identifier, actor.key))
    if row is None:
        raise Rejected(404, "操作不存在或不可访问", security=True)
    return row


def assert_live(row, *states):
    if row["status"] not in states or row["expires"] <= time.time():
        raise Rejected(409, "操作状态已改变或授权已过期，请刷新后重新申请")


def assert_open(db, actor: Actor):
    if current_policy(db)["emergency"]:
        raise Rejected(423, "已启用紧急关停：资料导出、共享和批量归档已锁定")
    if on_hold(db, actor):
        raise Rejected(423, "该账号的资料操作已因安全告警冻结，请等待管理员处置")


def step_archive(actor: Actor, identifier: str, lease: str) -> bool:
    """Apply one item and its checkpoint in the same SQLite transaction."""
    with transaction(actor, "archive.step", identifier) as db:
        now = time.time()
        op = owned_operation(db, actor, identifier)
        if op["status"] != "running" or op["lease"] != lease or op["lease_until"] <= now:
            return False
        if current_policy(db)["emergency"] or on_hold(db, actor) or op["expires"] <= now:
            db.execute("UPDATE operations SET status='paused',lease=NULL,lease_until=NULL,updated=? WHERE id=?",
                       (now, identifier))
            event(db, actor, "archive.pause", identifier, "success", "紧急关停、安全冻结或授权到期，保留检查点")
            return False
        targets = json.loads(op["targets"])
        index = op["cursor"]
        changed = db.execute("UPDATE documents SET archive_op=? WHERE id=? AND owner=? AND archive_op IS NULL",
                             (identifier, targets[index], actor.key)).rowcount
        if not changed:
            db.execute("UPDATE operations SET status='conflict',lease=NULL,lease_until=NULL,updated=? WHERE id=?",
                       (now, identifier))
            event(db, actor, "archive.freeze", identifier, "failed", "资料状态已变，停止处理并保留已执行项")
            return False
        db.execute("UPDATE grants SET revoked=? WHERE document_id=? AND revoked IS NULL",
                   (now, targets[index]))
        index += 1
        done = index == len(targets)
        db.execute("UPDATE operations SET cursor=?,status=?,updated=?,lease_until=?,lease=? WHERE id=?",
                   (index, "completed" if done else "running", now,
                    None if done else now + LEASE_SECONDS, None if done else lease, identifier))
        event(db, actor, "archive.item", targets[index - 1], "success", identifier)
        if done:
            event(db, actor, "archive.complete", identifier, "success")
        return not done
