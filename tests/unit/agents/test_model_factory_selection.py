# -*- coding: utf-8 -*-
"""Explicit knowledge-model selection must survive factory resolution."""

from unittest.mock import MagicMock

from qwenpaw.agents import model_factory
from qwenpaw.config.config import ModelSlotConfig


def test_explicit_model_slot_does_not_get_overwritten(monkeypatch):
    manager = MagicMock()
    provider = MagicMock()
    manager.get_provider.return_value = provider
    base_model = MagicMock()
    provider.get_chat_model_instance.return_value = base_model
    monkeypatch.setattr(
        model_factory.ProviderManager, "get_instance", lambda: manager
    )
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_active_chat_model",
        lambda: (_ for _ in ()).throw(
            AssertionError("Global must not be used")
        ),
    )
    monkeypatch.setattr(
        model_factory, "_create_formatter_instance", lambda model: "formatter"
    )
    monkeypatch.setattr(
        model_factory,
        "TokenRecordingModelWrapper",
        lambda provider_id, model, **kwargs: model,
    )
    monkeypatch.setattr(
        model_factory,
        "RetryChatModel",
        lambda model, **kwargs: model,
    )
    slot = ModelSlotConfig(
        provider_id="knowledge-provider", model="knowledge-model"
    )
    model, formatter = model_factory.create_model_and_formatter(
        agent_id="knowledge", model_slot=slot
    )
    manager.get_provider.assert_called_once_with("knowledge-provider")
    provider.get_chat_model_instance.assert_called_once_with("knowledge-model")
    assert model is base_model
    assert formatter == "formatter"
