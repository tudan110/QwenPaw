"""Shared, revisioned sensitive-text policy for managed runtime boundaries."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import time
from contextlib import closing, contextmanager
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from ...governance import component_events
from . import controlled_documents as store

logger = logging.getLogger(__name__)
Scene = Literal[
    "chat_input", "model_context", "documents", "knowledge", "query_results",
    "exports", "logs", "cache", "debug",
]
Mode = Literal["off", "observe", "block"]
FieldName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=48)]

# This is the UI's scenario catalog as well as the source of enforcement messages.
SCENES: dict[Scene, dict[str, str]] = {
    "chat_input": {"label": "对话输入", "action": "阻止提交", "detail": "文本进入受管聊天处理前检查。"},
    "model_context": {"label": "模型上下文", "action": "阻止发送", "detail": "在受管模型调用前检查发送的文本，包括提示词、历史对话和进入上下文的工具结果。"},
    "documents": {"label": "受控资料", "action": "阻止保存", "detail": "保存前检查标题和正文，不替代受控资料原有分类、脱敏、授权和审批。"},
    "knowledge": {"label": "知识库入库", "action": "阻止入库", "detail": "检查直接录入、受控资料发布、资料元数据编辑及可解码文本上传。阻止模式也拒绝无法检查的文件；仅记录模式不会阻止此类文件。"},
    "query_results": {"label": "业务查询与工具结果", "action": "阻止返回", "detail": "检查智能体受管工具的文本结果，以及实时告警、告警台账和关联工单列表。阻止模式命中时不返回该结果，不影响在其他系统独立查询。"},
    "exports": {"label": "业务与资料导出", "action": "阻止导出", "detail": "检查受控告警明细和受控资料原文下载，不替代条数上限、确认或审批。工单目前只做条数核验，不产生文件。"},
    "logs": {"label": "应用日志", "action": "不写入命中日志", "detail": "检查应用日志处理器将写入文件或标准错误的消息与异常文本；不管控宿主机或第三方服务日志。"},
    "cache": {"label": "运行缓存", "action": "不写入命中缓存", "detail": "检查受管工具原文缓存和对话压缩归档的新增内容；不清理旧缓存，不改变会话历史或模型文件的留存。"},
    "debug": {"label": "调试与调用追踪", "action": "阻止保存或返回", "detail": "检查新增的会话和任务追踪，以及调试页读取的应用日志和追踪明细，不删除既有记录。"},
}
_BOUNDARY_ACTION: dict[Scene, str] = {
    "chat_input": "阻止发送", "model_context": "阻止发送", "documents": "阻止保存",
    "knowledge": "阻止入库", "query_results": "阻止返回", "exports": "阻止导出",
    "logs": "跳过写入", "cache": "跳过写入", "debug": "阻止保存或返回",
}


class PrivacyPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(default=0, ge=0)
    builtin: list[str] = Field(default_factory=lambda: list(store.PATTERNS), max_length=len(store.PATTERNS))
    custom_fields: list[FieldName] = Field(default_factory=list, max_length=32)
    chat_input: Mode = "off"
    model_context: Mode = "off"
    documents: Mode = "off"
    knowledge: Mode = "off"
    query_results: Mode = "off"
    exports: Mode = "off"
    logs: Mode = "off"
    cache: Mode = "off"
    debug: Mode = "off"

    @field_validator("builtin")
    @classmethod
    def validate_builtin(cls, values: list[str]) -> list[str]:
        if set(values) - store.PATTERNS.keys():
            raise ValueError("未知的内置敏感分类")
        return [label for label in store.PATTERNS if label in values]

    @field_validator("custom_fields")
    @classmethod
    def validate_fields(cls, values: list[str]) -> list[str]:
        if any(not re.fullmatch(r"[\w][\w -]*", value) for value in values):
            raise ValueError("自定义字段名仅允许字母、汉字、数字、空格、下划线和短横线")
        if len({value.casefold() for value in values}) != len(values):
            raise ValueError("自定义字段名不能重复")
        return values

    @model_validator(mode="after")
    def validate_active_rules(self):
        if not (self.builtin or self.custom_fields) and any(
            getattr(self, key) != "off" for key in SCENES
        ):
            raise ValueError("启用检查前至少选择一条识别规则")
        return self


class PrivacyBlocked(RuntimeError):
    """Contains no input text or matched value."""


class PrivacyUnavailable(RuntimeError):
    """Policy storage could not be read; do not silently bypass enforcement."""


@contextmanager
def _connection(*, write=False):
    path = store.STORE_DIR / "privacy-policy.sqlite3"
    if write:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.touch(mode=0o600, exist_ok=True)
        connection = sqlite3.connect(path, timeout=3)
    else:
        try:
            path.stat()
        except FileNotFoundError:
            yield None
            return
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    with closing(connection) as db:
        db.row_factory = sqlite3.Row
        if write:
            db.execute("CREATE TABLE IF NOT EXISTS privacy_policy (id INTEGER PRIMARY KEY CHECK (id=1), payload TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS privacy_hits (
                id INTEGER PRIMARY KEY, scene TEXT NOT NULL, decision TEXT NOT NULL,
                revision INTEGER NOT NULL, rule_count INTEGER NOT NULL, at REAL NOT NULL
            )""")
        yield db


