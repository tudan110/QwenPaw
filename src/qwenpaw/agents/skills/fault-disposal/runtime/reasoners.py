from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

from .models import ActionProposal, AgentMessage, ProcessBlock


def _candidate_project_roots() -> list[Path]:
    candidates: list[Path] = []

    for env_name in (
        "QWENPAW_FAULT_DISPOSAL_PROJECT_ROOT",
        "QWENPAW_PORTAL_PROJECT_ROOT",
    ):
        raw = str((os.environ.get(env_name) or "")).strip()
        if raw:
            candidates.append(Path(raw).expanduser().resolve())

    current = Path.cwd().resolve()
    candidates.extend([current, *current.parents])

    here = Path(__file__).resolve()
    candidates.extend([*here.parents])

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


def _default_project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return here.parents[6]


def _resolve_project_root() -> Path:
    for root in _candidate_project_roots():
        if (root / "portal" / "vite.config.js").exists():
            return root
        if (
            root
            / "src"
            / "qwenpaw"
            / "extensions"
            / "integrations"
            / "alarm_workorders"
        ).exists():
            return root
    return _default_project_root()


FAULT_SNAPSHOT_NOTE = "注：已生成故障快照。"


class TemplateReasoner:
    """Template fallback that matches the ticket-driven chat contract."""

    name = "template_reasoner_v1"

    def render_application_timeout_messages(
        self,
        *,
        source_workorder: dict,
        root_cause_workorder: dict,
        related_workorders: list[dict],
        app_snapshot: dict,
        slow_sql_snapshot: dict,
        session_id: str = "",
    ) -> list[AgentMessage]:
        kickoff = AgentMessage(
            content=(
                f"已接管工单 `{source_workorder.get('workorderNo', '')}`，开始进入"
                f" **{source_workorder.get('title', '')}** 的工单驱动故障处置流程。\n\n"
                f"本次处置对象为 **{source_workorder.get('deviceName', '')}**，管理 IP "
                f"`{source_workorder.get('manageIp', '')}`，定位实例 "
                f"`{source_workorder.get('locateName', '')}`。接下来将按"
                "“工单关联 -> 应用观测 -> 数据库依赖 -> 根因收敛 -> 处置确认”顺序执行。"
            ),
        )

        checkpoint = AgentMessage(
            content=(
                f"第一轮诊断已完成：在 `{source_workorder.get('eventTime', '')}` 后的 5 分钟窗口内，"
                f"实例 `{source_workorder.get('locateName', '')}` 的接口时延显著抬升，"
                f"同时命中关联工单 `{root_cause_workorder.get('workorderNo', '')}`，"
                f"即 **{root_cause_workorder.get('title', '')}**。"
            ),
        )

        final_message = AgentMessage(
            content=(
                f"当前已完成根因收敛：表象故障 **{source_workorder.get('title', '')}** "
                f"对应的核心故障为 **{root_cause_workorder.get('title', '')}**。\n"
                "下面是本次工单驱动分析的关键证据。"
            ),
            process_blocks=[
                ProcessBlock(
                    id=f"{source_workorder.get('workorderNo', 'wo')}-impact",
                    kind="thinking",
                    icon="fa-bell",
                    title="接警与影响面评估",
                    subtitle="入口超时集中在单实例",
                    content=self._render_impact_block(source_workorder, app_snapshot),
                ),
                ProcessBlock(
                    id=f"{source_workorder.get('workorderNo', 'wo')}-application",
                    kind="tool",
                    icon="fa-server",
                    title="应用与中间层分析",
                    subtitle="线程池受阻，连接池等待升高",
                    content=self._render_application_block(app_snapshot),
                ),
                ProcessBlock(
                    id=f"{source_workorder.get('workorderNo', 'wo')}-database",
                    kind="tool",
                    icon="fa-database",
                    title="数据库依赖分析",
                    subtitle=f"关联根因工单 {root_cause_workorder.get('workorderNo', '')}",
                    content=self._render_database_block(
                        root_cause_workorder,
                        related_workorders,
                        slow_sql_snapshot,
                    ),
                ),
                ProcessBlock(
                    id=f"{source_workorder.get('workorderNo', 'wo')}-conclusion",
                    kind="thinking",
                    icon="fa-link",
                    title="根因结论与处置建议",
                    subtitle="由接口超时收敛到慢 SQL",
                    content=self._render_conclusion_block(
                        source_workorder,
                        root_cause_workorder,
                    ),
                ),
            ],
            action=ActionProposal(
                id=f"kill-slow-sql-{root_cause_workorder.get('workorderNo', '')}",
                type="kill-slow-sql",
                title="建议执行：终止异常慢 SQL 会话",
                summary=(
                    "慢 SQL 会话持续占用数据库连接，已经造成应用实例连接池排队。"
                    "建议先终止异常会话，再继续观察接口时延和连接池恢复情况。"
                ),
                status="ready",
                risk_level="medium",
                params={
                    "sessionId": slow_sql_snapshot.get("sessionId", ""),
                    "workflowSessionId": "",
                    "sqlId": slow_sql_snapshot.get("sqlId", ""),
                    "targetSummary": slow_sql_snapshot.get(
                        "targetSummary",
                        "数据库核心业务慢 SQL 会话",
                    ),
                    "sourceWorkorderNo": source_workorder.get("workorderNo", ""),
                    "sourceAlarmUniqueId": source_workorder.get("id", ""),
                    "rootCauseWorkorderNo": root_cause_workorder.get("workorderNo", ""),
                    "rootCauseAlarmUniqueId": root_cause_workorder.get("id", ""),
                    "deviceName": root_cause_workorder.get("deviceName", ""),
                    "manageIp": root_cause_workorder.get("manageIp", ""),
                    "locateName": root_cause_workorder.get("locateName", ""),
                },
            ),
        )

        return [kickoff, checkpoint, final_message]

    def render_generic_alarm_messages(
        self,
        *,
        entry_workorder: dict,
        session_id: str = "",
    ) -> list[AgentMessage]:
        return [
            AgentMessage(
                content=(
                    f"已接管工单 `{entry_workorder.get('workorderNo', '')}`。当前工单尚未匹配到专用 playbook，"
                    "已切换到通用故障处置模式。\n\n"
                    "建议按“影响面确认 -> 关联告警 -> 核心依赖 -> 处置动作”补齐专用流程，"
                    "后续新的工单类型即可直接通过路由接入。"
                ),
            )
        ]

    def render_action_result(
        self,
        *,
        operation: dict,
        result: dict,
        session_id: str = "",
    ) -> AgentMessage:
        recovery = result.get("recovery", {})
        clear_alarm = result.get("clearAlarm", {})
        verification = result.get("verification", {})
        is_simulated = bool(result.get("simulated"))
        clear_alarm_id = str(clear_alarm.get("alarmUniqueId", "")).strip()
        clear_alarm_message = str(clear_alarm.get("message", "")).strip()
        clear_alarm_status = "已完成" if clear_alarm.get("success") else "未完成"
        execution_mode_line = (
            "- 执行模式：模拟处置（当前环境未接入真实慢 SQL 终止接口）\n"
            if is_simulated
            else ""
        )
        clear_alarm_lines = []
        if clear_alarm.get("attempted"):
            clear_alarm_lines.extend(
                [
                    "**告警闭环**",
                    "",
                    f"- 清除对象：{clear_alarm_id or '未获取到告警标识'}",
                    f"- 接口状态：{clear_alarm_status}",
                    f"- 返回结果：{clear_alarm_message or '未返回可展示结果'}",
                ]
            )
        else:
            clear_alarm_lines.extend(
                [
                    "**告警闭环**",
                    "",
                    f"- 接口状态：{clear_alarm_status}",
                    f"- 返回结果：{clear_alarm_message or '未执行告警清除'}",
                ]
            )
        clear_alarm_section = "\n".join(clear_alarm_lines)
        verification_section = self._render_recovery_verification_section(
            operation=operation,
            recovery=recovery,
            verification=verification,
        )

        return AgentMessage(
            content=(
                f"慢 SQL 终止动作已完成，根因工单 `{operation.get('rootCauseWorkorderNo', '')}` "
                "已进入恢复验证阶段。\n\n"
                f"{execution_mode_line}"
                f"- 执行动作：终止会话 `{result.get('sessionId', operation.get('sessionId', ''))}` / "
                f"SQL_ID `{result.get('sqlId', operation.get('sqlId', ''))}`\n"
                f"- 处置对象：{operation.get('deviceName', '')} ({operation.get('manageIp', '')}) / "
                f"{operation.get('locateName', '')}\n"
                f"- 执行结果：{result.get('message', '')}\n\n"
                f"{clear_alarm_section}\n\n"
                f"{verification_section}"
            )
        )

    def _render_recovery_verification_section(
        self,
        *,
        operation: dict,
        recovery: dict,
        verification: dict,
    ) -> str:
        before_snapshot = verification.get("beforeSnapshot") or operation.get("preRecoverySnapshot") or {}
        after_snapshot = verification.get("afterSnapshot") or {}
        timeline = verification.get("timeline") or []
        api_delta = self._format_change_rate(
            self._to_float(before_snapshot.get("apiP95Ms")),
            self._to_float(after_snapshot.get("apiP95Ms")),
        )
        db_delta = self._format_change_rate(
            self._to_float(before_snapshot.get("dbP95Ms")),
            self._to_float(after_snapshot.get("dbP95Ms")),
        )
        pool_delta = self._format_change_rate(
            self._to_float(before_snapshot.get("connectionPoolUsagePct")),
            self._to_float(after_snapshot.get("connectionPoolUsagePct")),
        )
        timeout_delta = self._format_change_rate(
            self._to_float(before_snapshot.get("timeoutRatePct")),
            self._to_float(after_snapshot.get("timeoutRatePct")),
        )

        sections = [
            "**恢复验证**",
            "",
            "> 已保留处置前快照，并按实时采集接口的返回结构模拟了处置后趋势数据。恢复趋势图由前端实时可视化通道独立渲染，后续接入真实长连接指标流时可直接复用当前协议。",
        ]

        sections.extend(
            [
                "",
                f"- 采样窗口：处置前 {self._format_window(before_snapshot)} 基线，对比处置后最近 {self._format_window(after_snapshot)} 的滚动采样。",
                f"- 接口 P95：{self._format_latency(before_snapshot.get('apiP95Ms'))} -> {self._format_latency(after_snapshot.get('apiP95Ms'))}（{api_delta}）",
                f"- 数据库 P95：{self._format_latency(before_snapshot.get('dbP95Ms'))} -> {self._format_latency(after_snapshot.get('dbP95Ms'))}（{db_delta}）",
                f"- 连接池占用：{self._format_percent(before_snapshot.get('connectionPoolUsagePct'))} -> {self._format_percent(after_snapshot.get('connectionPoolUsagePct'))}（{pool_delta}）",
                f"- 接口超时率：{self._format_percent(before_snapshot.get('timeoutRatePct'))} -> {self._format_percent(after_snapshot.get('timeoutRatePct'))}（{timeout_delta}）",
                "",
                "**处置闭环总结**",
                "",
                f"- 根因工单 `{operation.get('rootCauseWorkorderNo', '')}` 的慢 SQL 会话已完成处置，数据库连接占用已释放。",
                f"- 入口工单 `{operation.get('sourceWorkorderNo', '')}` 对应的应用超时指标已回落，当前处置链路已具备闭环条件。",
                "- 已保留处置前快照与处置后验证结果，便于后续接入真实实时采集流后直接复用。",
            ]
        )

        return "\n".join(sections)

    def build_recovery_visualization_payload(
        self,
        *,
        verification: dict[str, Any],
        recovery: dict[str, Any],
    ) -> dict[str, Any]:
        return self._build_recovery_visualization_payload(
            verification=verification,
            recovery=recovery,
        )

    def _build_latency_chart(self, verification: dict) -> dict[str, Any]:
        timeline = verification.get("timeline") or []
        labels = [item.get("label", "") for item in timeline]
        marker_lines = self._build_event_marker_lines(verification, labels)
        fault_point = self._build_fault_marker_point(timeline)
        return {
            "__mockStream": self._build_mock_stream_meta(verification, timeline),
            "backgroundColor": "transparent",
            "animationDuration": 500,
            "title": {
                "text": "接口与数据库时延恢复趋势",
                "left": 18,
                "top": 12,
                "textStyle": {"fontSize": 14, "fontWeight": 600, "color": "#0f172a"},
            },
            "legend": {
                "top": 12,
                "right": 18,
                "itemWidth": 10,
                "itemHeight": 10,
                "textStyle": {"fontSize": 12, "color": "#475569"},
            },
            "grid": {"left": 54, "right": 24, "top": 64, "bottom": 58},
            "tooltip": {"trigger": "axis"},
            "xAxis": {
                "type": "category",
                "boundaryGap": False,
                "data": labels,
                "axisLine": {"lineStyle": {"color": "#cbd5e1"}},
                "axisTick": {"show": False},
                "axisLabel": {
                    "show": True,
                    "color": "#64748b",
                    "fontSize": 11,
                    "margin": 14,
                    "interval": 5,
                },
            },
            "yAxis": {
                "type": "value",
                "name": "时延 (ms)",
                "nameTextStyle": {"color": "#64748b", "padding": [0, 0, 0, 4]},
                "splitLine": {"lineStyle": {"color": "rgba(148, 163, 184, 0.18)"}},
                "axisLabel": {"color": "#64748b"},
            },
            "series": [
                {
                    "name": "接口 P95",
                    "type": "line",
                    "smooth": True,
                    "showSymbol": False,
                    "lineStyle": {"width": 3, "color": "#2563eb"},
                    "areaStyle": {"color": "rgba(37, 99, 235, 0.10)"},
                    "data": [item.get("apiP95Ms", 0) for item in timeline],
                    "markPoint": {
                        "symbol": "circle",
                        "symbolSize": 16,
                        "itemStyle": {"color": "#dc2626", "borderColor": "#fff", "borderWidth": 2},
                        "label": {"show": True, "formatter": "故障点", "position": "top", "color": "#991b1b"},
                        "data": [fault_point] if fault_point else [],
                    },
                    "markLine": {
                        "symbol": ["none", "none"],
                        "data": marker_lines,
                    },
                },
                {
                    "name": "数据库 P95",
                    "type": "line",
                    "smooth": True,
                    "showSymbol": False,
                    "lineStyle": {"width": 2.5, "color": "#0f766e"},
                    "areaStyle": {"color": "rgba(15, 118, 110, 0.08)"},
                    "data": [item.get("dbP95Ms", 0) for item in timeline],
                },
            ],
        }

    def _build_health_chart(self, verification: dict, recovery: dict) -> dict[str, Any]:
        timeline = verification.get("timeline") or []
        labels = [item.get("label", "") for item in timeline]
        marker_lines = self._build_event_marker_lines(verification, labels)
        return {
            "__mockStream": self._build_mock_stream_meta(verification, timeline),
            "backgroundColor": "transparent",
            "animationDuration": 500,
            "title": {
                "text": "连接池占用与超时率回落趋势",
                "left": 18,
                "top": 12,
                "textStyle": {"fontSize": 14, "fontWeight": 600, "color": "#0f172a"},
                "subtext": (
                    f"即时恢复结果：连接池占用 {recovery.get('connectionPoolUsage', '--')}，"
                    f"接口超时率 {recovery.get('timeoutRate', '--')}"
                ),
                "subtextStyle": {"fontSize": 11, "color": "#64748b"},
            },
            "legend": {
                "top": 12,
                "right": 18,
                "itemWidth": 10,
                "itemHeight": 10,
                "textStyle": {"fontSize": 12, "color": "#475569"},
            },
            "grid": {"left": 54, "right": 24, "top": 78, "bottom": 58},
            "tooltip": {"trigger": "axis"},
            "xAxis": {
                "type": "category",
                "boundaryGap": False,
                "data": labels,
                "axisLine": {"lineStyle": {"color": "#cbd5e1"}},
                "axisTick": {"show": False},
                "axisLabel": {
                    "show": True,
                    "color": "#64748b",
                    "fontSize": 11,
                    "margin": 14,
                    "interval": 5,
                },
            },
            "yAxis": {
                "type": "value",
                "name": "占比 (%)",
                "nameTextStyle": {"color": "#64748b", "padding": [0, 0, 0, 4]},
                "splitLine": {"lineStyle": {"color": "rgba(148, 163, 184, 0.18)"}},
                "axisLabel": {"color": "#64748b", "formatter": "{value}%"},
                "max": 100,
            },
            "series": [
                {
                    "name": "连接池占用",
                    "type": "line",
                    "smooth": True,
                    "showSymbol": False,
                    "lineStyle": {"width": 3, "color": "#f97316"},
                    "areaStyle": {"color": "rgba(249, 115, 22, 0.08)"},
                    "data": [item.get("connectionPoolUsagePct", 0) for item in timeline],
                    "markLine": {
                        "symbol": ["none", "none"],
                        "data": marker_lines,
                    },
                },
                {
                    "name": "接口超时率",
                    "type": "line",
                    "smooth": True,
                    "showSymbol": False,
                    "lineStyle": {"width": 2.5, "color": "#ef4444"},
                    "areaStyle": {"color": "rgba(239, 68, 68, 0.08)"},
                    "data": [item.get("timeoutRatePct", 0) for item in timeline],
                },
            ],
        }

    def _build_recovery_visualization_payload(
        self,
        *,
        verification: dict[str, Any],
        recovery: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "type": "chart-group",
            "version": 1,
            "charts": [
                {
                    "id": "latency-trend",
                    "kind": "echarts",
                    "option": self._build_latency_chart(verification),
                },
                {
                    "id": "health-trend",
                    "kind": "echarts",
                    "option": self._build_health_chart(verification, recovery),
                },
            ],
        }

    def _build_event_marker_lines(
        self,
        verification: dict,
        labels: list[str],
    ) -> list[dict[str, Any]]:
        if not labels:
            return []
        fault_label = verification.get("faultMarkerLabel", "故障爆发")
        action_label = verification.get("phaseMarkerLabel", "执行处置")
        fault_axis = next(
            (item.get("label", "") for item in verification.get("timeline", []) if item.get("phase") == "fault"),
            labels[0],
        )
        action_axis = next(
            (item.get("label", "") for item in verification.get("timeline", []) if item.get("phase") == "action"),
            labels[min(len(labels) - 1, 1)],
        )
        return [
            {
                "xAxis": fault_axis,
                "label": {"formatter": fault_label, "color": "#b91c1c"},
                "lineStyle": {"type": "dashed", "color": "rgba(220, 38, 38, 0.45)"},
            },
            {
                "xAxis": action_axis,
                "label": {"formatter": action_label, "color": "#334155"},
                "lineStyle": {"type": "dashed", "color": "#94a3b8"},
            },
        ]

    def _build_mock_stream_meta(
        self,
        verification: dict,
        timeline: list[dict[str, Any]],
    ) -> dict[str, Any]:
        initial_visible = int(
            verification.get("initialVisiblePoints")
            or min(len(timeline), 10),
        )
        return {
            "enabled": True,
            "intervalMs": int(verification.get("mockPlaybackIntervalMs") or 420),
            "batchSize": int(verification.get("mockPlaybackBatchSize") or 1),
            "initialVisiblePoints": max(2, min(initial_visible, len(timeline))),
            "totalPoints": len(timeline),
        }

    def _build_fault_marker_point(
        self,
        timeline: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        fault_item = next((item for item in timeline if item.get("phase") == "fault"), None)
        if not fault_item:
            return None
        return {
            "coord": [fault_item.get("label", ""), fault_item.get("apiP95Ms", 0)],
            "value": "故障点",
        }

    def _format_change_rate(self, before: float, after: float) -> str:
        if before <= 0:
            return "暂无可比降幅"
        delta = ((before - after) / before) * 100
        return f"下降 {delta:.1f}%"

    def _format_latency(self, value: Any) -> str:
        return f"{self._to_float(value):.0f}ms"

    def _format_percent(self, value: Any) -> str:
        return f"{self._to_float(value):.2f}%"

    def _format_window(self, snapshot: dict[str, Any]) -> str:
        seconds = int(snapshot.get("windowSeconds") or 0)
        if seconds > 0:
            return f"{seconds} 秒"
        minutes = int(snapshot.get("windowMinutes") or 0)
        if minutes > 0:
            return f"{minutes} 分钟"
        return "当前时间窗"

    def _to_float(self, value: Any) -> float:
        text = str(value).strip()
        if text.endswith("%"):
            text = text[:-1]
        try:
            return float(text)
        except (TypeError, ValueError):
            return 0.0

    def _render_impact_block(self, source_workorder: dict, app_snapshot: dict) -> str:
        api_latency = app_snapshot.get("apiLatency", {})
        return "\n".join(
            [
                "| 字段 | 取值 |",
                "| --- | --- |",
                f"| 来源工单 | {source_workorder.get('workorderNo', '')} |",
                f"| 告警标题 | {source_workorder.get('title', '')} |",
                f"| 设备 / 管理 IP | {source_workorder.get('deviceName', '')} / {source_workorder.get('manageIp', '')} |",
                f"| 定位对象 | {source_workorder.get('locateName', '')} |",
                f"| 首次触发时间 | {source_workorder.get('eventTime', '')} |",
                "",
                f"- 接口 P95 由基线 230ms 抬升至 **{api_latency.get('p95', 0)}ms**，P99 峰值达到 **{api_latency.get('p99', 0)}ms**。",
                f"- 超时请求集中落在实例 `{source_workorder.get('locateName', '')}`，更符合单实例下游依赖退化，而不是全链路网络故障。",
                f"- 当前窗口超时率达到 **{app_snapshot.get('timeoutRate', '--')}**，已进入业务感知级故障。",
            ]
        )

    def _render_application_block(self, app_snapshot: dict) -> str:
        threads = app_snapshot.get("tomcatThreads", {})
        pool = app_snapshot.get("dbConnectionPool", {})
        rtt = app_snapshot.get("gatewayRttMs", {})
        return "\n".join(
            [
                "| 指标项 | 观测结果 | 判定 |",
                "| --- | --- | --- |",
                f"| 网关 -> 应用 RTT | {rtt.get('min', 0)}ms - {rtt.get('max', 0)}ms | 正常 |",
                f"| JVM CPU 使用率 | {app_snapshot.get('jvmCpuUsage', '--')} | 未打满 |",
                f"| Full GC 次数 | {app_snapshot.get('fullGcCount', 0)} 次 | 正常 |",
                f"| Tomcat 工作线程 | {threads.get('active', 0)} / {threads.get('max', 0)} | 接近上限 |",
                f"| 数据库连接池占用 | {pool.get('usage', '--')} | 异常升高 |",
                f"| 连接等待 P95 | {pool.get('waitP95Ms', 0)}ms | 明显异常 |",
                "",
                "- 应用线程未被 CPU 或 GC 打满，说明问题不在计算资源本身。",
                "- 数据库连接等待时延显著抬高，线程主要阻塞在依赖访问阶段。",
                "- 当前更可能是数据库侧长事务或慢 SQL 导致的连接池排队。",
            ]
        )

    def _render_database_block(
        self,
        root_cause_workorder: dict,
        related_workorders: list[dict],
        slow_sql_snapshot: dict,
    ) -> str:
        return "\n".join(
            [
                f"- 当前时间窗内共识别到 {len(related_workorders)} 条关联工单，其中根因候选为 `{root_cause_workorder.get('workorderNo', '')}`，"
                f"即 **{root_cause_workorder.get('title', '')}**。",
                f"- 根因工单对象与来源工单一致：设备 `{root_cause_workorder.get('deviceName', '')}`，"
                f"管理 IP `{root_cause_workorder.get('manageIp', '')}`，定位实例 `{root_cause_workorder.get('locateName', '')}`。",
                "",
                "| 数据库观测项 | 分析结果 |",
                "| --- | --- |",
                f"| SQL_ID | {slow_sql_snapshot.get('sqlId', '')} |",
                f"| 慢 SQL 执行时长 | {slow_sql_snapshot.get('executionTimeSeconds', 0)}s |",
                f"| 锁等待时长 | {slow_sql_snapshot.get('lockWaitSeconds', 0)}s |",
                f"| 活跃会话数 | {slow_sql_snapshot.get('activeSessions', 0)} |",
                f"| 被该 SQL 占用连接数 | {slow_sql_snapshot.get('occupiedConnections', 0)} |",
                f"| 数据库 P95 | {slow_sql_snapshot.get('dbLatencyP95Ms', 0)}ms |",
                "",
                "- 慢 SQL 持续占用连接，导致应用请求无法及时获取数据库连接。",
                "- 因此上层首先表现为应用接口响应超时，数据库慢 SQL 是更深层根因。",
            ]
        )

    def _render_conclusion_block(
        self,
        source_workorder: dict,
        root_cause_workorder: dict,
    ) -> str:
        return "\n".join(
            [
                "**结论**",
                "",
                f"- 表象工单：`{source_workorder.get('workorderNo', '')}` / {source_workorder.get('title', '')}",
                f"- 根因工单：`{root_cause_workorder.get('workorderNo', '')}` / {root_cause_workorder.get('title', '')}",
                "",
                f"由于数据库慢 SQL 持续占用连接，应用实例 `{source_workorder.get('locateName', '')}` "
                "出现连接池排队，最终导致对外接口响应超时。",
                "",
                "**建议动作**",
                "",
                "1. 先终止当前异常慢 SQL 会话，快速释放被占用连接。",
                "2. 持续观察 5 分钟接口 P95、超时率和连接池占用是否回落。",
                "3. 若指标恢复，再转入 SQL 优化与索引整改流程。",
            ]
        )


class CopawReasoner:
    """Prefer local CoPAW model reasoning and fall back to templates."""

    def __init__(self, fallback: TemplateReasoner | None = None) -> None:
        self.fallback = fallback or TemplateReasoner()
        self.name = "copaw_reasoner_v1"
        self.last_used_reasoner = self.name
        self.last_error = ""
        self.base_url = (
            os.getenv("QWENPAW_FAULT_DISPOSAL_BASE_URL", "http://127.0.0.1:8088/api").rstrip("/")
        )
        self.agent_id = os.getenv("FAULT_DISPOSAL_REASONER_AGENT_ID", "fault").strip() or "fault"
        self.fallback_agent_id = (
            os.getenv("FAULT_DISPOSAL_REASONER_FALLBACK_AGENT_ID", "default").strip() or "default"
        )
        self.user_id = (
            os.getenv("FAULT_DISPOSAL_REASONER_USER_ID", "portal-reasoner").strip() or "portal-reasoner"
        )
        self.channel = "console"
        self.timeout_seconds = float(os.getenv("FAULT_DISPOSAL_REASONER_TIMEOUT_SECONDS", "90"))
        self.project_root = _resolve_project_root()
        self.node_script = Path(__file__).resolve().with_name("copaw_reasoner_proxy.mjs")

    def render_application_timeout_messages(
        self,
        *,
        source_workorder: dict,
        root_cause_workorder: dict,
        related_workorders: list[dict],
        app_snapshot: dict,
        slow_sql_snapshot: dict,
        session_id: str = "",
    ) -> list[AgentMessage]:
        prompt = self._build_application_timeout_prompt(
            source_workorder=source_workorder,
            root_cause_workorder=root_cause_workorder,
            related_workorders=related_workorders,
            app_snapshot=app_snapshot,
            slow_sql_snapshot=slow_sql_snapshot,
        )
        try:
            payload = self._invoke_copaw_json(
                prompt,
                session_id=self._resolve_reasoner_session_id(session_id),
                chat_name=self._build_reasoner_chat_name(
                    source_workorder,
                    prefix="故障处置诊断",
                ),
                chat_meta=self._build_reasoner_chat_meta(
                    session_id=session_id,
                    entry_workorder=source_workorder,
                    mode="diagnose",
                ),
            )
            messages = self._build_messages_from_llm_payload(payload)
            self.last_used_reasoner = self.name
            self.last_error = ""
            return messages
        except Exception as exc:
            self.last_used_reasoner = self.fallback.name
            self.last_error = str(exc)
            return self.fallback.render_application_timeout_messages(
                source_workorder=source_workorder,
                root_cause_workorder=root_cause_workorder,
                related_workorders=related_workorders,
                app_snapshot=app_snapshot,
                slow_sql_snapshot=slow_sql_snapshot,
                session_id=session_id,
            )

    def render_generic_alarm_messages(
        self,
        *,
        entry_workorder: dict,
        session_id: str = "",
    ) -> list[AgentMessage]:
        self.last_used_reasoner = self.fallback.name
        self.last_error = ""
        return self.fallback.render_generic_alarm_messages(
            entry_workorder=entry_workorder,
            session_id=session_id,
        )

    def render_action_result(
        self,
        *,
        operation: dict,
        result: dict,
        session_id: str = "",
    ) -> AgentMessage:
        prompt = self._build_action_result_prompt(
            operation=operation,
            result=result,
        )
        try:
            payload = self._invoke_copaw_json(
                prompt,
                session_id=self._resolve_reasoner_session_id(session_id),
                chat_name=self._build_reasoner_chat_name(
                    operation,
                    prefix="处置动作回执",
                ),
                chat_meta={
                    "source": "fault-disposal-runtime",
                    "mode": "execute",
                    "workflowSessionId": session_id,
                    "actionId": operation.get("id", ""),
                    "actionType": operation.get("type", ""),
                },
            )
            messages = self._build_messages_from_llm_payload(payload)
            self.last_used_reasoner = self.name
            self.last_error = ""
            return messages[0]
        except Exception as exc:
            self.last_used_reasoner = self.fallback.name
            self.last_error = str(exc)
            return self.fallback.render_action_result(
                operation=operation,
                result=result,
                session_id=session_id,
            )

    def stream_application_timeout_narrative(
        self,
        *,
        source_workorder: dict,
        root_cause_workorder: dict,
        related_workorders: list[dict],
        app_snapshot: dict,
        slow_sql_snapshot: dict,
        session_id: str = "",
    ):
        prompt = self._build_application_timeout_stream_prompt(
            source_workorder=source_workorder,
            root_cause_workorder=root_cause_workorder,
            related_workorders=related_workorders,
            app_snapshot=app_snapshot,
            slow_sql_snapshot=slow_sql_snapshot,
        )
        reasoner_session_id = self._resolve_reasoner_session_id(session_id)
        request_payload = self._build_request_payload(
            prompt,
            session_id=reasoner_session_id,
        )
        proxy_payload = {
            "baseUrl": self.base_url,
            "agentCandidates": self._candidate_agent_ids(),
            "requestPayload": request_payload,
            "chatSpec": self._build_reasoner_chat_spec(
                session_id=reasoner_session_id,
                chat_name=self._build_reasoner_chat_name(
                    source_workorder,
                    prefix="故障处置流式诊断",
                ),
                chat_meta=self._build_reasoner_chat_meta(
                    session_id=session_id,
                    entry_workorder=source_workorder,
                    mode="diagnose-stream",
                ),
            ),
            "timeoutMs": int(self.timeout_seconds * 1000),
        }
        encoded = _encode_base64_json(proxy_payload)
        process = subprocess.Popen(
            [
                "node",
                str(self.node_script),
                "--payload-base64",
                encoded,
                "--stream-jsonl",
            ],
            cwd=str(self.project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        completed_text = ""
        used_agent_id = ""

        try:
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if payload.get("type") == "delta" and payload.get("text"):
                    yield {
                        "event": "content-delta",
                        "text": str(payload.get("text", "")),
                    }
                elif payload.get("type") == "done":
                    completed_text = str(payload.get("text", ""))
                    used_agent_id = str(payload.get("usedAgentId", ""))

            stderr_output = process.stderr.read() if process.stderr is not None else ""
            return_code = process.wait()
            if return_code != 0:
                raise RuntimeError(stderr_output.strip() or "CoPAW narrative stream failed")
        finally:
            if process.poll() is None:
                process.kill()

        self.last_used_reasoner = self.name
        self.last_error = ""
        yield {
            "event": "narrative-complete",
            "text": completed_text,
            "usedAgentId": used_agent_id,
        }

    def _invoke_copaw_json(
        self,
        prompt: str,
        *,
        session_id: str,
        chat_name: str,
        chat_meta: dict[str, Any],
    ) -> dict[str, Any]:
        request_payload = self._build_request_payload(
            prompt,
            session_id=session_id,
            stream=False,
        )
        proxy_payload = {
            "baseUrl": self.base_url,
            "agentCandidates": self._candidate_agent_ids(),
            "requestPayload": request_payload,
            "chatSpec": self._build_reasoner_chat_spec(
                session_id=session_id,
                chat_name=chat_name,
                chat_meta=chat_meta,
            ),
            "timeoutMs": int(self.timeout_seconds * 1000),
        }
        encoded = _encode_base64_json(proxy_payload)
        completed = subprocess.run(
            ["node", str(self.node_script), "--payload-base64", encoded],
            cwd=str(self.project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "CoPAW reasoner proxy request failed")

        proxy_result = json.loads(completed.stdout or "{}")
        parsed = _extract_json_payload(proxy_result.get("text", ""))
        if not isinstance(parsed, dict):
            raise RuntimeError(
                "CoPAW reasoner did not return valid JSON payload"
                f" (agent={proxy_result.get('usedAgentId', '')})"
            )
        return parsed

    def _build_request_payload(
        self,
        prompt: str,
        *,
        session_id: str,
        stream: bool = True,
    ) -> dict[str, Any]:
        return {
            "input": [
                {
                    "role": "user",
                    "type": "message",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                            "status": "created",
                        }
                    ],
                }
            ],
            "session_id": session_id,
            "user_id": self.user_id,
            "channel": self.channel,
            "stream": stream,
        }

    def _build_action_result_prompt(
        self,
        *,
        operation: dict[str, Any],
        result: dict[str, Any],
    ) -> str:
        schema = {
            "messages": [
                {
                    "content": "string",
                    "processBlocks": [
                        {
                            "id": "string",
                            "kind": "tool|thinking",
                            "icon": "fa-*",
                            "title": "string",
                            "subtitle": "string",
                            "content": "markdown string",
                            "defaultOpen": True,
                        }
                    ],
                }
            ]
        }
        evidence = {
            "operation": operation,
            "result": result,
        }
        return (
            "你是企业级故障处置智能体。"
            "请基于执行结果生成一条面向运维用户的回执消息。"
            "输出必须是唯一 JSON 对象，第一个字符必须是 `{`，最后一个字符必须是 `}`。"
            "不要输出 Markdown 代码块，不要输出任何前置说明。"
            "内容要求：清晰说明已执行的动作、告警闭环结果、恢复验证摘要，语气专业、简洁。"
            "如果结果中包含 simulated=true，说明为模拟处置。"
            "不要重复粘贴原始 JSON 字段。"
            "返回 JSON Schema 示例：\n"
            f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
            f"证据输入：\n{json.dumps(evidence, ensure_ascii=False, indent=2)}"
        )

    def _resolve_reasoner_session_id(self, workflow_session_id: str) -> str:
        normalized = str(workflow_session_id or "").strip()
        if normalized:
            return f"fault-reasoner::{normalized}"
        return f"fault-reasoner::{uuid.uuid4().hex[:12]}"

    def _build_reasoner_chat_name(
        self,
        entry_workorder: dict[str, Any],
        *,
        prefix: str,
    ) -> str:
        workorder_no = str(entry_workorder.get("workorderNo", "")).strip()
        title = str(entry_workorder.get("title", "")).strip()
        suffix = workorder_no or title or "新会话"
        return f"{prefix} · {suffix}"[:80]

    def _build_reasoner_chat_meta(
        self,
        *,
        session_id: str,
        entry_workorder: dict[str, Any],
        mode: str,
    ) -> dict[str, Any]:
        return {
            "source": "fault-disposal-runtime",
            "mode": mode,
            "workflowSessionId": session_id,
            "workorderNo": entry_workorder.get("workorderNo", ""),
            "title": entry_workorder.get("title", ""),
        }

    def _build_reasoner_chat_spec(
        self,
        *,
        session_id: str,
        chat_name: str,
        chat_meta: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "name": chat_name,
            "session_id": session_id,
            "user_id": self.user_id,
            "channel": self.channel,
            "meta": chat_meta,
        }

    def _build_messages_from_llm_payload(self, payload: dict[str, Any]) -> list[AgentMessage]:
        raw_messages = payload.get("messages") or []
        if isinstance(raw_messages, dict):
            raw_messages = [raw_messages]

        messages: list[AgentMessage] = []
        for item in raw_messages:
            if not isinstance(item, dict):
                continue
            process_blocks = [
                ProcessBlock(
                    id=block.get("id", f"block-{index}"),
                    kind=block.get("kind", "thinking"),
                    icon=block.get("icon", "fa-circle"),
                    title=block.get("title", ""),
                    subtitle=block.get("subtitle", ""),
                    content=block.get("content", ""),
                    default_open=bool(block.get("defaultOpen", True)),
                )
                for index, block in enumerate(item.get("processBlocks") or [])
                if isinstance(block, dict)
            ]

            action_payload = item.get("action")
            action = None
            if isinstance(action_payload, dict):
                action = ActionProposal(
                    id=action_payload.get("id", ""),
                    type=action_payload.get("type", ""),
                    title=action_payload.get("title", ""),
                    summary=action_payload.get("summary", ""),
                    status=action_payload.get("status", "ready"),
                    risk_level=action_payload.get("riskLevel", "medium"),
                    params={
                        key: value
                        for key, value in action_payload.items()
                        if key not in {"id", "type", "title", "summary", "status", "riskLevel"}
                    },
                )

            messages.append(
                AgentMessage(
                    content=str(item.get("content", "")),
                    process_blocks=process_blocks,
                    action=action,
                )
            )

        if not messages:
            raise RuntimeError("No messages returned from CoPAW reasoner")
        return messages

    def _build_application_timeout_prompt(
        self,
        *,
        source_workorder: dict,
        root_cause_workorder: dict,
        related_workorders: list[dict],
        app_snapshot: dict,
        slow_sql_snapshot: dict,
    ) -> str:
        evidence = {
            "sourceWorkorder": source_workorder,
            "rootCauseWorkorder": root_cause_workorder,
            "relatedWorkorders": related_workorders,
            "applicationSnapshot": app_snapshot,
            "slowSqlSnapshot": slow_sql_snapshot,
        }
        schema = {
            "messages": [
                {
                    "content": "string",
                    "processBlocks": [
                        {
                            "id": "string",
                            "kind": "thinking|tool",
                            "icon": "fa-*",
                            "title": "string",
                            "subtitle": "string",
                            "content": "markdown string",
                            "defaultOpen": True,
                        }
                    ],
                    "action": {
                        "id": "string",
                        "type": "kill-slow-sql",
                        "title": "string",
                        "summary": "string",
                        "status": "ready",
                        "riskLevel": "low|medium|high",
                        "sessionId": "string",
                        "sqlId": "string",
                        "targetSummary": "string",
                        "sourceWorkorderNo": "string",
                        "rootCauseWorkorderNo": "string",
                        "deviceName": "string",
                        "manageIp": "string",
                        "locateName": "string",
                    },
                }
            ]
        }
        return (
            "你是企业级故障处置智能体中的应用故障分析器。"
            "你必须基于给定证据输出结构化 JSON，不要输出任何额外解释，不要使用 Markdown 代码块，"
            "不要声明数据是 mock，不要调用任何工具，只根据证据完成推理。\n\n"
            "输出必须是唯一的 JSON 对象，第一个字符必须是 `{`，最后一个字符必须是 `}`。"
            "不要输出 ```json 代码块，不要输出前置说明，不要输出后续总结。\n\n"
            "任务目标：\n"
            "1. 先生成一条接管工单的消息。\n"
            "2. 再生成一条阶段性诊断消息。\n"
            "3. 最后一条消息必须给出完整分析结论，包含 4 个 processBlocks：接警与影响面评估、应用与中间层分析、数据库依赖分析、根因结论与处置建议。\n"
            "4. 最后一条消息必须带一个 action，动作类型固定为 kill-slow-sql。\n"
            "5. 语气要像真正的运维应用级智能体，内容专业、具体、面向处置。\n\n"
            f"返回 JSON Schema 示例：\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
            f"证据输入：\n{json.dumps(evidence, ensure_ascii=False, indent=2)}"
        )

    def _build_application_timeout_stream_prompt(
        self,
        *,
        source_workorder: dict,
        root_cause_workorder: dict,
        related_workorders: list[dict],
        app_snapshot: dict,
        slow_sql_snapshot: dict,
    ) -> str:
        evidence = {
            "sourceWorkorder": source_workorder,
            "rootCauseWorkorder": root_cause_workorder,
            "relatedWorkorders": related_workorders,
            "applicationSnapshot": app_snapshot,
            "slowSqlSnapshot": slow_sql_snapshot,
        }
        return (
            "你是企业级故障处置智能体，正在以对话形式向用户实时汇报故障分析过程。"
            "请直接输出自然语言分析内容，不要输出 JSON，不要使用 ``` 代码围栏，也不要说明数据来自 mock。"
            "内容必须专业、具体、像真实运维分析报告，并自然收敛到数据库慢 SQL 是根因。\n\n"
            "输出要求：\n"
            "1. 直接开始输出分析内容，不要写前言，不要写“好的/下面开始”。\n"
            "2. 按顺序说明：接管工单、应用层诊断、依赖侧排查、数据库层诊断、根因结论、处置建议。\n"
            "3. 必须使用给定证据中的真实字段和数值。\n"
            "4. 在“根因结论”之前，只能陈述观测现象、排查动作和证据收敛过程，不要提前在标题或首句直接宣布慢 SQL 是根因。\n"
            "5. 只有在“根因结论”部分才能明确点名数据库慢 SQL 和关联工单。\n"
            "6. 结尾必须明确建议终止慢 SQL 会话，但不要自己执行。\n"
            "7. 输出使用 Markdown，可以用小标题、列表、表格。\n"
            "8. 在“关键发现”部分结束后，补一句“注：已生成故障快照。”\n\n"
            "正文必须以 `## 工单接管` 作为开头。\n"
            "绝对禁止：复述任务要求、复述“用户要求我”、复述“输出要求”、复述“证据输入”、逐项抄录原始 JSON 字段。"
            "你要像已经理解上下文一样，直接面向用户给出分析结论和排查过程。\n\n"
            f"证据输入：\n{json.dumps(evidence, ensure_ascii=False, indent=2)}"
        )

    def _candidate_agent_ids(self) -> list[str]:
        return list(dict.fromkeys([self.agent_id, self.fallback_agent_id]))


def _extract_json_payload(raw_text: str) -> dict[str, Any] | None:
    text = raw_text.strip()
    if not text:
        return None

    parsed = _try_parse_json_object(text)
    if parsed is not None:
        return parsed

    for fenced_block in re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE):
        parsed = _try_parse_json_object(fenced_block.strip())
        if parsed is not None:
            return parsed

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _try_parse_json_object(candidate: str) -> dict[str, Any] | None:
    if not candidate:
        return None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _encode_base64_json(payload: dict[str, Any]) -> str:
    return base64.b64encode(
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    ).decode("utf-8")
