# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for permanent source deletion (knowledge_base.delete_sources)."""

import sys
from pathlib import Path

import pytest

KNOWLEDGE_BASE_SKILL_ROOT = (
    Path(__file__).resolve().parents[4]
    / "deploy-all"
    / "qwenpaw"
    / "working"
    / "workspaces"
    / "knowledge"
    / "skills"
    / "knowledge-base"
)
if str(KNOWLEDGE_BASE_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(KNOWLEDGE_BASE_SKILL_ROOT))


from qwenpaw.extensions.integrations import knowledge_base  # noqa: E402


@pytest.fixture()
def kb_env(tmp_path, monkeypatch):
    """Bootstrap the knowledge engine against an isolated temp data dir."""
    data_dir = tmp_path / "kbdata"
    monkeypatch.setenv(
        "QWENPAW_KNOWLEDGE_BASE_SKILL_ROOT",
        str(KNOWLEDGE_BASE_SKILL_ROOT),
    )
    monkeypatch.setenv("QWENPAW_KNOWLEDGE_BASE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("KNOWLEDGE_BASE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("KNOWLEDGE_BASE_EMBEDDING_ENABLED", "false")
    monkeypatch.setattr(knowledge_base, "_ENGINE_READY", False)

    from core import db as kb_db  # noqa: WPS433

    kb_db.close_thread_connection()
    try:
        knowledge_base._ensure_engine()
    except (RuntimeError, ImportError) as exc:  # sqlite-vec not loadable
        pytest.skip(f"knowledge engine unavailable in this env: {exc}")

    yield kb_db

    kb_db.close_thread_connection()
    monkeypatch.setattr(knowledge_base, "_ENGINE_READY", False)


def _create_doc(kb_db, *, storage_file: Path | None = None) -> int:
    result = knowledge_base.manual_entry(
        {
            "title": "割接步骤",
            "content": "网络割接需要先做配置备份，再执行变更。",
        },
    )
    doc_id = int(result["id"])
    if storage_file is not None:
        storage_file.parent.mkdir(parents=True, exist_ok=True)
        storage_file.write_bytes(b"original upload")
        with kb_db.connect() as conn:
            conn.execute(
                "UPDATE document SET storage_path=? WHERE id=?",
                (str(storage_file), doc_id),
            )
    return doc_id


def _counts(kb_db, doc_id: int) -> dict:
    with kb_db.connect() as conn:
        doc = conn.execute(
            "SELECT COUNT(*) AS n FROM document WHERE id=?",
            (doc_id,),
        ).fetchone()["n"]
        parents = conn.execute(
            "SELECT COUNT(*) AS n FROM parent_chunk WHERE document_id=?",
            (doc_id,),
        ).fetchone()["n"]
        children = conn.execute(
            "SELECT COUNT(*) AS n FROM child_chunk WHERE document_id=?",
            (doc_id,),
        ).fetchone()["n"]
    return {"doc": doc, "parents": parents, "children": children}


def test_delete_removes_rows_and_upload_file(kb_env, tmp_path):
    storage = tmp_path / "kbdata" / "uploads" / "abc.txt"
    doc_id = _create_doc(kb_env, storage_file=storage)
    before = _counts(kb_env, doc_id)
    assert before["doc"] == 1 and before["children"] >= 1
    assert storage.exists()

    result = knowledge_base.delete_sources({"source_record_ids": [doc_id]})

    assert result["deleted"] == 1
    assert result["ids"] == [doc_id]
    assert result["removed_files"] == 1
    after = _counts(kb_env, doc_id)
    assert after == {"doc": 0, "parents": 0, "children": 0}
    assert not storage.exists()


def test_delete_is_permanent_not_archived(kb_env):
    doc_id = _create_doc(kb_env)
    knowledge_base.delete_sources({"source_record_ids": [doc_id]})

    # unarchive must NOT bring it back (it is gone, not flagged)
    knowledge_base.unarchive_sources({"source_record_ids": [doc_id]})
    assert _counts(kb_env, doc_id)["doc"] == 0


def test_delete_never_touches_files_outside_data_dir(kb_env, tmp_path):
    outside = tmp_path / "outside" / "precious.txt"
    doc_id = _create_doc(kb_env, storage_file=outside)

    result = knowledge_base.delete_sources({"source_record_ids": [doc_id]})

    assert result["deleted"] == 1
    assert result["removed_files"] == 0
    assert outside.exists()  # safety: file outside data dir is untouched


def test_delete_with_unknown_or_bad_ids_is_noop(kb_env):
    result = knowledge_base.delete_sources(
        {"source_record_ids": ["abc", None, 999999]},
    )
    assert result["deleted"] == 0
    assert result["removed_files"] == 0


def test_delete_accepts_camel_case_payload(kb_env):
    doc_id = _create_doc(kb_env)
    result = knowledge_base.delete_sources({"sourceRecordIds": [doc_id]})
    assert result["deleted"] == 1


def test_guarded_delete_binds_account_scope_target_and_one_use(kb_env, monkeypatch):
    from fastapi import HTTPException
    from qwenpaw.extensions.integrations import knowledge_source_control as control

    monkeypatch.setenv("QWENPAW_DELETE_OPS_DISABLED", "false")
    doc = _create_doc(kb_env)
    other_doc = _create_doc(kb_env)
    preview = control.prepare("admin-session-a", "admin-a", doc)
    token = preview["confirmation_token"]
    assert preview["unit_count"] > 0
    with pytest.raises(HTTPException, match="409"):
        control.decide("admin-session-b", doc, token, confirm=True, phrase="确认删除")
    with pytest.raises(HTTPException, match="409"):
        control.decide("admin-session-a", other_doc, token, confirm=True, phrase="确认删除")
    with pytest.raises(HTTPException, match="400"):
        control.decide("admin-session-a", doc, token, confirm=True, phrase="确认")
    assert _counts(kb_env, doc)["doc"] == 1
    result = control.decide("admin-session-a", doc, token, confirm=True, phrase="确认删除")
    assert result["status"] == "deleted"
    with pytest.raises(HTTPException, match="409"):
        control.decide("admin-session-a", doc, token, confirm=True, phrase="确认删除")
    assert _counts(kb_env, doc) == {"doc": 0, "parents": 0, "children": 0}
    assert _counts(kb_env, other_doc)["doc"] == 1
    entry = control.recent()[0]
    assert entry["source_id"] == doc and entry["status"] == "deleted"
    assert entry["subject"] == "admin-a" and entry["pid"] > 0
    assert token not in str(entry)


def test_archive_cancellation_restore_and_global_delete_block(kb_env, monkeypatch):
    from fastapi import HTTPException
    from qwenpaw.extensions.integrations import knowledge_source_control as control

    monkeypatch.setenv("QWENPAW_DELETE_OPS_DISABLED", "true")
    doc = _create_doc(kb_env)
    with pytest.raises(HTTPException, match="403"):
        control.prepare("admin", "admin-a", doc)
    token = control.prepare("admin", "admin-a", doc, operation="archive")["confirmation_token"]
    assert control.decide("admin", doc, token, confirm=False, operation="archive")["status"] == "cancelled"
    assert knowledge_base.source_detail(doc)["unit_count"] > 0
    token = control.prepare("admin", "admin-a", doc, operation="archive")["confirmation_token"]
    assert control.decide("admin", doc, token, confirm=True, phrase="确认归档", operation="archive")["status"] == "archived"
    with pytest.raises(LookupError, match="archived"):
        knowledge_base.source_detail(doc)
    assert knowledge_base.source_detail(doc, include_archived=True)["archived_at"]
    knowledge_base.unarchive_sources({"source_record_ids": [doc]})
    assert knowledge_base.source_detail(doc)["unit_count"] > 0
    assert [x["status"] for x in control.recent()] == ["archived", "cancelled"]


def test_guarded_archive_rejects_expired_or_changed_source(kb_env, monkeypatch):
    from fastapi import HTTPException
    from qwenpaw.extensions.integrations import knowledge_source_control as control

    doc = _create_doc(kb_env)
    now = control.time.time()
    token = control.prepare("admin", "admin-a", doc, operation="archive")["confirmation_token"]
    with monkeypatch.context() as timed:
        timed.setattr(control.time, "time", lambda: now + 185)
        with pytest.raises(HTTPException, match="409"):
            control.decide("admin", doc, token, confirm=True, phrase="确认归档", operation="archive")
    token = control.prepare("admin", "admin-a", doc, operation="archive")["confirmation_token"]
    knowledge_base.archive_sources({"source_record_ids": [doc]})
    with pytest.raises(HTTPException, match="409"):
        control.decide("admin", doc, token, confirm=True, phrase="确认归档", operation="archive")
    assert [x["status"] for x in control.recent()] == ["changed", "expired"]


def test_controlled_document_publishes_masked_searchable_copy_once(kb_env, monkeypatch):
    from core import retrieval
    from fastapi.responses import JSONResponse
    from qwenpaw.app.routers import controlled_documents as routes
    from qwenpaw.extensions.api import controlled_documents as store, text_privacy

    monkeypatch.setattr(store, "STORE_DIR", knowledge_base.data_dir() / "controlled-test")
    monkeypatch.setattr(text_privacy, "load_policy", lambda: text_privacy.PrivacyPolicy(knowledge="block"))
    monkeypatch.setattr(retrieval, "HYDE_ENABLED", False)
    monkeypatch.setenv("KNOWLEDGE_BASE_RERANKER", "heuristic")
    owner = store.Actor("test", "admin", True)
    other = store.Actor("test", "other-admin", True)
    body = routes.DocumentInput(title="取证答复操作手册", content="星云巡检基准为双机切换。联系号码 13800138000。")
    item = routes.create_document(body, owner)
    preview = routes.read_document(item["id"], owner)
    assert preview["masked"] and "13800138000" not in preview["content"]
    approval = routes.PublishInput(reviewed_for_sharing=True)
    refused = routes.publish_to_knowledge_base(item["id"], approval, other)
    assert isinstance(refused, JSONResponse) and refused.status_code == 404
    published = routes.publish_to_knowledge_base(item["id"], approval, owner)
    duplicate = routes.publish_to_knowledge_base(item["id"], approval, owner)
    assert not published["already_published"] and duplicate["already_published"]
    assert published["source_id"] == duplicate["source_id"]
    units = str(knowledge_base.source_detail(published["source_id"])["units"])
    assert "星云巡检" in units and "13800138000" not in units and "手机" in units
    search = knowledge_base.query_knowledge({"query": "星云巡检"})
    excerpts = [
        hit["chunk_text"] for hit in search["relevant_evidence"]
        if hit["citation"]["source_label"] == body.title
    ]
    assert any("双机切换" in excerpt and "手机" in excerpt for excerpt in excerpts)
    assert "13800138000" not in str(search)
    with store.connection(owner) as conn:
        assert "13800138000" in store.owned_document(conn, owner, item["id"])["content"]
