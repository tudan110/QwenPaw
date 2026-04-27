"""FastAPI router for the knowledge_kb subsystem.

Mounted at /api/portal/knowledge/* by qwenpaw.app._app. Re-implements the
legacy stdlib HTTP server's route table; business logic stays in core.py.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from .. import core
from ..bridges import llm as llm_bridge

router = APIRouter(prefix="/api/portal/knowledge", tags=["knowledge_kb"])

RAG_SYSTEM_PROMPT = (
    "你是运维知识库的 RAG 合成助手。只用下面给出的「资料」回答用户问题。\n"
    "规则:\n"
    "1. 事实必须严格出自资料,禁止编造或补充资料外的信息\n"
    "2. 每条结论末尾用 [序号] 标注引用的资料编号,可多个如 [1][3]\n"
    "3. 如果资料不足以回答,直接说 \"资料不足以回答\",别硬答\n"
    "4. 用简洁中文,能用列表就列表\n"
    "5. 不要元注释,不要 \"根据资料...\",直接给答案"
)
LLM_FALLBACK_SYSTEM_PROMPT = (
    "你是运维知识库的辅助回答助手。用户的问题没有命中本地知识库。\n"
    "请基于通用知识给一个简洁、带边界的回答。\n"
    "如果问题太宽泛或信息不足，直接说明需要更多上下文，不要编造细节。\n"
    "不要给出根因结论。列出建议时每条不超过 80 字。"
)


# ----------------------------- helpers ----------------------------------


def _llm_error_response(exc: Exception) -> JSONResponse:
    """Map llm_bridge exceptions onto the legacy HTTP 503 reason shape."""
    if isinstance(exc, llm_bridge.LLMDisabled):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "llm provider unavailable",
                "reason": "disabled",
                "error": str(exc),
                "hint": "请在 console 配置知识专员的 provider/model（系统设置 → 知识专员 → 模型）",
            },
        )
    if isinstance(exc, llm_bridge.LLMTimeout):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "llm timeout",
                "reason": "timeout",
                "error": str(exc),
            },
        )
    if isinstance(exc, llm_bridge.LLMRateLimit):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "llm rate limited",
                "reason": "rate_limited",
                "error": str(exc),
            },
        )
    if isinstance(exc, llm_bridge.LLMInvalidResponse):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "llm invalid response",
                "reason": "invalid_response",
                "error": str(exc),
            },
        )
    if isinstance(exc, llm_bridge.LLMError):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "llm error",
                "reason": getattr(exc, "reason", "unknown"),
                "error": str(exc),
            },
        )
    return JSONResponse(
        status_code=500,
        content={"detail": "internal error", "error": str(exc)},
    )


# ----------------------------- health -----------------------------------


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "llm_enabled": llm_bridge.is_llm_available(),
        "embedding_enabled": core.embedding_enabled(),
        "embedding_key_configured": core.embedding_enabled(),
        "embedding_env_forced_off": False,
    }


# ----------------------------- ingestion jobs ---------------------------


@router.get("/ingestion-jobs")
async def list_ingestion_jobs(limit: int = 20) -> dict:
    conn = core.get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM ingestion_job ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        items = [dict(r) for r in rows]
    finally:
        conn.close()
    return {"items": items}


@router.get("/ingestion-jobs/{job_id}/progress")
async def ingestion_job_progress(job_id: str) -> dict:
    if not job_id:
        raise HTTPException(status_code=400, detail="missing job id")
    conn = core.get_conn()
    try:
        row = conn.execute(
            """
            SELECT id, filename, source_type, status, created_at, updated_at,
                   finished_at, progress_pct, current_stage, unit_count, note
            FROM ingestion_job WHERE id=?
            """,
            (job_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    return dict(row)


# ----------------------------- units / source records -------------------


@router.get("/units")
async def list_units(  # pylint: disable=too-many-arguments
    limit: int = 50,
    include_archived: bool = False,
    source_scope: str = "",
    source_type: str = "",
    builtin_pack_id: str = "",
    filename: str = "",
) -> dict:
    filters = core.normalize_filters(
        {
            "source_scope": source_scope,
            "source_type": source_type,
            "builtin_pack_id": builtin_pack_id,
            "filename": filename,
        }
    )
    where: list[str] = []
    query_params: list[Any] = []
    if not include_archived:
        where.append("sr.archived_at IS NULL")
        where.append("(ku.archived_at IS NULL OR ku.archived_at = '')")
    if filters.get("source_scope"):
        where.append("sr.source_scope = ?")
        query_params.append(filters["source_scope"])
    if filters.get("source_type"):
        where.append("ku.source_type = ?")
        query_params.append(filters["source_type"])
    if filters.get("builtin_pack_id"):
        where.append("sr.builtin_pack_id = ?")
        query_params.append(filters["builtin_pack_id"])
    if filters.get("filename"):
        where.append("sr.filename LIKE ?")
        query_params.append(f"%{filters['filename']}%")
    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    conn = core.get_conn()
    try:
        rows = conn.execute(
            f"""
            SELECT ku.id, ku.source_type, ku.source_scope, ku.title, ku.content,
                   ku.locator, ku.created_at,
                   sr.filename, sr.uploaded_at, sr.builtin_pack_id,
                   sr.builtin_pack_version, sr.meta_json
            FROM knowledge_unit ku
            JOIN source_record sr ON sr.id = ku.source_record_id
            {where_clause}
            ORDER BY ku.created_at DESC, ku.chunk_index ASC
            LIMIT ?
            """,
            [*query_params, limit],
        ).fetchall()
        items: list[dict] = []
        for row in rows:
            item = dict(row)
            item["meta"] = json.loads(item.pop("meta_json") or "{}")
            items.append(item)
    finally:
        conn.close()
    return {"items": items}


@router.get("/source-records")
async def list_source_records_endpoint(  # pylint: disable=too-many-arguments
    limit: int = 50,
    offset: int = 0,
    include_archived: bool = False,
    source_scope: str = "",
    source_type: str = "",
    builtin_pack_id: str = "",
    filename: str = "",
) -> dict:
    return core.list_source_records(
        limit=limit,
        offset=offset,
        filters={
            "source_scope": source_scope,
            "source_type": source_type,
            "builtin_pack_id": builtin_pack_id,
            "filename": filename,
        },
        include_archived=include_archived,
    )


@router.get("/source-records/detail")
async def source_record_detail_endpoint(
    id: int = Query(..., description="source record id"),  # pylint: disable=redefined-builtin
    include_archived: bool = False,
) -> dict:
    item = core.get_source_record_detail(id, include_archived=include_archived)
    if not item:
        raise HTTPException(status_code=404, detail="source record not found")
    return item


@router.get("/source-summary")
async def source_summary_endpoint() -> dict:
    return {"items": core.list_source_summary()}


@router.get("/builtin-knowledge/packs")
async def builtin_packs() -> dict:
    return {"items": core.list_builtin_pack_status()}


# ----------------------------- knowledge unit / file -------------------


@router.get("/unit")
async def unit_detail(id: str = Query(..., description="unit id")):  # pylint: disable=redefined-builtin
    if not id:
        raise HTTPException(status_code=400, detail="missing id")
    item = core.get_unit_detail(id)
    if not item:
        raise HTTPException(status_code=404, detail="unit not found")
    storage_path = item.get("storage_path") or ""
    file_url = (
        f"/api/portal/knowledge/file?id={id}"
        if storage_path and Path(storage_path).exists()
        else None
    )
    return {
        "id": item["id"],
        "title": core.clean_display_text(item["title"]),
        "content": core.clean_display_text(item["content"]),
        "locator": item["locator"],
        "source_type": core.normalize_response_source_type(item["source_type"]),
        "source_scope": item["source_scope"],
        "filename": item["filename"],
        "mime_type": item["mime_type"],
        "uploaded_at": item["uploaded_at"],
        "builtin_pack_id": item["builtin_pack_id"],
        "builtin_pack_version": item["builtin_pack_version"],
        "meta": item["meta"],
        "file_url": file_url,
    }


@router.get("/file")
async def unit_file(id: str = Query(..., description="unit id")):  # pylint: disable=redefined-builtin
    if not id:
        raise HTTPException(status_code=400, detail="missing id")
    item = core.get_unit_detail(id)
    if not item:
        raise HTTPException(status_code=404, detail="unit not found")
    path = Path(item["storage_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    mime = item["mime_type"] or "application/octet-stream"
    return FileResponse(path=str(path), media_type=mime, filename=path.name)


# ----------------------------- query / ingest --------------------------


@router.post("/query")
async def query_endpoint(payload: dict) -> dict:
    query = (payload.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="missing query")
    return core.build_query_response(query, payload.get("filters"))


@router.post("/ingest")
async def ingest_endpoint(file: UploadFile = File(...)) -> dict:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    if len(raw) > core.MAX_UPLOAD_BYTES:
        return JSONResponse(
            status_code=413,
            content={
                "detail": (
                    f"文件过大（上限 "
                    f"{core.MAX_UPLOAD_BYTES // (1024 * 1024)}MB）"
                ),
                "max_bytes": core.MAX_UPLOAD_BYTES,
            },
        )
    filename = os.path.basename(file.filename or "uploaded")
    if not filename:
        raise HTTPException(status_code=400, detail="missing filename")

    source_type = core.detect_source_type(filename, file.content_type)
    job_id = f"job_{uuid.uuid4().hex[:10]}"
    created_at = core.now_iso()

    safe_name = f"{uuid.uuid4().hex}{Path(filename).suffix}"
    target = core.UPLOAD_DIR / safe_name
    try:
        target.write_bytes(raw)
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(
            status_code=500,
            detail=f"保存上传文件失败：{exc}",
        ) from exc

    conn = core.get_conn()
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
                filename,
                source_type,
                "queued",
                created_at,
                created_at,
                core.INGEST_STAGE_PCT["queued"],
                "queued",
                0,
                "已接收，排队中",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    worker = threading.Thread(
        target=core._run_ingest_worker,  # pylint: disable=protected-access
        args=(job_id, str(target), filename, source_type, file.content_type),
        daemon=True,
        name=f"ingest-worker-{job_id}",
    )
    worker.start()

    return {
        "job_id": job_id,
        "filename": filename,
        "source_type": source_type,
        "status": "queued",
        "unit_count": 0,
        "preview_units": [],
        "note": "已接收，后台处理中",
        "poll_url": f"/api/portal/knowledge/ingestion-jobs/{job_id}/progress",
    }


# ----------------------------- embeddings ------------------------------


@router.post("/embedding/toggle")
async def embedding_toggle_endpoint(payload: dict) -> JSONResponse:
    """Embedding enable state is now driven by the knowledge agent's
    `embedding_config` in console (set api_key/base_url/model_name to enable).
    The legacy runtime toggle is a no-op; we report current status for
    backwards compatibility with the demo UI."""
    _ = payload
    status = core.embedding_status()
    return JSONResponse(
        status_code=200,
        content={
            **status,
            "changed": False,
            "reject_reason": "controlled_by_agent_config",
        },
    )


@router.post("/embeddings/reindex")
async def embeddings_reindex(force: bool = False) -> dict:
    conn = core.get_conn()
    try:
        if force:
            rows = conn.execute(
                "SELECT ku.id FROM knowledge_unit ku "
                "JOIN source_record sr ON sr.id=ku.source_record_id "
                "WHERE sr.archived_at IS NULL "
                "AND (ku.archived_at IS NULL OR ku.archived_at='')"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT ku.id FROM knowledge_unit ku "
                "JOIN source_record sr ON sr.id=ku.source_record_id "
                "WHERE ku.embedding IS NULL AND sr.archived_at IS NULL "
                "AND (ku.archived_at IS NULL OR ku.archived_at='')"
            ).fetchall()
    finally:
        conn.close()
    ku_ids = [r["id"] for r in rows]
    if not core.embedding_enabled():
        raise HTTPException(
            status_code=503,
            detail={
                "message": "embedding disabled",
                "reason": "disabled",
                "hint": (
                    "请在 console 配置知识专员的 embedding "
                    "(api_key/base_url/model_name)"
                ),
            },
        )
    updated = core.compute_unit_embeddings(ku_ids)
    return {
        "requested": len(ku_ids),
        "embedded": updated,
        "force": force,
    }


# ----------------------------- LLM endpoints ---------------------------


@router.post("/chat/rag-synthesize")
async def rag_synthesize(payload: dict) -> Any:
    query = (payload.get("query") or "").strip()
    evidence_ids = payload.get("evidence_ids") or []
    if not query or not evidence_ids:
        raise HTTPException(
            status_code=400,
            detail="missing query or evidence_ids",
        )
    if not llm_bridge.is_llm_available():
        return JSONResponse(
            status_code=503,
            content={
                "detail": "llm unavailable",
                "reason": "disabled",
                "hint": "知识专员未配置可用模型",
            },
        )
    conn = core.get_conn()
    try:
        placeholders = ",".join(["?"] * len(evidence_ids))
        crows = conn.execute(
            f"SELECT ku.id, ku.title, ku.content, ku.locator, sr.filename "
            f"FROM knowledge_unit ku "
            f"JOIN source_record sr ON sr.id=ku.source_record_id "
            f"WHERE ku.id IN ({placeholders})",
            list(evidence_ids),
        ).fetchall()
    finally:
        conn.close()
    if not crows:
        raise HTTPException(status_code=404, detail="no chunks found")
    chunk_blocks: list[str] = []
    ordered_ids: list[str] = []
    for idx, r in enumerate(crows, start=1):
        ordered_ids.append(r["id"])
        title = (r["title"] or "").strip()
        content = (r["content"] or "").strip()
        locator = (r["locator"] or "").strip()
        src = (r["filename"] or "").strip()
        block = (
            f"[{idx}] {title}\n来源: {src} · 定位: {locator}\n{content[:1500]}"
        )
        chunk_blocks.append(block)
    user_content = (
        "资料:\n\n" + "\n\n".join(chunk_blocks) + f"\n\n用户问题: {query}"
    )
    messages = [
        {"role": "system", "content": RAG_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    request_id = f"rag_{uuid.uuid4().hex[:10]}"
    try:
        result = await llm_bridge.call_llm(
            messages,
            timeout_s=30.0,
            request_id=request_id,
        )
    except llm_bridge.LLMError as exc:
        return _llm_error_response(exc)
    return {**result, "evidence_ids_ordered": ordered_ids}


@router.post("/chat/llm-fallback")
async def llm_fallback(payload: dict) -> Any:
    query = (payload.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="missing query")
    request_id = f"req_{uuid.uuid4().hex[:10]}"
    messages = [
        {"role": "system", "content": LLM_FALLBACK_SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]
    try:
        result = await llm_bridge.call_llm(
            messages,
            timeout_s=30.0,
            request_id=request_id,
        )
    except llm_bridge.LLMError as exc:
        return _llm_error_response(exc)
    return result


# ----------------------------- curate / manual entry -------------------


@router.post("/llm-capture")
async def llm_capture(payload: dict) -> dict:
    query = (payload.get("query") or "").strip()
    answer = (payload.get("answer") or "").strip()
    edited = (payload.get("edited_answer") or "").strip()
    content = edited or answer
    if not query or not content:
        raise HTTPException(status_code=400, detail="missing query or answer")
    if len(content.encode("utf-8")) > core.MAX_MANUAL_ENTRY_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"内容过长（上限 "
                f"{core.MAX_MANUAL_ENTRY_BYTES // 1024}KB）"
            ),
        )
    title_override = (payload.get("title_override") or "").strip()
    title = title_override or f"{query[:40]} · AI 兜底"
    meta = {
        "llm_generated": True,
        "llm_model": (payload.get("llm_model") or "qwenpaw"),
        "llm_provider": (payload.get("llm_provider") or "qwenpaw"),
        "user_edited": bool(edited and edited != answer),
        "source_query": query,
        "request_id": payload.get("request_id"),
        "scope_label": "AI 生成 · 运行时沉淀",
        "original_answer": (
            answer if (edited and edited != answer) else None
        ),
    }
    record = core.insert_curated_knowledge(
        title=core.clean_display_text(title),
        content=core.clean_display_text(content),
        meta=meta,
        source_scope="runtime_curated",
        source_type="document",
        note="AI 兜底沉淀",
    )
    return {**record, "meta": meta}


@router.post("/manual-entry")
async def manual_entry(payload: dict) -> dict:
    title = (payload.get("title") or "").strip()
    content = (payload.get("content") or "").strip()
    if not title or not content:
        raise HTTPException(status_code=400, detail="标题和内容都得填")
    if len(title) > 120:
        raise HTTPException(status_code=400, detail="标题不超过 120 字符")
    if len(content.encode("utf-8")) > core.MAX_MANUAL_ENTRY_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"内容过长（上限 "
                f"{core.MAX_MANUAL_ENTRY_BYTES // 1024}KB）"
            ),
        )
    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    meta = {
        "manually_entered": True,
        "source_query": (payload.get("source_query") or "").strip() or None,
        "tags": list(tags) if isinstance(tags, list) else [],
        "scope_label": "运行时沉淀",
    }
    record = core.insert_curated_knowledge(
        title=core.clean_display_text(title),
        content=core.clean_display_text(content),
        meta=meta,
        source_scope="runtime_curated",
        source_type="document",
        note="手动录入",
    )
    return {**record, "meta": meta}


# ----------------------------- builtin reload --------------------------


@router.post("/builtin-knowledge/reload")
async def builtin_reload(
    pack_id: str | None = None,
    force: bool = True,
) -> dict:
    try:
        return core.import_enabled_builtin_packs(force=force, pack_id=pack_id)
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ----------------------------- archive / metadata ----------------------


@router.post("/source-records/archive")
async def source_records_archive(payload: dict) -> dict:
    source_record_ids = payload.get("source_record_ids") or []
    reason = (payload.get("reason") or "manual archive").strip()
    return core.archive_source_records(source_record_ids, reason)


@router.post("/source-records/unarchive")
async def source_records_unarchive(payload: dict) -> dict:
    source_record_ids = payload.get("source_record_ids") or []
    return core.unarchive_source_records(source_record_ids)


@router.post("/source-records/update")
async def source_records_update(payload: dict) -> dict:
    source_record_id = payload.get("source_record_id")
    if not source_record_id:
        raise HTTPException(status_code=400, detail="missing source_record_id")
    try:
        return core.update_source_record_metadata(
            int(source_record_id),
            display_title=payload.get("display_title"),
            tags=payload.get("tags"),
            note=payload.get("note"),
            source_scope=payload.get("source_scope"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
