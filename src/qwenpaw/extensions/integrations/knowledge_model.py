# -*- coding: utf-8 -*-
"""Deterministic knowledge model resolution without changing configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qwenpaw.config.config import ModelSlotConfig, load_agent_config
from qwenpaw.providers import ProviderManager


class KnowledgeModelUnavailable(RuntimeError):
    """Model enhancement is unavailable; basic retrieval may still work."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class KnowledgeModelSelection:
    slot: ModelSlotConfig
    source: str
    provider_name: str
    model_name: str

    def metadata(self) -> dict[str, str]:
        return {
            "provider": self.slot.provider_id,
            "provider_name": self.provider_name,
            "model": self.slot.model,
            "model_name": self.model_name,
            "model_label": f"{self.provider_name} / {self.model_name}",
            "model_source": self.source,
        }


def resolve_knowledge_model(
    agent_id: str = "knowledge",
) -> KnowledgeModelSelection:
    """Use agent selection, then the global default; never borrow gateway."""
    try:
        config = load_agent_config(agent_id)
        slot = config.active_model
        manager = ProviderManager.get_instance()
        source = "agent"
        if not slot or not slot.provider_id or not slot.model:
            slot = manager.get_active_model()
            source = "global"
        if not slot or not slot.provider_id or not slot.model:
            raise KnowledgeModelUnavailable("model_not_configured")
        provider = manager.get_provider(slot.provider_id)
        if provider is None:
            raise KnowledgeModelUnavailable("provider_not_found")
        model_name = slot.model
        models: list[Any] = [
            *getattr(provider, "models", []),
            *getattr(provider, "extra_models", []),
        ]
        for item in models:
            if getattr(item, "id", None) == slot.model:
                model_name = getattr(item, "name", None) or slot.model
                break
        return KnowledgeModelSelection(
            slot=slot,
            source=source,
            provider_name=getattr(provider, "name", None) or slot.provider_id,
            model_name=model_name,
        )
    except KnowledgeModelUnavailable:
        raise
    except (OSError, ValueError) as exc:
        raise KnowledgeModelUnavailable("model_configuration_invalid") from exc