def _has_table(db, name: str) -> bool:
    return db is not None and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _policy(db) -> PrivacyPolicy:
    row = db.execute("SELECT payload FROM privacy_policy WHERE id=1").fetchone() if _has_table(db, "privacy_policy") else None
    return PrivacyPolicy.model_validate_json(row[0]) if row else PrivacyPolicy()


def status() -> dict:
    with _connection() as db:
        policy = _policy(db)
        hits = [dict(row) for row in db.execute("SELECT * FROM privacy_hits ORDER BY id DESC LIMIT 20")] if _has_table(db, "privacy_hits") else []
    return {
        "policy": policy.model_dump(), "available_builtin": list(store.PATTERNS),
        "scenes": [{"id": scene, **details} for scene, details in SCENES.items()],
        "hits": hits,
    }


def save(requested: PrivacyPolicy, subject: str) -> None:
    with _connection(write=True) as db, db:
        db.execute("BEGIN IMMEDIATE")
        previous = _policy(db)
        if requested.revision != previous.revision:
            raise store.Rejected(409, "策略已被其他管理员更新，请重新读取后再编辑。")
        if requested == previous:
            return
        updated = requested.model_copy(update={"revision": previous.revision + 1})
        db.execute("INSERT OR REPLACE INTO privacy_policy VALUES (1, ?)", (updated.model_dump_json(),))
    token = component_events.actor.set(subject)
    try:
        component_events.record(
            "privacy_policy", "敏感数据规则", "全局部署",
            previous.model_dump(exclude={"revision"}), updated.model_dump(exclude={"revision"}),
            visible_fields={"builtin", "custom_fields", *SCENES},
        )
    finally:
        component_events.actor.reset(token)


