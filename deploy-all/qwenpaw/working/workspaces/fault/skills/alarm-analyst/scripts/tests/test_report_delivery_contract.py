import importlib.util
import re
from pathlib import Path
from unittest.mock import Mock

import pytest

from qwenpaw.extensions.api.alarm_analyst_card_service import (
    build_alarm_analyst_card,
    extract_display_fields,
    is_alarm_analyst_card_candidate,
)

SKILL_DIR = Path(__file__).resolve().parents[2]
FAULT_DIR = SKILL_DIR.parents[1]
PROTOCOL = (SKILL_DIR / "references/portal-card-protocol.md").read_text(
    encoding="utf-8"
)
REPORT_MATCH = re.search(r"```md\n([\s\S]*?)\n```", PROTOCOL)
assert REPORT_MATCH is not None
REPORT = REPORT_MATCH.group(1)
MARKER = "# PORTAL ALARM ANALYST CARD MODE"
DOWNLOAD = "[下载报告：分析报告](/api/portal/agents/fault/reports/example.md)"

SPEC = importlib.util.spec_from_file_location(
    "alarm_delivery_notification",
    SKILL_DIR / "scripts/send_analysis_report.py",
)
assert SPEC is not None and SPEC.loader is not None
notification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notification)


def build_card(report):
    assert is_alarm_analyst_card_candidate(
        employee_id="fault", report_markdown=report, process_blocks=[]
    )
    return build_alarm_analyst_card(
        chat_id="offline-delivery-test",
        message_id="offline-report",
        employee_id="fault",
        report_markdown=report,
        process_blocks=[],
    )


def assert_complete_report(report):
    assert report.startswith(MARKER + "\n\n---\n")
    assert len(report) <= 4500
    for heading in (
        "告警基础信息",
        "数据查询与整理",
        "异常关联分析",
        "根因判断",
        "影响范围",
        "知识匹配与适用性",
        "处置建议",
        "异常指标",
        "自动化执行结果",
        "恢复验证与状态回写",
        "分析依据与待确认事项",
        "📊 总结",
    ):
        assert "## " + heading in report
    assert re.search(r"^- 置信度：\d+(?:\.\d+)?%$", report, re.MULTILINE)
    assert report.splitlines()[-1].startswith("- 通知状态：")
    assert "\n## 通知推送" not in report


def replace_section(report, heading, content):
    pattern = rf"(## {re.escape(heading)}\n)[\s\S]*?(?=\n## |\Z)"
    updated, count = re.subn(pattern, lambda m: m[1] + content + "\n", report)
    assert count == 1
    return updated


def test_ordinary_analysis_template_is_inline_complete_card_without_export():
    assert_complete_report(REPORT)
    assert "下载报告" not in REPORT
    card = build_card(REPORT)
    assert card.raw_report_markdown == REPORT
    assert card.root_cause.resource_id == "8493"
    assert (
        extract_display_fields(card.model_dump(by_alias=True))["confidence"]
        == "90%"
    )
    assert len(PROTOCOL[: REPORT_MATCH.end()].splitlines()) <= 132


def test_explicit_export_is_additional_link_before_summary_not_a_replacement():
    report = REPORT.replace(
        "### 追溯、复核与按需导出\n",
        "### 追溯、复核与按需导出\n- " + DOWNLOAD + "\n",
    )
    assert_complete_report(report)
    assert report.index(DOWNLOAD) < report.index("## 📊 总结")
    card = build_card(report)
    assert DOWNLOAD in card.raw_report_markdown
    assert card.raw_report_markdown.endswith("- 通知状态：未执行")


def test_download_and_notification_prose_without_analysis_do_not_form_a_card():
    response = (
        "报告已保存。\n\n## 通知推送\n### 异常指标\nCPU=12%。\n"
        "### 根因方向\n采样命中阈值。\n### 处置建议\n核验规则。\n\n" + DOWNLOAD
    )
    assert not is_alarm_analyst_card_candidate(
        employee_id="fault", report_markdown=response, process_blocks=[]
    )


