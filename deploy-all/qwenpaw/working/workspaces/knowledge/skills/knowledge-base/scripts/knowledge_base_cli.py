#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import uuid
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = SKILL_ROOT / "server.py"
DEFAULT_HOST = os.environ.get("KNOWLEDGE_BASE_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("KNOWLEDGE_BASE_PORT", "38427"))
DEFAULT_DATA_DIR = Path(
    os.environ.get("KNOWLEDGE_BASE_DATA_DIR", SKILL_ROOT / "data")
).expanduser()
_ENGINE = None


def engine():
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("KNOWLEDGE_BASE_DATA_DIR", str(DEFAULT_DATA_DIR))
    if str(SKILL_ROOT) not in sys.path:
        sys.path.insert(0, str(SKILL_ROOT))
    spec = importlib.util.spec_from_file_location("knowledge_base_engine_cli", SERVER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {SERVER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.init_db()
    module.reap_orphan_jobs()
    module.import_enabled_builtin_packs(force=False)
    _ENGINE = module
    return module


def create_ingest_job(path: Path) -> object:
    eng = engine()
    raw = path.read_bytes()
    filename = path.name
    source_type = eng.detect_source_type(filename, None)
    job_id = f"job_{uuid.uuid4().hex[:10]}"
    created_at = eng.now_iso()
    target = eng.UPLOAD_DIR / f"{uuid.uuid4().hex}{path.suffix}"
    target.write_bytes(raw)
    conn = eng.get_conn()
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
                eng.INGEST_STAGE_PCT["queued"],
                "queued",
                0,
                "已接收，排队中",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    eng._run_ingest_worker(job_id, str(target), filename, source_type, None)
    return eng.ingestion_progress(job_id) if hasattr(eng, "ingestion_progress") else {
        "job_id": job_id,
        "filename": filename,
        "source_type": source_type,
        "status": "completed",
    }


def query_payload(query: str, limit: int) -> object:
    return engine().build_query_response(query, {"limit": limit})


def manual_entry_payload(title: str, content: str, tags: list[str]) -> object:
    eng = engine()
    meta = {
        "manually_entered": True,
        "source_query": None,
        "tags": tags,
        "scope_label": "运行时沉淀",
    }
    return {
        **eng.insert_curated_knowledge(
            title=eng.clean_display_text(title),
            content=eng.clean_display_text(content),
            meta=meta,
            source_scope="runtime_curated",
            source_type="document",
            note="手动录入",
        ),
        "meta": meta,
    }


def ingestion_progress(job_id: str) -> object:
    eng = engine()
    conn = eng.get_conn()
    try:
        row = conn.execute("SELECT * FROM ingestion_job WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else {"detail": "job not found"}
    finally:
        conn.close()


def reindex_payload(force: bool) -> object:
    eng = engine()
    if not eng.EMBEDDING_ENABLED:
        return {
            "detail": "embedding disabled",
            "embedding": eng.embedding_status(),
        }
    conn = eng.get_conn()
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
        "embedded": eng.compute_unit_embeddings(ids),
        "force": force,
    }


def health_payload() -> object:
    eng = engine()
    return {
        "status": "ok",
        "storage": {
            "skillRoot": str(SKILL_ROOT),
            "dataDir": str(DEFAULT_DATA_DIR),
            "dbPath": str(eng.DB_PATH),
        },
        "llm": {
            "enabled": bool(eng.LLM_ENABLED),
            "provider": eng.LLM_DEFAULT_PROVIDER,
        },
        "embedding": eng.embedding_status(),
    }


def sources_payload(limit: int, include_archived: bool) -> object:
    return engine().list_source_records(
        limit=limit,
        offset=0,
        filters={},
        include_archived=include_archived,
    )


def print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Knowledge base skill CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("health")
    query_parser = sub.add_parser("query")
    query_parser.add_argument("query")
    query_parser.add_argument("--limit", type=int, default=8)

    manual_parser = sub.add_parser("manual-entry")
    manual_parser.add_argument("--title", required=True)
    manual_parser.add_argument("--content", required=True)
    manual_parser.add_argument("--tag", action="append", default=[])

    ingest_parser = sub.add_parser("ingest")
    ingest_parser.add_argument("file")

    sources_parser = sub.add_parser("sources")
    sources_parser.add_argument("--limit", type=int, default=50)
    sources_parser.add_argument("--include-archived", action="store_true")

    reindex_parser = sub.add_parser("reindex")
    reindex_parser.add_argument("--force", action="store_true")

    args = parser.parse_args()
    if args.cmd == "health":
        print_json(health_payload())
    elif args.cmd == "query":
        print_json(query_payload(args.query, args.limit))
    elif args.cmd == "manual-entry":
        print_json(manual_entry_payload(args.title, args.content, args.tag))
    elif args.cmd == "ingest":
        path = Path(args.file).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        print_json(create_ingest_job(path))
    elif args.cmd == "sources":
        print_json(sources_payload(args.limit, args.include_archived))
    elif args.cmd == "reindex":
        print_json(reindex_payload(args.force))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
