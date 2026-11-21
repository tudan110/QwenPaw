# -*- coding: utf-8 -*-
"""Model selection for standalone, platform-level AI capabilities.

This is intentionally separate from Agent model routing.  It only stores a
reference to an existing provider/model pair, never provider credentials or
an Agent id.  A missing selection means platform features fall back to the
system global default model.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.governance.component_events import record_default_model
from qwenpaw.extensions.api import settings_store
from qwenpaw.extensions.runtime_data_paths import (
    SETTINGS_DB_PATH as DEFAULT_DB_PATH,
)
from qwenpaw.providers.provider_manager import ProviderManager

_NAMESPACE = "platform_ai_model"
_PROVIDER_KEY = "provider_id"
_MODEL_KEY = "model_id"

__all__ = [
    "apply_settings_update",
    "build_settings_payload",
    "get_model_slot",
]


def _normalized_selection(values: dict[str, Any]) -> tuple[str, str]:
    return (
        str(values.get(_PROVIDER_KEY) or "").strip(),
        str(values.get(_MODEL_KEY) or "").strip(),
    )


def get_model_slot(*, db_path: Path = DEFAULT_DB_PATH) -> ModelSlotConfig | None:
    """Return the configured standalone-feature model, if one is selected."""
    provider_id, model_id = _normalized_selection(
        settings_store.get_namespace(_NAMESPACE, db_path=db_path),
    )
    if not provider_id or not model_id:
        return None
    return ModelSlotConfig(provider_id=provider_id, model=model_id)


def build_settings_payload(
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, str | bool]:
    """Return the public settings payload; no credential is ever exposed."""
    slot = get_model_slot(db_path=db_path)
    return {
        "providerId": slot.provider_id if slot else "",
        "modelId": slot.model if slot else "",
        "usesGlobalDefault": slot is None,
    }


def apply_settings_update(
    body: dict[str, Any],
    *,
    manager: ProviderManager | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Save an existing provider/model reference or clear it for fallback.

    Both fields are required together.  Empty values clear the selection,
    which deliberately restores the system global default rather than
    coupling this concern to any Agent's active model.
    """
    allowed = {"providerId", "modelId"}
    unknown = set(body).difference(allowed)
    if unknown:
        raise ValueError(
            f"不支持的综合功能模型设置项：{', '.join(sorted(unknown))}"
        )
    if not allowed.issubset(body):
        raise ValueError("必须同时选择模型提供商和模型")

    provider_id = str(body.get("providerId") or "").strip()
    model_id = str(body.get("modelId") or "").strip()
    old_slot = get_model_slot(db_path=db_path)
    before = old_slot.model_dump() if old_slot else None
    if not provider_id and not model_id:
        settings_store.replace_namespace(_NAMESPACE, {}, db_path=db_path)
        record_default_model("Portal 综合功能", before, None)
        return
    if not provider_id or not model_id:
        raise ValueError("必须同时选择模型提供商和模型")

    resolved_manager = manager or ProviderManager.get_instance()
    provider = resolved_manager.get_provider(provider_id)
    if provider is None:
        raise ValueError(f"模型提供商“{provider_id}”不存在")
    if not provider.has_model(model_id):
        raise ValueError(f"模型“{model_id}”在提供商“{provider_id}”中不存在")
    settings_store.set_values(
        _NAMESPACE,
        {_PROVIDER_KEY: provider_id, _MODEL_KEY: model_id},
        db_path=db_path,
    )
    record_default_model(
        "Portal 综合功能",
        before,
        {"provider_id": provider_id, "model": model_id},
    )
