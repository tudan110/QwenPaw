# -*- coding: utf-8 -*-
"""Facade for local llama.cpp and model download management."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from ..constant import DEFAULT_LOCAL_PROVIDER_DIR

from .llamacpp import LlamaCppBackend, LlamaCppServerSetupResult
from .model_manager import LocalModelInfo as RecommendedLocalModelInfo
from .model_manager import ModelManager, DownloadSource
from .resource_policy import protect_storage

logger = logging.getLogger(__name__)


class LocalModelConfig(BaseModel):
    """Persistent local runtime settings for embedded llama.cpp."""

    access_mode: Literal["managed", "deny"] = "managed"
    allow_downloads: bool = True

    max_context_length: int = Field(
        default=65536,
        description="Maximum context length passed to llama.cpp on startup.",
        ge=32768,
    )
    port: int | None = Field(
        default=None,
        description=(
            "Optional fixed port for llama.cpp startup. Null means auto."
        ),
        ge=1,
        le=65535,
    )


class LocalModelManager:  # pylint: disable=too-many-public-methods
    """Single entry point for local runtime downloads and server control."""

    _instance: LocalModelManager | None = None

    DEFAULT_LLAMA_CPP_BASE_URL = (
        # Mirror of "https://github.com/ggml-org/llama.cpp/releases/download"
        "https://download.qwenpaw.agentscope.io/files/models/llama_cpp"
    )
    DEFAULT_LLAMA_CPP_RELEASE_TAG = "b8744"
    CONFIG_FILE_NAME = "config.json"

    def __init__(
        self,
        *,
        model_manager: ModelManager | None = None,
        llamacpp_backend: LlamaCppBackend | None = None,
    ) -> None:
        self._model_manager = model_manager or ModelManager()
        self._llamacpp_backend = llamacpp_backend or LlamaCppBackend()
        self._server_lifecycle_lock = asyncio.Lock()
        self._access_update_in_progress = False
        self._config_path = DEFAULT_LOCAL_PROVIDER_DIR / self.CONFIG_FILE_NAME
        self._config = self._load_config()

    def _load_config(self) -> LocalModelConfig:
        """Load persisted local runtime settings from disk."""
        if not self._config_path.exists():
            return LocalModelConfig()

        try:
            with open(self._config_path, "r", encoding="utf-8") as file_obj:
                payload = json.load(file_obj)
            return LocalModelConfig.model_validate(payload)
        except (OSError, ValueError, ValidationError) as exc:
            logger.warning(
                "Failed to load local model config from %s: %s",
                self._config_path,
                exc,
            )
            return LocalModelConfig(access_mode="deny")

    @staticmethod
    def _write_config_file(
        config_path,
        payload: dict[str, Any],
    ) -> None:
        """Write local runtime settings to disk in a worker thread."""
        config_path.parent.mkdir(parents=True, exist_ok=True)
        from ..governance.component_events import record, snapshot

        before = snapshot(config_path)
        if before is not None and "access_mode" not in before:
            before["access_mode"] = (
                "managed"  # Effective default before opt-in.
            )
        temp = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=config_path.parent,
                delete=False,
            ) as file_obj:
                temp = Path(file_obj.name)
                json.dump(payload, file_obj, ensure_ascii=False, indent=2)
            temp.replace(config_path)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)

        def summary(settings):
            if settings is None:
                return None
            return {
                "allow_downloads": settings.get("allow_downloads", True),
                "access_mode": (
                    "禁止受管本地运行"
                    if settings.get("access_mode") == "deny"
                    else "受管运行严格管控"
                )
            }

        record(
            "local",
            "受管本地模型策略",
            "全局",
            before,
            payload,
            visible_fields={"access_mode", "allow_downloads", "max_context_length", "port"},
            summaries=(summary(before), summary(payload)),
        )
        try:
            config_path.chmod(0o600)
        except OSError:
            pass

    async def _save_config(self) -> None:
        """Persist local runtime settings to disk without blocking the loop."""
        await asyncio.to_thread(
            self._write_config_file,
            self._config_path,
            self._config.model_dump(),
        )

    def get_config(self) -> LocalModelConfig:
        """Return a defensive copy of the current local runtime settings."""
        return self._config.model_copy(deep=True)

    async def set_access_mode(self, mode: Literal["managed", "deny"]) -> None:
        await self.set_access_policy(mode)

    async def set_access_policy(
        self, mode: Literal["managed", "deny"], *, allow_downloads: bool | None = None,
    ) -> None:
        async with self._server_lifecycle_lock:
            if allow_downloads is None:
                allow_downloads = self._config.allow_downloads
            mode_changed = mode != self._config.access_mode
            if not mode_changed and allow_downloads == self._config.allow_downloads:
                return
            if mode_changed and self.get_llamacpp_server_status().get("running"):
                raise RuntimeError("请先停止受管本地推理服务，再变更访问策略")
            active_downloads = {"pending", "downloading", "canceling"}
            if (
                self.get_model_download_progress().get("status")
                in active_downloads
                or self.get_llamacpp_download_progress().get("status")
                in active_downloads
            ):
                raise RuntimeError("请先停止本地模型下载，再变更访问策略")
            updated = self._config.model_copy(
                update={"access_mode": mode, "allow_downloads": allow_downloads},
            )
            self._access_update_in_progress = True
            try:
                await asyncio.to_thread(
                    self._write_config_file,
                    self._config_path,
                    updated.model_dump(),
                )
                self._config = updated
            finally:
                self._access_update_in_progress = False

    def _require_local_storage(self, *, download: bool = False) -> None:
        if self._access_update_in_progress:
            raise RuntimeError("本地资源访问策略正在更新，请稍后重试")
        if self._config.access_mode == "deny":
            raise RuntimeError("本地资源策略禁止受管本地模型运行或下载")
        if download and not self._config.allow_downloads:
            raise RuntimeError("本地资源策略禁止下载；仅可运行已下载的受管模型")
        try:
            protect_storage()
        except OSError as exc:
            raise RuntimeError("无法验证受管本地模型目录权限") from exc

    async def set_max_context_length(self, max_context_length: int) -> None:
        """Persist the max context length for future llama.cpp startups."""
        async with self._server_lifecycle_lock:
            self._config.max_context_length = max_context_length
            await self._save_config()

    async def set_port(self, port: int | None) -> None:
        """Persist the llama.cpp server port for future startups."""
        async with self._server_lifecycle_lock:
            self._config.port = port
            await self._save_config()

    def check_llamacpp_installation(self) -> tuple[bool, str]:
        """Return whether llama.cpp is already installed locally."""
        return self._llamacpp_backend.check_llamacpp_installation()

    def check_llamacpp_installability(self) -> tuple[bool, str]:
        """Return whether the current environment can install llama.cpp."""
        return self._llamacpp_backend.check_llamacpp_installability()

    async def start_llamacpp_download(self) -> bool:
        """Start the llama.cpp binary download task.

        Returns whether a running llama.cpp server was stopped first.
        """
        async with self._server_lifecycle_lock:
            self._require_local_storage(download=True)
            server_was_running = bool(
                self._llamacpp_backend.get_server_status().get("running"),
            )
            if server_was_running:
                await self._llamacpp_backend.shutdown_server()

            self._llamacpp_backend.download(
                self.DEFAULT_LLAMA_CPP_BASE_URL,
                self.DEFAULT_LLAMA_CPP_RELEASE_TAG,
            )
            return server_was_running

    async def has_update(self) -> bool:
        """Return whether a llama.cpp update is available for download."""
        return await self._llamacpp_backend.has_update(
            self.DEFAULT_LLAMA_CPP_RELEASE_TAG,
        )

    async def check_llamacpp_server_ready(
        self,
        timeout: float = 120.0,
    ) -> bool:
        """Return whether the llama.cpp server is ready."""
        return await self._llamacpp_backend.server_ready(timeout=timeout)

    def get_llamacpp_download_progress(self) -> dict[str, Any]:
        """Return the current llama.cpp download progress."""
        return self._llamacpp_backend.get_download_progress()

    def get_llamacpp_server_status(self) -> dict[str, Any]:
        """Return the current llama.cpp server status."""
        return self._llamacpp_backend.get_server_status()

    def is_llamacpp_server_transitioning(self) -> bool:
        """Return whether the llama.cpp server is starting or stopping."""
        return self._llamacpp_backend.is_server_transitioning()

    def cancel_llamacpp_download(self) -> None:
        """Cancel the current llama.cpp download task."""
        self._llamacpp_backend.cancel_download()

    def get_recommended_models(
        self,
    ) -> list[RecommendedLocalModelInfo]:
        """Return recommended local models for the current machine."""
        return self._model_manager.get_recommended_models()

    def is_model_downloaded(self, model_name: str) -> bool:
        """Return whether the requested model is already downloaded."""
        return self._model_manager.is_downloaded(model_name)

    def list_downloaded_models(self) -> list[RecommendedLocalModelInfo]:
        """Return all downloaded local model repositories."""
        return self._model_manager.list_downloaded_models()

    def start_model_download(
        self,
        model_id: str,
        source: DownloadSource | None = None,
    ) -> None:
        """Start downloading the requested model."""
        self._require_local_storage(download=True)
        self._model_manager.download_model(model_id, source=source)

    def get_model_download_progress(self) -> dict[str, Any]:
        """Return the current model download progress."""
        return self._model_manager.get_download_progress()

    def cancel_model_download(self) -> None:
        """Cancel the current model download task."""
        self._model_manager.cancel_download()

    def remove_downloaded_model(self, model_id: str) -> None:
        """Delete a downloaded local model by repo id or directory name."""
        self._model_manager.remove_downloaded_model(model_id)

    async def setup_server(
        self,
        model_id: str,
    ) -> LlamaCppServerSetupResult:
        """Start the llama.cpp server for the specified model."""
        async with self._server_lifecycle_lock:
            self._require_local_storage()
            model_dir = self._model_manager.get_model_dir(model_id).resolve()
            if not model_dir.is_relative_to(
                (DEFAULT_LOCAL_PROVIDER_DIR / "models").resolve()
            ):
                raise RuntimeError("模型必须位于受管本地模型目录")
            return await self._llamacpp_backend.setup_server(
                model_path=model_dir,
                model_name=model_id,
                max_context_length=self._config.max_context_length,
                port=self._config.port,
            )

    async def shutdown_server(self) -> None:
        """Stop the current llama.cpp server if it is running."""
        async with self._server_lifecycle_lock:
            await self._llamacpp_backend.shutdown_server()

    def shutdown_server_sync(self) -> None:
        """Best-effort synchronous shutdown for process teardown paths."""
        self._llamacpp_backend.shutdown_server_sync()

    @staticmethod
    def get_instance() -> LocalModelManager:
        """Return the singleton LocalModelManager instance."""
        # This is a simple module-level singleton pattern. In a more complex
        # application, you might want to use a dependency injection framework.
        if LocalModelManager._instance is None:
            LocalModelManager._instance = LocalModelManager()
        return LocalModelManager._instance
