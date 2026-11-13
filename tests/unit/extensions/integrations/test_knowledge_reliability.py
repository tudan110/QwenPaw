# -*- coding: utf-8 -*-
"""Knowledge model resolution and optional enhancement degradation."""

import sys
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.extensions.integrations import knowledge_base, knowledge_model

ROOT = Path(__file__).resolve().parents[4]
SKILL = ROOT / (
    "deploy-all/qwenpaw/working/workspaces/knowledge/skills/knowledge-base"
)
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from providers import llm  # noqa: E402
from domain import query_expansion  # noqa: E402
from retrieval import rerank  # noqa: E402
from core import db  # noqa: E402


@pytest.fixture
def model_env(monkeypatch):
    config = SimpleNamespace(active_model=None)
    manager = MagicMock()
    manager.get_active_model.return_value = None
    manager.get_provider.return_value = SimpleNamespace(
        name="Fixture Provider", models=[], extra_models=[]
    )
    monkeypatch.setattr(
        knowledge_model, "load_agent_config", lambda agent_id: config
    )
    monkeypatch.setattr(
        knowledge_model.ProviderManager, "get_instance", lambda: manager
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    return config, manager


def test_model_resolution_does_not_borrow_gateway_or_write_config(model_env):
    config, manager = model_env
    global_slot = ModelSlotConfig(provider_id="fixture", model="global")
    manager.get_active_model.return_value = global_slot
    selection = knowledge_model.resolve_knowledge_model()
    assert selection.source == "global"
    assert config.active_model is None
    config.active_model = ModelSlotConfig(provider_id="fixture", model="own")
    assert knowledge_model.resolve_knowledge_model().source == "agent"
    assert knowledge_model.resolve_knowledge_model().slot.model == "own"
    manager.get_provider.return_value = None
    with pytest.raises(knowledge_model.KnowledgeModelUnavailable) as error:
        knowledge_model.resolve_knowledge_model()
    assert error.value.reason == "provider_not_found"


def test_missing_model_is_not_reported_available(model_env):
    assert llm.is_available("qwenpaw_active") is False
    assert llm.model_status()["reason"] == "model_not_configured"
    with pytest.raises(llm.LLMNotConfigured):
        llm._call_qwenpaw_active([{"role": "user", "content": "query"}])


@pytest.mark.parametrize("phase", ["create", "call", "stream"])
def test_model_errors_at_every_phase_are_normalized(
    model_env, monkeypatch, phase
):
    from qwenpaw.agents import model_factory

    config, _ = model_env
    config.active_model = ModelSlotConfig(provider_id="fixture", model="own")

    async def chunks():
        raise httpx.ReadTimeout("private upstream detail")
        yield

    async def model(messages):
        assert messages[0].role == "user"
        if phase == "call":
            raise httpx.ReadTimeout("private upstream detail")
        return chunks()

    def create(**kwargs):
        assert kwargs["model_slot"].model == "own"
        if phase == "create":
            raise RuntimeError("private provider detail")
        return model, None

    monkeypatch.setattr(model_factory, "create_model_and_formatter", create)
    with pytest.raises(llm.LLMError) as error:
        llm._call_qwenpaw_active([{"role": "user", "content": "query"}])
    assert "private" not in str(error.value)
    assert error.value.reason == (
        "server_error" if phase == "create" else "timeout"
    )


def test_success_reports_actual_model_and_uses_typed_messages(
    model_env, monkeypatch
):
    from agentscope.message import Msg, TextBlock
    from qwenpaw.agents import model_factory

    config, _ = model_env
    config.active_model = ModelSlotConfig(provider_id="fixture", model="own")

    async def model(messages):
        assert all(isinstance(message, Msg) for message in messages)
        return SimpleNamespace(content=[TextBlock(text="real answer")])

    monkeypatch.setattr(
        model_factory,
        "create_model_and_formatter",
        lambda **kwargs: (model, None),
    )
    result = llm._call_qwenpaw_active([{"role": "user", "content": "query"}])
    assert result["answer"] == "real answer"
    assert result["model"] == "own"
    assert result["model_source"] == "agent"


def test_hyde_unavailable_is_observable(model_env):
    diagnostic = {}
    assert (
        query_expansion.generate_hyde("MySQL", diagnostic=diagnostic) is None
    )
    assert diagnostic["hyde_degraded_reason"] == "model_not_configured"


def test_reranker_failure_preserves_all_candidates(monkeypatch):
    monkeypatch.setattr(llm, "first_available", lambda *args: "qwenpaw_active")

    def fail(*args, **kwargs):
        raise llm.LLMAuthError("model authentication failed")

    monkeypatch.setattr(llm, "call_llm", fail)
    monkeypatch.setattr(rerank.LLMReranker, "MAX_INPUT_CANDIDATES", 1)
    candidates = [
        rerank.RerankInput(
            chunk_id=i,
            parent_id=i,
            rrf_score=0.1 * i,
            sparse_score=1,
            dense_score=None,
            sources={"sparse"},
            child_content="MySQL slow query",
            parent_content="real evidence",
            section_path="MySQL",
            locator="section",
            filename="fixture.md",
            source_scope="runtime_curated",
        )
        for i in range(1, 4)
    ]
    result = rerank.LLMReranker().rerank("MySQL", candidates, top_k=3)
    assert {item.chunk_id for item in result} == {1, 2, 3}
    assert all(
        item.diagnostic["degraded_reason"] == "model_auth_failed"
        for item in result
    )


@pytest.fixture
def kb_db(tmp_path, monkeypatch, model_env):
    monkeypatch.setenv("KNOWLEDGE_BASE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KNOWLEDGE_BASE_EMBEDDING_ENABLED", "false")
    monkeypatch.setenv("KNOWLEDGE_BASE_RERANKER", "llm")
    monkeypatch.setattr(knowledge_base, "_ensure_engine", lambda: None)
    from providers import embedding

    monkeypatch.setattr(embedding, "is_available", lambda: False)
    db.close_thread_connection()
    db.init_db()
    try:
        yield db
    finally:
        db.close_thread_connection()


def test_real_evidence_survives_missing_model_and_no_match_is_separate(kb_db):
    document = knowledge_base.manual_entry(
        {
            "title": "MySQL slowqueryfixture",
            "content": "# MySQL slowqueryfixture\n"
            "MySQL slowqueryfixture requires read-only process inspection.",
        }
    )
    result = knowledge_base.query_knowledge(
        {"query": "MySQL slowqueryfixture"}
    )
    assert result["relevant_evidence"]
    assert result["flags"]["degraded"] is True
    assert result["flags"]["insufficient_evidence"] is False
    assert "process inspection" in result["relevant_evidence"][0]["chunk_text"]
    assert result["diagnostic"]["degraded_reasons"]["hyde"] == (
        "model_not_configured"
    )
    empty = knowledge_base.query_knowledge({"query": "nomatchunique314159"})
    assert empty["flags"]["insufficient_evidence"] is True
    assert empty["relevant_evidence"] == []
    assert document["id"]


def test_health_reports_effective_model_without_claiming_connectivity(
    kb_db, model_env
):
    config, manager = model_env
    manager.get_active_model.return_value = ModelSlotConfig(
        provider_id="fixture", model="global"
    )
    health = knowledge_base.health()
    assert health["llm"]["enabled"] is True
    assert health["llm"]["model"] == "global"
    assert health["llm"]["model_source"] == "global"
    assert health["llm"]["connectivity_checked"] is False
    assert config.active_model is None


def test_health_honors_existing_deepseek_enhancement_fallback(
    kb_db, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-only-key")
    health = knowledge_base.health()
    assert health["llm"]["enabled"] is True
    assert health["llm"]["provider"] == "deepseek"
    assert health["llm"]["model_source"] == "environment"
    assert "fixture-only-key" not in str(health)


async def test_synthesis_returns_explicit_unavailable_not_fake_answer(
    kb_db,
):
    result = await knowledge_base.synthesize_answer(
        {"query": "MySQL", "evidence_ids": []}
    )
    assert result["skipped"] is True
    assert result["reason"] == "model_not_configured"
    assert result["answer"] == ""


def test_query_failure_is_not_converted_to_empty_evidence(monkeypatch):
    from qwenpaw.extensions.api import portal_backend

    def fail(payload):
        raise RuntimeError("private store detail")

    monkeypatch.setattr(knowledge_base, "query_knowledge", fail)
    response = portal_backend.query_knowledge_base({"query": "fixture"})
    assert response.status_code == 503
    body = json.loads(response.body)
    assert body["code"] == "KNOWLEDGE_RETRIEVAL_UNAVAILABLE"
    assert isinstance(body["detail"], str)
    assert body["occurred_at"]
    assert "private" not in response.body.decode()
