"""Rule catalog and synthetic, isolated checks for the controlled-documents path."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from uuid import uuid4

from . import controlled_documents as store


CATEGORIES = (
    {"id": "personal", "name": "个人信息", "group": "隐私类",
     "labels": ["手机号", "身份证号", "银行卡号", "位置轨迹", "生物识别声明"],
     "scope": "识别号码格式和显式字段；不分析图片、指纹或人脸本身。"},
    {"id": "business", "name": "商业秘密", "group": "隐私类",
     "labels": ["商业秘密", "机密数据（归为商业秘密）"],
     "scope": "识别带商业秘密或机密数据字段的文本；不推断业务语义。"},
    {"id": "technical", "name": "技术秘密", "group": "技术类",
     "labels": sorted(store.NON_EXPORTABLE_LABELS),
     "scope": "识别令牌、凭据、密钥字段、PEM 私钥和指定配置字段。配置块可能遮蔽后续文本；命中即禁止原文导出。"},
)

def status(db, actor: store.Actor) -> dict:
    return {
        "categories": CATEGORIES,
        "approval_seconds": store.APPROVAL_SECONDS,
        "emergency": bool(store.current_policy(db)["emergency"]),
        "security_hold": store.on_hold(db, actor),
    }


def run_check(actor: store.Actor) -> dict:
    """No inputs, no live grants/downloads; only self-check decisions are persisted."""
    run_id = uuid4().hex
    results: list[dict] = []
    samples: list[dict] = []
    owner = store.Actor("isolated-self-check", "sample-owner")
    viewer = store.Actor(owner.realm, "sample-viewer")

    def insert_sample(db, identifier, title, text, expected, redacted_values):
        labels = store.classify(text)
        db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,NULL)",
                   (identifier, owner.key, title, text, json.dumps(labels), time.time()))
        preview = store.read_preview(db, owner, identifier)
        passed = set(expected) == set(preview["labels"]) and all(
            value not in preview["content"] for value in redacted_values
        )
        samples.append({"title": title, "labels": preview["labels"], "preview": preview["content"] if passed else None})
        return passed

    def allow(key, label, reason, passed=True):
        results.append({"key": key, "label": label, "decision": "allowed", "passed": passed, "reason": reason})

    def deny(key, label, status_code, expected_reason, operation):
        try:
            operation()
        except store.Rejected as exc:
            results.append({"key": key, "label": label, "decision": "denied",
                            "passed": exc.status == status_code and expected_reason in str(exc), "reason": str(exc)})
        else:
            allow(key, label, "预期应拒绝，但实际通过；请检查策略实现。", False)

    with closing(sqlite3.connect(":memory:")) as db:
        db.row_factory = sqlite3.Row
        db.executescript(store.SCHEMA)
        privacy, tech, permit, legacy = (uuid4().hex for _ in range(4))
        privacy_ok = insert_sample(
            db, privacy, "个人信息与商业秘密",
            "资料用途：治理自检（虚构样本）\n联系手机号：19900000000\n商业秘密：DEMO-QUOTE-NOT-REAL",
            ["手机号", "商业秘密"], ["19900000000", "DEMO-QUOTE-NOT-REAL"],
        )
        tech_ok = insert_sample(
            db, tech, "令牌、密钥与核心配置",
            "资料用途：治理自检（虚构样本）\n系统令牌：DEMO-TOKEN\nAPI_KEY=DEMO-KEY\n核心配置：DEMO-CONFIG",
            ["系统令牌", "密钥", "核心配置"], ["DEMO-TOKEN", "DEMO-KEY", "DEMO-CONFIG"],
        )
        allow("classify_read", "分类与本人读取", "两份样本均命中预期分类；本人只收到脱敏预览。"
              if privacy_ok and tech_ok else "分类或脱敏结果不符合预期，已隐藏异常预览。", privacy_ok and tech_ok)
        deny("ungranted_read", "未授权账号读取", 404, "资料不存在或不可访问", lambda: store.read_preview(db, viewer, privacy))
        now = time.time()
        db.execute("INSERT INTO grants VALUES (?,?,?,?,?,?,NULL)",
                   (uuid4().hex, privacy, owner.key, viewer.key, viewer.subject, now + 60))
        shared = store.read_preview(db, viewer, privacy)
        shared_ok = privacy_ok and not shared["owner"] and shared["masked"] and shared["content"] == samples[0]["preview"]
        allow("shared_read", "限时授权账号读取", "仅取得同一份脱敏预览，不取得原文。"
              if shared_ok else "授权读取结果不符合预期。", shared_ok)

        # Model the persisted states the real confirm/review/execute endpoints
        # produce. The legacy row exercises reclassification at download time.
        for identifier, target, state in ((permit, privacy, "pending_review"), (legacy, tech, "export_ready")):
            reviewer = "sample-reviewer" if state == "export_ready" else None
            db.execute("""INSERT INTO operations(id,owner,subject,kind,targets,sensitive,status,created,updated,expires,reviewer)
                          VALUES (?,?,?,?,?,1,?,?,?,?,?)""",
                       (identifier, owner.key, owner.subject, "export", json.dumps([target]), state,
                        now, now, now + store.APPROVAL_SECONDS, reviewer))
        deny("unapproved_export", "未获许可的原文导出", 403, "尚无有效导出许可", lambda: store.consume_export(db, owner, permit))
        db.execute("UPDATE operations SET status='export_ready',reviewer='sample-reviewer' WHERE id=?", (permit,))
        exported = store.consume_export(db, owner, permit)
        export_ok = exported["id"] == privacy
        allow("approved_export", "受限原文导出", "模拟复核态的许可通过校验并被消费；本次未发送原文。"
              if export_ok else "导出许可解析到非目标资料。", export_ok)
        deny("replayed_export", "再次使用导出许可", 403, "许可已经使用", lambda: store.consume_export(db, owner, permit))
        deny("technical_export", "技术秘密原文导出", 403, "禁止导出原文", lambda: store.consume_export(db, owner, legacy))

    with store.transaction(actor, "sensitive.self_check", run_id) as db:
        for item in results:
            item["event_id"] = store.event(
                db, actor, f"sensitive.self_check.{item['key']}", run_id,
                "pass" if item["passed"] else "fail", item["reason"],
            )
        return {"run_id": run_id, "completed_at": time.time(), "samples": samples, "checks": results}
