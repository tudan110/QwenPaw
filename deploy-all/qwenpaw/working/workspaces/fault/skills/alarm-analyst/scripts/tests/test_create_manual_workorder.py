import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SCRIPT_DIR / "create_manual_workorder.py"


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


WORKORDER_MODULE = _load_module("alarm_manual_workorder_test", SCRIPT_PATH)


def test_build_workorder_payload_marks_ai_created_and_keeps_suggestions():
    args = SimpleNamespace(
        chat_id="chat-1",
        res_id="3094",
        metric_type="mysql",
        alarm_id="alarm-001",
        alarm_title="数据库锁异常",
        visible_content="数据库锁异常（db_mysql_001 10.43.150.186）",
        device_name="db_mysql_001",
        manage_ip="10.43.150.186",
        asset_id="db_mysql_001",
        level="critical",
        status="active",
        event_time="2026-04-20 15:00:00",
        analysis_summary="AI 已完成根因分析，自动创建人工处置工单",
        root_cause="疑似 MySQL 锁等待 / 长事务 / 死锁",
        suggestion=["排查长事务", "检查阻塞链"],
        suggestions_json='["检查阻塞链", "确认是否存在热点更新"]',
        ticket_title="",
        ticket_priority="P1",
        ticket_category="database-lock",
        ticket_source="portal-fault-disposal-ai",
        ticket_external_system="manual-workorder",
    )

    payload = WORKORDER_MODULE.build_workorder_payload(args)

    assert payload["chatId"] == "chat-1"
    assert payload["ticket"]["source"] == "portal-fault-disposal-ai"
    assert payload["ticket"]["title"].startswith("AI创建")
    assert payload["analysis"]["suggestions"] == [
        "排查长事务",
        "检查阻塞链",
        "确认是否存在热点更新",
    ]


def test_build_workorder_payload_requires_suggestions():
    args = SimpleNamespace(
        chat_id="chat-1",
        res_id="3094",
        metric_type="mysql",
        alarm_id="",
        alarm_title="数据库锁异常",
        visible_content="",
        device_name="",
        manage_ip="",
        asset_id="",
        level="",
        status="active",
        event_time="",
        analysis_summary="",
        root_cause="",
        suggestion=[],
        suggestions_json="",
        ticket_title="",
        ticket_priority="P1",
        ticket_category="database-lock",
        ticket_source="portal-fault-disposal-ai",
        ticket_external_system="manual-workorder",
    )

    with pytest.raises(ValueError, match="至少提供一条处置建议"):
        WORKORDER_MODULE.build_workorder_payload(args)


@patch.dict(
    "os.environ",
    {
        "INOE_API_BASE_URL": "http://example.com",
        "INOE_API_TOKEN": "token-123",
    },
    clear=False,
)
def test_create_manual_workorder_posts_expected_request():
    payload = {
        "chatId": "chat-1",
        "resId": "3094",
        "metricType": "mysql",
        "alarm": {"title": "数据库锁异常"},
        "analysis": {"summary": "AI 已完成根因分析，自动创建人工处置工单", "suggestions": ["排查长事务"]},
        "ticket": {"title": "AI创建 · 数据库锁异常人工处置", "source": "portal-fault-disposal-ai"},
    }
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "code": 200,
        "msg": None,
        "data": {"procInsId": "proc-1", "taskId": "task-1"},
    }

    with patch.object(WORKORDER_MODULE.requests, "post", return_value=response) as mock_post:
        result = WORKORDER_MODULE.create_manual_workorder(payload, timeout_seconds=12)

    assert result["data"]["procInsId"] == "proc-1"
    kwargs = mock_post.call_args.kwargs
    assert kwargs["json"] == payload
    assert kwargs["timeout"] == 12
    assert kwargs["headers"]["Authorization"] == "token-123"
    assert kwargs["headers"]["Content-Type"] == "application/json;charset=utf-8"
    assert kwargs["headers"]["SerialNo"]


def test_format_markdown_result_contains_ai_marker():
    markdown = WORKORDER_MODULE.format_markdown_result(
        {
            "resId": "3094",
            "alarm": {"title": "数据库锁异常"},
            "analysis": {
                "summary": "AI 已完成根因分析，自动创建人工处置工单",
                "rootCause": "疑似 MySQL 锁等待 / 长事务 / 死锁",
                "suggestions": ["排查长事务"],
            },
            "ticket": {"title": "AI创建 · 数据库锁异常人工处置", "source": "portal-fault-disposal-ai"},
        },
        {"data": {"procInsId": "proc-1", "taskId": "task-1"}},
    )

    assert "AI 创建处置工单结果" in markdown
    assert "portal-fault-disposal-ai" in markdown
    assert "排查长事务" in markdown