def _context_texts(payload):
    """Walk provider-formatted messages, including tool results/arguments.

    Inspect key/value pairs as fields as well as unlabelled scalar text. Skip
    inline binary sources rather than treating encoded bytes as text.
    """
    from agentscope.message import Msg

    media_url_keys = {"url", "image_url", "file_data", "audio_url", "video_url"}
    text_keys = {"content", "text", "reasoning_content", "arguments"}
    inline_media = re.compile(r"data:[\w.+-]+/[\w.+-]+;base64,[A-Za-z0-9+/]+={0,2}", re.IGNORECASE)
    base64_text = re.compile(r"[A-Za-z0-9+/]+={0,2}")

    stack = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, Msg):
            # Model-only chat, title generation and structured calls can use
            # Msg directly rather than provider-specific dictionaries.
            stack.append(item.model_dump(include={"content"})["content"])
        elif isinstance(item, str):
            yield item
        elif isinstance(item, (list, tuple)):
            # Some formatters emit separate consecutive text blocks.
            fragments = []
            for block in item:
                if isinstance(block, dict) and block.get("type") in ("text", "input_text", "output_text") and isinstance(block.get("text"), str):
                    fragments.append(block["text"])
                else:
                    if len(fragments) > 1:
                        yield "".join(fragments)
                    fragments = []
            if len(fragments) > 1:
                yield "".join(fragments)
            stack.extend(item)
        elif isinstance(item, dict):
            for key, value in item.items():
                if isinstance(value, str):
                    if (key == "data" and item.get("type") == "base64" and base64_text.fullmatch(value)) or (
                        key in media_url_keys and inline_media.fullmatch(value)
                    ):
                        continue
                    yield value if key in text_keys else f"{key}: {value}"
                    if key == "arguments" and value.lstrip().startswith(("{", "[")):
                        try:
                            parsed = json.loads(value)
                        except (ValueError, RecursionError):
                            pass  # Its raw text was already checked.
                        else:
                            stack.append(parsed)
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    yield f"{key}: {value}"
                elif isinstance(value, (list, tuple, dict)):
                    stack.append(value)


def _rule_count(policy: PrivacyPolicy, texts) -> int:
    rules = [store.PATTERNS[label] for label in policy.builtin]
    rules.extend(
        re.compile(rf"(?<![\w-]){re.escape(name)}[\"']?[ \t]*[:：=][ \t]*[^\s]", re.IGNORECASE)
        for name in policy.custom_fields
    )
    remaining = set(rules)
    for text in texts:
        remaining.difference_update(rule for rule in rules if rule in remaining and rule.search(text))
        if not remaining:
            break
    return len(set(rules)) - len(remaining)


def _record_hit(scene: Scene, mode: Mode, revision: int, count: int) -> None:
    with _connection(write=True) as db, db:
        db.execute(
            "INSERT INTO privacy_hits(scene, decision, revision, rule_count, at) VALUES (?, ?, ?, ?, ?)",
            (scene, "blocked" if mode == "block" else "observed", revision, count, time.time()),
        )
        db.execute("DELETE FROM privacy_hits WHERE id <= (SELECT max(id) - 200 FROM privacy_hits)")


def load_policy() -> PrivacyPolicy:
    try:
        with _connection() as db:
            return _policy(db)
    except (OSError, sqlite3.Error, ValueError):
        raise PrivacyUnavailable("暂时无法读取敏感数据策略，请稍后重试或联系管理员。") from None


def check_sync(
    scene: Scene, payload, *, policy: PrivacyPolicy | None = None,
    log_errors: bool = True,
) -> None:
    if policy is None:
        policy = load_policy()
    mode = getattr(policy, scene)
    if mode == "off":
        return
    if scene == "chat_input":
        # Match across adjacent text chunks without losing explicit line breaks.
        texts = ("".join(payload), "\n".join(payload))
    else:
        texts = _context_texts(payload)
    count = _rule_count(policy, texts)
    if not count:
        return
    try:
        _record_hit(scene, mode, policy.revision, count)
    except (OSError, sqlite3.Error):
        if log_errors:
            logger.warning("Unable to record a text privacy hit")
    if mode == "block":
        raise PrivacyBlocked(
            f"{SCENES[scene]['label']}命中敏感数据规则，已{_BOUNDARY_ACTION[scene]}。请移除或脱敏后重试。",
        )


async def check(scene: Scene, payload, *, policy: PrivacyPolicy | None = None) -> None:
    await asyncio.to_thread(check_sync, scene, payload, policy=policy)


def allow_persistence(scene: Scene, payload) -> bool:
    """Optional diagnostic/cache writes must not break the primary operation."""
    try:
        check_sync(scene, payload)
        return True
    except (PrivacyBlocked, PrivacyUnavailable):
        return False


def check_http(scene: Scene, payload) -> None:
    from fastapi import HTTPException

    try:
        check_sync(scene, payload)
    except PrivacyBlocked as exc:
        raise HTTPException(422, str(exc)) from exc
    except PrivacyUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
