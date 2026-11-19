"""Deployment contracts for skills that support MCP and local scripts."""

from pathlib import Path

import pytest

WORKSPACES = Path(__file__).resolve().parents[2] / "working/workspaces"
SKILLS = {
    "real-alarm": ("gateway", "query", "fault"),
    "zgops-cmdb": ("gateway", "query", "fault", "inspection", "resource"),
    "order-workflow": ("gateway", "order"),
    "inspection-analyst": ("gateway", "inspection"),
    "resource-insight-query": ("gateway", "query", "resource"),
    "monitoring-overview-query": ("gateway", "query"),
    "web-availability-monitor": ("gateway", "inspection"),
    "alarm-analyst": ("fault",),
}
COPIES = [
    (workspace, skill)
    for skill, workspaces in SKILLS.items()
    for workspace in workspaces
]


@pytest.mark.parametrize("workspace,skill", COPIES)
def test_deployed_skill_obeys_request_route(workspace, skill):
    text = (WORKSPACES / workspace / "skills" / skill / "SKILL.md").read_text()
    assert "Skill execution routes" in text
    assert "不先尝试 MCP" in text
    assert "mcp_disabled" in text and "mcp_not_configured" in text
    assert "`unavailable`" in text and "`blocked`" in text
    assert "不得通过脚本或跨智能体绕过" in text
    assert "写操作已发送但结果不明时，不用脚本重复提交" in text
    assert "本工作区已启用" not in text
    assert "MCP Driver 未加载" not in text


@pytest.mark.parametrize("workspace", ("gateway", "inspection"))
def test_script_inspection_keeps_read_only_boundary(workspace):
    text = (
        WORKSPACES / workspace / "skills/inspection-analyst/SKILL.md"
    ).read_text()
    assert "python3 scripts/inspect_resource_metrics.py --no-notify" in text
    assert "不得把切换通道当作通知授权" in text
    assert "才按其现有配置处理通知" not in text


def test_mixed_routes_do_not_use_all_in_one_alarm_script():
    text = (WORKSPACES / "fault/skills/alarm-analyst/SKILL.md").read_text()
    assert "所有涉及能力均须允许脚本" in text
    assert "禁止聚合脚本越过其他能力路由" in text


@pytest.mark.parametrize("workspace", ("gateway", "query"))
def test_monitoring_uses_resource_driver_name(workspace):
    text = (
        WORKSPACES / workspace / "skills/monitoring-overview-query/SKILL.md"
    ).read_text()
    assert "`resource` MCP Server" in text
    assert "monitor-overview MCP Driver" not in text
