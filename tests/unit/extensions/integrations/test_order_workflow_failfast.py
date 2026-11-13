# -*- coding: utf-8 -*-
"""T-012: 大屏工单取数快速失败——短超时 + 禁 curl 兜底。

覆盖两件事：
1. integrations 层 ``query_order_workorders`` 的新可选参数只在显式传入时
   覆盖 client config；默认路径保留环境参数并规范化 ferry 网关入口。
2. 大屏 ``fetch_workorders`` 走的是短超时（6s）+ 禁 curl 兜底的路径。
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from qwenpaw.extensions.integrations import order_workflow


@dataclass
class _FakeConfig:
    """镜像真实 OrderWorkflowConfig 里本任务关心的两个字段。"""

    timeout_seconds: int = 20
    enable_curl_fallback: bool = False
    # 额外字段用于验证「只改这两个、其它保持 from_env() 原样」。
    base_url: str = "http://example.invalid"

    @classmethod
    def from_env(cls) -> "_FakeConfig":
        # from_env 的默认基线：20s、curl 兜底关。
        return cls(timeout_seconds=20, enable_curl_fallback=False)


class _FakeClient:
    """记录构造时拿到的 config；镜像真实 client 的 ``config or from_env()``。"""

    captured: list[Any] = []

    def __init__(self, config: Any = None) -> None:
        self.config = config or _FakeConfig.from_env()
        _FakeClient.captured.append(self.config)

    def get_workorder_stats(self) -> dict[str, Any]:
        return {"code": 200, "data": {}}

    def list_todo_workorders(
        self, *, page_num: int = 1, page_size: int = 10
    ) -> dict[str, Any]:
        return {"total": 0, "rows": []}


@pytest.fixture
def fake_module(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    _FakeClient.captured = []
    module = SimpleNamespace(
        OrderWorkflowConfig=_FakeConfig,
        OrderWorkflowClient=_FakeClient,
    )
    monkeypatch.setattr(
        order_workflow, "_load_order_client_module", lambda: module
    )
    # 别在测试里真去加载 secrets 文件（query_order_workorders 内是局部
    # 导入，打在模块属性上即可被拿到）。
    import qwenpaw.extensions.integrations.working_secrets as ws

    monkeypatch.setattr(ws, "ensure_working_secrets_loaded", lambda: None)
    return module


class TestBuildOrderClientConfig:
    def test_default_path_normalizes_gateway(
        self, fake_module: SimpleNamespace
    ) -> None:
        result = order_workflow._build_order_client_config(
            fake_module,
            timeout_seconds=None,
            disable_curl_fallback=False,
        )
        assert result.base_url == "http://example.invalid/ferry"
        assert result.timeout_seconds == _FakeConfig.from_env().timeout_seconds
        assert (
            result.enable_curl_fallback
            == _FakeConfig.from_env().enable_curl_fallback
        )

    def test_overrides_only_named_fields(
        self, fake_module: SimpleNamespace
    ) -> None:
        config = order_workflow._build_order_client_config(
            fake_module,
            timeout_seconds=6,
            disable_curl_fallback=True,
        )
        assert config is not None
        assert config.timeout_seconds == 6
        assert config.enable_curl_fallback is False
        assert config.base_url == "http://example.invalid/ferry"


class TestQueryOrderWorkorders:
    def test_default_path_uses_from_env(
        self, fake_module: SimpleNamespace
    ) -> None:
        # The wrapper also normalizes legacy gateway roots to the ferry API.
        order_workflow.query_order_workorders(limit=5)
        assert len(_FakeClient.captured) == 1
        assert _FakeClient.captured[0] == _FakeConfig(
            base_url="http://example.invalid/ferry"
        )

    def test_big_screen_values_shorten_timeout_and_disable_curl(
        self, fake_module: SimpleNamespace
    ) -> None:
        order_workflow.query_order_workorders(
            limit=5,
            timeout_seconds=6,
            disable_curl_fallback=True,
        )
        assert len(_FakeClient.captured) == 1
        captured = _FakeClient.captured[0]
        assert captured.timeout_seconds == 6
        assert captured.enable_curl_fallback is False


class TestFetchWorkordersPath:
    def test_fetch_workorders_passes_failfast_kwargs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """大屏取数入口必须传 6s 超时 + 禁 curl 兜底。"""
        from qwenpaw.extensions.ai_big_screen.capabilities import descriptors

        captured: dict[str, Any] = {}

        def _fake_query(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {
                "source": "live",
                "total": 1,
                "items": [{"id": "wo-1", "title": "磁盘告警工单"}],
                "stats": {"todo": 1},
            }

        monkeypatch.setattr(
            order_workflow, "query_order_workorders", _fake_query
        )
        descriptors.fetch_workorders({"limit": 5})
        assert captured.get("timeout_seconds") == 6
        assert captured.get("disable_curl_fallback") is True
