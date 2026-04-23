from __future__ import annotations

from qwenpaw.extensions.api.alarm_analyst_card_service import (
    build_alarm_analyst_card,
    is_alarm_analyst_card_candidate,
)


def test_is_alarm_analyst_card_candidate_matches_report_with_rca_markers() -> None:
    matched = is_alarm_analyst_card_candidate(
        employee_id="fault",
        report_markdown=(
            "🔴 数据库锁异常 — 完整故障分析报告\n"
            "## 根因分析结论\n"
            "- 根资源 MySQL（CI ID 3094）出现锁等待放大\n"
            "## 处置建议\n"
            "- 优先终止异常会话并观察告警收敛\n"
        ),
        process_blocks=[
            {
                "kind": "tool",
                "toolName": "read_file",
                "outputContent": (
                    "{\"title\":{\"text\":\"CMDB 应用关系拓扑\"},"
                    "\"series\":[{\"type\":\"graph\",\"data\":[],\"links\":[]}]}"
                ),
            }
        ],
    )

    assert matched is True


def test_build_alarm_analyst_card_extracts_summary_recommendations_and_hash() -> None:
    card = build_alarm_analyst_card(
        chat_id="chat-1",
        message_id="assistant-1",
        employee_id="fault",
        report_markdown=(
            "🔴 数据库锁异常 — 完整故障分析报告\n"
            "## 根因分析结论\n"
            "- 根因：MySQL 资源 3094 存在锁等待放大，导致 CMDB 写入失败。\n"
            "## 影响范围\n"
            "- 受影响应用：CMDB\n"
            "- 受影响资源：3094、3092\n"
            "## 处置建议\n"
            "- P0：终止异常慢 SQL 会话。\n"
            "- P1：继续观察最近 10 分钟告警是否收敛。\n"
        ),
        process_blocks=[
            {
                "kind": "tool",
                "toolName": "read_file",
                "outputContent": (
                    "```json\n"
                    "{\"title\":{\"text\":\"CMDB 应用关系拓扑\"},"
                    "\"series\":[{\"type\":\"graph\",\"data\":[{\"id\":\"3094\",\"name\":\"MySQL\"}],"
                    "\"links\":[{\"source\":\"3094\",\"target\":\"3092\"}]}]}\n"
                    "```"
                ),
            }
        ],
    )

    assert card.type == "alarm-analyst-card"
    assert card.summary.title == "数据库锁异常"
    assert "MySQL" in card.summary.conclusion
    assert card.source.content_hash
    assert card.source.chat_id == "chat-1"
    assert card.root_cause.ci_id == "3094"
    assert card.impact.affected_applications[0].name == "CMDB"
    assert card.impact.affected_resources[0].id == "3094"
    assert card.topology.nodes[0]["id"] == "3094"
    assert card.recommendations[0].priority == "p0"
    assert card.recommendations[1].action_type == "observe"
    assert card.evidence[-1].kind == "tool"
