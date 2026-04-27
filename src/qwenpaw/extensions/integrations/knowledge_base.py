from __future__ import annotations

import importlib.util
import asyncio
import json
import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Any


_ENGINE_LOCK = threading.Lock()
_ENGINE: Any | None = None
_ENGINE_READY = False
_INGEST_THREADS: dict[str, threading.Thread] = {}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def skill_root() -> Path:
    configured = os.getenv("QWENPAW_KNOWLEDGE_BASE_SKILL_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    working_dir = os.getenv("QWENPAW_WORKING_DIR", "").strip()
    if working_dir:
        candidate = (
            Path(working_dir).expanduser()
            / "workspaces"
            / "knowledge"
            / "skills"
            / "knowledge-base"
        ).resolve()
        if candidate.exists():
            return candidate

    runtime_candidate = (
        Path.home()
        / ".qwenpaw"
        / "workspaces"
        / "knowledge"
        / "skills"
        / "knowledge-base"
    ).resolve()
    if runtime_candidate.exists():
        return runtime_candidate

    return (
        _repo_root()
        / "deploy-all"
        / "qwenpaw"
        / "working"
        / "workspaces"
        / "knowledge"
        / "skills"
        / "knowledge-base"
    )


def data_dir() -> Path:
    configured = (
        os.getenv("QWENPAW_KNOWLEDGE_BASE_DATA_DIR")
        or os.getenv("KNOWLEDGE_BASE_DATA_DIR")
        or ""
    ).strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (skill_root() / "data").resolve()


def _load_engine():
    global _ENGINE, _ENGINE_READY
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE

        root = skill_root()
        server_path = root / "server.py"
        if not server_path.exists():
            raise FileNotFoundError(f"knowledge-base engine not found: {server_path}")

        os.environ.setdefault("KNOWLEDGE_BASE_DATA_DIR", str(data_dir()))
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        spec = importlib.util.spec_from_file_location(
            "qwenpaw_portal_knowledge_base_engine",
            server_path,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"could not load knowledge-base engine: {server_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.init_db()
        module.reap_orphan_jobs()
        module.import_enabled_builtin_packs(force=False)
        _ENGINE = module
        _ENGINE_READY = True
        return module


def health() -> dict[str, Any]:
    engine = _load_engine()
    return {
        "status": "ok" if _ENGINE_READY else "initializing",
        "storage": {
            "skillRoot": str(skill_root()),
            "dataDir": str(data_dir()),
            "dbPath": str(engine.DB_PATH),
        },
        "llm": {
            "enabled": bool(engine.LLM_ENABLED),
            "provider": engine.LLM_DEFAULT_PROVIDER,
        },
        "embedding": engine.embedding_status(),
    }


def query_knowledge(payload: dict[str, Any] | None) -> dict[str, Any]:
    engine = _load_engine()
    body = payload or {}
    query = str(body.get("query") or "").strip()
    if not query:
        raise ValueError("missing query")
    return engine.build_query_response(query, body.get("filters"))


def _extract_model_text(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload.strip()
    content = getattr(payload, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        fragments: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    fragments.append(str(text))
            elif getattr(item, "text", None):
                fragments.append(str(getattr(item, "text")))
        return "\n".join(fragment.strip() for fragment in fragments if fragment).strip()
    text = getattr(payload, "text", None)
    if isinstance(text, str):
        return text.strip()
    return str(payload).strip()


async def _consume_model_text(response: Any) -> str:
    if hasattr(response, "__aiter__"):
        accumulated = ""
        async for chunk in response:
            text = _extract_model_text(chunk)
            if not text:
                continue
            if text.startswith(accumulated):
                accumulated = text
            else:
                accumulated += text
        return accumulated.strip()
    return _extract_model_text(response)


def _resolve_knowledge_model_agent_id(agent_id: str | None) -> str | None:
    normalized = str(agent_id or "").strip()
    if normalized:
        return normalized
    return "knowledge"


async def synthesize_answer(payload: dict[str, Any] | None, *, agent_id: str | None = None) -> dict[str, Any]:
    engine = _load_engine()
    body = payload or {}
    query = str(body.get("query") or "").strip()
    evidence_ids = body.get("evidence_ids") or body.get("evidenceIds") or []
    if not query:
        raise ValueError("missing query")
    if not isinstance(evidence_ids, list):
        evidence_ids = []

    rows = []
    if evidence_ids:
        conn = engine.get_conn()
        try:
            placeholders = ",".join(["?"] * len(evidence_ids))
            rows = conn.execute(
                f"SELECT ku.id, ku.title, ku.content, ku.locator, sr.filename "
                f"FROM knowledge_unit ku JOIN source_record sr ON sr.id=ku.source_record_id "
                f"WHERE ku.id IN ({placeholders})",
                list(evidence_ids),
            ).fetchall()
        finally:
            conn.close()

    blocks: list[str] = []
    ordered_ids: list[str] = []
    for idx, row in enumerate(rows, start=1):
        ordered_ids.append(row["id"])
        locator = (row["locator"] or "").strip()
        source = f"{row['filename']}{(' · ' + locator) if locator else ''}"
        blocks.append(
            f"[{idx}] {row['title']}\n来源: {source}\n内容:\n{row['content']}"
        )

    system_prompt = (
        "你是知识库问答的最终总结助手。你会先参考命中的知识片段，再结合通用运维知识作答。"
        "如果证据足够，直接给出可执行、准确的答案；如果证据不足，也要说明证据不足，"
        "再基于相似线索和通用经验给出审慎推断。不要编造不存在的引用来源。"
        "输出使用简洁中文，包含：结论、依据、建议下一步。"
    )
    evidence_text = "\n\n".join(blocks) if blocks else "本次知识库没有返回可直接引用的证据片段。"
    user_prompt = (
        f"用户问题：{query}\n\n"
        f"知识库证据：\n{evidence_text}\n\n"
        "请给出 AI 总结。"
    )

    from qwenpaw.agents.model_factory import create_model_and_formatter

    model_agent_id = _resolve_knowledge_model_agent_id(agent_id)
    model, _ = create_model_and_formatter(agent_id=model_agent_id)
    response = await model(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    answer = await asyncio.wait_for(_consume_model_text(response), timeout=120)
    return {
        "answer": answer,
        "provider": model_agent_id,
        "model": "",
        "evidence_ids": ordered_ids,
        "created_at": engine.now_iso(),
    }


def list_sources(
    *,
    limit: int = 50,
    offset: int = 0,
    include_archived: bool = False,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    engine = _load_engine()
    return engine.list_source_records(
        limit=limit,
        offset=offset,
        filters=filters or {},
        include_archived=include_archived,
    )


def source_detail(source_record_id: int, *, include_archived: bool = False) -> dict[str, Any]:
    engine = _load_engine()
    item = engine.get_source_record_detail(source_record_id, include_archived=include_archived)
    if not item:
        raise LookupError("source record not found")
    return item


def manual_entry(payload: dict[str, Any] | None) -> dict[str, Any]:
    engine = _load_engine()
    body = payload or {}
    title = str(body.get("title") or "").strip()
    content = str(body.get("content") or "").strip()
    if not title or not content:
        raise ValueError("title and content are required")
    if len(title) > 120:
        raise ValueError("title must be 120 characters or less")
    if len(content.encode("utf-8")) > engine.MAX_MANUAL_ENTRY_BYTES:
        raise ValueError(f"content is too large; max {engine.MAX_MANUAL_ENTRY_BYTES} bytes")

    tags = body.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    meta = {
        "manually_entered": True,
        "source_query": str(body.get("source_query") or body.get("sourceQuery") or "").strip() or None,
        "tags": list(tags) if isinstance(tags, list) else [],
        "scope_label": "运行时沉淀",
    }
    record = engine.insert_curated_knowledge(
        title=engine.clean_display_text(title),
        content=engine.clean_display_text(content),
        meta=meta,
        source_scope="runtime_curated",
        source_type="document",
        note="手动录入",
    )
    return {**record, "meta": meta}


def update_source(payload: dict[str, Any] | None) -> dict[str, Any]:
    engine = _load_engine()
    body = payload or {}
    source_record_id = body.get("source_record_id") or body.get("sourceRecordId")
    if not source_record_id:
        raise ValueError("missing source_record_id")
    return engine.update_source_record_metadata(
        int(source_record_id),
        display_title=body.get("display_title") or body.get("displayTitle"),
        tags=body.get("tags"),
        note=body.get("note"),
        source_scope=body.get("source_scope") or body.get("sourceScope"),
    )


def archive_sources(payload: dict[str, Any] | None) -> dict[str, Any]:
    engine = _load_engine()
    body = payload or {}
    ids = body.get("source_record_ids") or body.get("sourceRecordIds") or []
    reason = str(body.get("reason") or "portal archive").strip()
    return engine.archive_source_records(ids, reason)


def unarchive_sources(payload: dict[str, Any] | None) -> dict[str, Any]:
    engine = _load_engine()
    body = payload or {}
    ids = body.get("source_record_ids") or body.get("sourceRecordIds") or []
    return engine.unarchive_source_records(ids)


def set_embedding_enabled(payload: dict[str, Any] | None) -> dict[str, Any]:
    engine = _load_engine()
    enabled = bool((payload or {}).get("enabled"))
    ok, reason = engine.toggle_embedding(enabled)
    return {
        **engine.embedding_status(),
        "changed": ok,
        "reject_reason": None if ok else reason,
    }


def reindex_embeddings(*, force: bool = False) -> dict[str, Any]:
    engine = _load_engine()
    if not engine.EMBEDDING_ENABLED:
        raise RuntimeError("embedding disabled")

    conn = engine.get_conn()
    try:
        where = "" if force else "AND ku.embedding IS NULL"
        rows = conn.execute(
            "SELECT ku.id FROM knowledge_unit ku JOIN source_record sr ON sr.id=ku.source_record_id "
            "WHERE sr.archived_at IS NULL AND (ku.archived_at IS NULL OR ku.archived_at='') "
            f"{where}"
        ).fetchall()
    finally:
        conn.close()

    ids = [row["id"] for row in rows]
    return {
        "requested": len(ids),
        "embedded": engine.compute_unit_embeddings(ids),
        "force": force,
    }


def create_ingest_job(filename: str, raw: bytes, mime_type: str | None = None) -> dict[str, Any]:
    engine = _load_engine()
    if not filename:
        raise ValueError("missing filename")
    if not raw:
        raise ValueError("empty file")
    if len(raw) > engine.MAX_UPLOAD_BYTES:
        raise ValueError(f"file too large; max {engine.MAX_UPLOAD_BYTES} bytes")

    safe_filename = Path(filename).name
    source_type = engine.detect_source_type(safe_filename, mime_type)
    job_id = f"job_{uuid.uuid4().hex[:10]}"
    created_at = engine.now_iso()
    target = engine.UPLOAD_DIR / f"{uuid.uuid4().hex}{Path(safe_filename).suffix}"
    target.write_bytes(raw)

    conn = engine.get_conn()
    try:
        conn.execute(
            """
            INSERT INTO ingestion_job (
                id, filename, source_type, status, created_at, updated_at,
                progress_pct, current_stage, unit_count, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                safe_filename,
                source_type,
                "queued",
                created_at,
                created_at,
                engine.INGEST_STAGE_PCT["queued"],
                "queued",
                0,
                "已接收，排队中",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    worker = threading.Thread(
        target=engine._run_ingest_worker,
        args=(job_id, str(target), safe_filename, source_type, mime_type),
        daemon=True,
        name=f"knowledge-ingest-{job_id}",
    )
    worker.start()
    _INGEST_THREADS[job_id] = worker

    return {
        "job_id": job_id,
        "filename": safe_filename,
        "source_type": source_type,
        "status": "queued",
        "unit_count": 0,
        "preview_units": [],
        "note": "已接收，后台处理中",
        "poll_url": f"/api/portal/knowledge-base/ingestion-jobs/{job_id}/progress",
    }


def ingestion_jobs(limit: int = 20) -> dict[str, Any]:
    engine = _load_engine()
    conn = engine.get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM ingestion_job ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return {"items": [dict(row) for row in rows]}
    finally:
        conn.close()


def ingestion_progress(job_id: str) -> dict[str, Any]:
    engine = _load_engine()
    conn = engine.get_conn()
    try:
        row = conn.execute(
            """
            SELECT id, filename, source_type, status, created_at, updated_at, finished_at,
                   progress_pct, current_stage, unit_count, note
            FROM ingestion_job WHERE id=?
            """,
            (job_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise LookupError("job not found")
    return dict(row)


def source_summary() -> dict[str, Any]:
    engine = _load_engine()
    return {"items": engine.list_source_summary()}


def units(
    *,
    limit: int = 50,
    include_archived: bool = False,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    engine = _load_engine()
    normalized = engine.normalize_filters(filters or {})
    where: list[str] = []
    params: list[object] = []
    if not include_archived:
        where.append("sr.archived_at IS NULL")
        where.append("(ku.archived_at IS NULL OR ku.archived_at = '')")
    if normalized.get("source_scope"):
        where.append("sr.source_scope = ?")
        params.append(normalized["source_scope"])
    if normalized.get("source_type"):
        where.append("ku.source_type = ?")
        params.append(normalized["source_type"])
    if normalized.get("builtin_pack_id"):
        where.append("sr.builtin_pack_id = ?")
        params.append(normalized["builtin_pack_id"])
    if normalized.get("filename"):
        where.append("sr.filename LIKE ?")
        params.append(f"%{normalized['filename']}%")
    where_clause = f"WHERE {' AND '.join(where)}" if where else ""

    conn = engine.get_conn()
    try:
        rows = conn.execute(
            f"""
            SELECT ku.id, ku.source_type, ku.source_scope, ku.title, ku.content, ku.locator, ku.created_at,
                   sr.filename, sr.uploaded_at, sr.builtin_pack_id, sr.builtin_pack_version, sr.meta_json
            FROM knowledge_unit ku
            JOIN source_record sr ON sr.id = ku.source_record_id
            {where_clause}
            ORDER BY ku.created_at DESC, ku.chunk_index ASC
            LIMIT ?
            """,
            [*params, int(limit)],
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["meta"] = json.loads(item.pop("meta_json") or "{}")
            items.append(item)
        return {"items": items}
    finally:
        conn.close()


def builtin_packs() -> dict[str, Any]:
    engine = _load_engine()
    return {"items": engine.list_builtin_pack_status()}


def reload_builtin_pack(payload: dict[str, Any] | None) -> dict[str, Any]:
    engine = _load_engine()
    body = payload or {}
    return engine.import_enabled_builtin_packs(
        force=bool(body.get("force", True)),
        pack_id=body.get("pack_id") or body.get("packId"),
    )


def dump_for_cli(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
