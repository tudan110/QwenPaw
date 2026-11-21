# -*- coding: utf-8 -*-
"""Append-only application audit of managed configuration writes.

Diff raw values in memory only. Never write configuration payloads, prompt
contents, headers, commands, URLs, or secret values to the evidence store.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from ..constant import WORKING_DIR

logger = logging.getLogger(__name__)
actor: ContextVar[str | None] = ContextVar(
    "component_change_actor", default=None
)
INGEST_FAILED = False
_MISSING = object()


def label(value: object) -> str:
    text = str(value or "")
    if not re.fullmatch(r"[\w./:@+ -]{1,150}", text) or "://" in text:
        return "[标识已隐藏]"
    if re.search(r"(?i)(?:bearer |sk-|gh[pousr]_\w|eyJ[\w-]+\.)", text):
        return "[标识已隐藏]"
    return text


def snapshot(path: Path) -> dict | None:
    if actor.get() is None:
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        logger.warning("Unable to read previous component configuration")
        return None


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _open(*, write: bool) -> sqlite3.Connection | None:
    path = WORKING_DIR / "governance" / "component-governance.db"
    if not write:
        if not path.is_file():
            return None
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS changes (
            id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, subject TEXT NOT NULL,
            scope TEXT NOT NULL, kind TEXT NOT NULL, target TEXT NOT NULL,
            action TEXT NOT NULL, fields TEXT NOT NULL, before TEXT, after TEXT,
            supply INTEGER NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS latest_scan (
            id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL)""")
    except Exception:
        conn.close()
        raise
    return conn


def record(
    kind: str,
    target: str,
    scope: str,
    before: Mapping | None,
    after: Mapping | None,
    *,
    supply: bool = False,
    summaries: tuple[dict | None, dict | None] = (None, None),
    visible_fields: set[str] | None = None,
) -> None:
    """Record a successful write; equality is checked before redaction."""
    subject = actor.get()
    if subject is None or before == after:
        return
    old, new = before or {}, after or {}
    changed = {
        key
        for key in old.keys() | new.keys()
        if old.get(key, _MISSING) != new.get(key, _MISSING)
    }
    # Never emit dynamic keys (e.g. header names) as field labels.
    fields = sorted(changed & (visible_fields or set()))
    if changed - set(fields):
        fields.append("其他受保护字段")
    action = (
        "add" if before is None else "remove" if after is None else "update"
    )
    if all(state is not None for state in summaries):
        was, is_now = (state.get("enabled") for state in summaries)
        if (
            isinstance(was, bool)
            and isinstance(is_now, bool)
            and was != is_now
        ):
            action = "enable" if is_now else "disable"
    if summaries == (None, None):
        # For protected values, expose structure/presence only, not hashes or
        # values (which may include low-entropy secrets).
        summaries = tuple(
            (
                {
                    field: "已设置（值不公开）" if field in state else "未设置"
                    for field in fields
                    if field != "其他受保护字段"
                }
                if state is not None
                else None
            )
            for state in (before, after)
        )
    global INGEST_FAILED
    try:
        conn = _open(write=True)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO changes(timestamp, subject, scope, kind, target, "
                    "action, fields, before, after, supply) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        now(),
                        label(subject),
                        label(scope),
                        kind,
                        label(target),
                        action,
                        json.dumps(fields),
                        *(
                            json.dumps(s) if s is not None else None
                            for s in summaries
                        ),
                        int(supply),
                    ),
                )
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        # The backing mutation is already committed. Do not report it as rolled back.
        INGEST_FAILED = True
        logger.exception(
            "Component change was committed but audit insertion failed"
        )