def test_denied_recall_fixture_preserves_card_and_unknown_coverage():
    report = replace_section(
        REPORT,
        "数据查询与整理",
        "| 来源 | 结果及限制 |\n|---|---|\n"
        "| CPU历史指标／8493 | 接口统计均值14.68%、最大51.95%；"
        "原始样本被截断，受控回读因无沙箱被拒绝，实际末端和样本数未核验 |",
    )
    report = replace_section(
        report,
        "异常关联分析",
        "### 关键事件时间线\n- 告警记录：采样命中阈值。\n"
        "### 关联证据与待核验线索\n"
        "- 无完整逐点样本，峰值时间与指标同步关系未核验。",
    )
    report = replace_section(
        report,
        "异常指标",
        "- CPU接口统计见查询概览；无逐点证据，不推断峰值同步。",
    )
    report = replace_section(
        report,
        "告警基础信息",
        "| 字段 | 值 |\n|---|---|\n| 设备名称 | host-1 |\n"
        "| 资源 ID（CI ID） | 8493 |\n"
        "| 报告分析状态 | 部分完成：历史采样覆盖核验受限 |\n"
        "### 对象识别\n- CI 8493。\n### 故障信息摘要\n"
        "- 时间：实际历史末端和样本数未核验。\n"
        "- 现象：CPU阈值触发。\n- 影响：业务待验证。\n"
        "- 处理情况：本次仅查询。",
    )
    assert_complete_report(report)
    assert "280点" not in report
    assert "下载报告" not in report
    assert "51.95%" in report
    assert (
        "峰值时间与指标同步关系未核验"
        in build_card(report).raw_report_markdown
    )


@pytest.mark.parametrize(
    "channels,expected",
    [
        (("sent", "sent"), "sent"),
        (("sent", "failed"), "partial"),
        (("failed", "failed"), "failed"),
    ],
)
def test_notification_channel_outcomes_not_process_success_determine_status(
    monkeypatch, channels, expected
):
    monkeypatch.setattr(
        notification,
        "_get_notify_env",
        lambda key: {
            "DINGTALK_WEBHOOK_URL": "https://example.invalid/dingtalk",
            "FEISHU_WEBHOOK_URL": "https://example.invalid/feishu",
        }.get(key, ""),
    )
    sender = Mock(
        side_effect=[
            {
                "channel": name,
                "status": status,
                "reason": "rejected" if status == "failed" else "",
            }
            for name, status in zip(("dingtalk", "feishu"), channels)
        ]
    )
    monkeypatch.setattr(notification, "_send_json_webhook", sender)
    actual = notification._notify_analysis_report({})
    assert actual["status"] == expected
    assert sender.call_count == 2
    status_text = notification._format_notification_status(actual)
    report = REPORT.replace("- 通知状态：未执行", "- 通知状态：" + status_text)
    assert_complete_report(report)
    assert build_card(report).raw_report_markdown.endswith(status_text)
    if expected != "sent":
        assert "✅ 已成功推送" not in status_text


def test_unconfigured_notification_skips_without_network_and_keeps_card(
    monkeypatch,
):
    monkeypatch.setattr(notification, "_get_notify_env", lambda key: "")
    sender = Mock(side_effect=AssertionError("Must not send without config"))
    monkeypatch.setattr(notification, "_send_json_webhook", sender)
    monkeypatch.setattr(notification, "_send_app_push", sender)
    actual = notification._notify_analysis_report({})
    assert actual == {
        "enabled": False,
        "status": "skipped",
        "reason": "webhook_not_configured",
        "channels": [],
    }
    sender.assert_not_called()
    report = REPORT.replace("- 通知状态：未执行", "- 通知状态：未配置")
    assert_complete_report(report)
    assert build_card(report).raw_report_markdown.endswith(
        "- 通知状态：未配置"
    )


def test_export_trigger_contract_is_explicit_and_preserves_inline_report():
    export = (FAULT_DIR / "skills/report-export/SKILL.md").read_text(
        encoding="utf-8"
    )
    description = re.search(r"^description: (.+)$", export, re.MULTILINE)
    assert description is not None
    assert "仅当用户明确要求" in description[1]
    assert "生成告警分析报告" in description[1] and "不触发" in description[1]
    assert "--copy" in export
    assert "后续仅导出已有报告" in export
    assert "不重新通知" in export
    prefix = PROTOCOL.split("## 示例模板", 1)[0]
    for requirement in (
        "不藏于文件",
        "不替代正文",
        "已知无沙箱/拒绝/缺失/失败则停止",
        "不重复审批",
        "不试读空缓存",
        "不以最大值推断同步",
        "未调用写未执行",
        "不另附通知全文",
    ):
        assert requirement in prefix