def list_changes(*, supply: bool, limit: int, offset: int) -> dict:
    conn = _open(write=False)
    rows, total = [], 0
    if conn is not None:
        try:
            where = " WHERE supply = 1" if supply else ""
            with conn:
                conn.execute("BEGIN")
                total = conn.execute(
                    "SELECT COUNT(*) FROM changes" + where
                ).fetchone()[0]
                rows = conn.execute(
                    "SELECT * FROM changes"
                    + where
                    + " ORDER BY id DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
        finally:
            conn.close()
    records = [dict(row) for row in rows]
    for row in records:
        for field in ("fields", "before", "after"):
            if row[field] is not None:
                row[field] = json.loads(row[field])
    return {"records": records, "total": total, "write_warning": INGEST_FAILED}


def latest_scan() -> dict | None:
    conn = _open(write=False)
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT payload FROM latest_scan WHERE id = 1"
        ).fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()


def save_scan(report: dict) -> None:
    conn = _open(write=True)
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO latest_scan VALUES (1, ?)",
                (json.dumps(report),),
            )
    finally:
        conn.close()


def model_summary(data: Mapping | None) -> dict | None:
    if not data:
        return None
    return {
        "provider": label(data.get("provider_id")),
        "model": label(data.get("model")),
    }


def record_default_model(
    scope: str, before: dict | None, after: dict | None
) -> None:
    record(
        "model",
        "默认模型",
        scope,
        before,
        after,
        supply=True,
        summaries=(model_summary(before), model_summary(after)),
        visible_fields={"provider_id", "model"},
    )


def record_provider(
    provider_id: str, before: dict | None, after: dict | None
) -> None:
    if actor.get() is None:
        return
    groups = {"models", "extra_models"}
    old, new = (
        (
            {k: v for k, v in (data or {}).items() if k not in groups}
            if data is not None
            else None
        )
        for data in (before, after)
    )
    record(
        "provider",
        provider_id,
        "全局",
        old,
        new,
        supply=True,
        visible_fields={
            "base_url",
            "api_key",
            "custom_headers",
            "generate_kwargs",
            "chat_model",
            "auth_mode",
            "name",
        },
    )

    def models(data: dict | None) -> dict:
        return {
            m["id"]: m
            for group in sorted(groups, reverse=True)
            for m in (data or {}).get(group, [])
            if isinstance(m, dict) and "id" in m
        }

    old_models, new_models = models(before), models(after)
    for name in sorted(old_models.keys() | new_models.keys()):
        record(
            "model",
            name,
            provider_id,
            old_models.get(name),
            new_models.get(name),
            supply=True,
            visible_fields={
                "id",
                "name",
                "generate_kwargs",
                "max_tokens",
                "max_input_length",
                "supports_image",
                "supports_video",
                "supports_multimodal",
                "thinking_enabled",
            },
        )


def record_skills(scope: str, before: dict, after: dict) -> None:
    def entries(data: dict) -> dict:
        skills = data.get("skills", {})
        return (
            {
                key: value
                for key, value in skills.items()
                if isinstance(value, dict)
            }
            if isinstance(skills, dict)
            else {}
        )

    def stable(entry: dict | None) -> dict | None:
        if entry is None:
            return None
        data = {
            k: v
            for k, v in entry.items()
            if k not in {"updated_at", "last_checked_at"}
        }
        if isinstance(data.get("metadata"), dict):
            data["metadata"] = {
                k: v
                for k, v in data["metadata"].items()
                if k not in {"mtime", "updated_at"}
            }
        return data

    def summary(entry: dict | None) -> dict | None:
        if entry is None:
            return None
        meta = entry.get("metadata") or {}
        version = meta.get("version_text") if isinstance(meta, dict) else None
        result = {"version": label(version)} if version else {}
        if isinstance(entry.get("enabled"), bool):
            result["enabled"] = entry["enabled"]
        return result

    old, new = entries(before), entries(after)
    for name in sorted(old.keys() | new.keys()):
        a, b = stable(old.get(name)), stable(new.get(name))
        record(
            "skill",
            name,
            scope,
            a,
            b,
            supply=True,
            summaries=(summary(a), summary(b)),
            visible_fields={
                "enabled",
                "source",
                "requirements",
                "config",
                "channels",
                "tags",
                "metadata",
            },
        )
