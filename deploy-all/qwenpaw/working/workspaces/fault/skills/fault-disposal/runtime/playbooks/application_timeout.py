from __future__ import annotations

import re

from ..models import (
    ActionExecutionResult,
    ActionProposal,
    AgentMessage,
    DiagnosisResult,
    RouterDecision,
    TicketContext,
)
from ..reasoners import TemplateReasoner
from ..tool_adapters import FaultDisposalToolbox


class ApplicationTimeoutPlaybook:
    id = "application-timeout"
    name = "应用接口响应超时处置"

    def match(self, context: TicketContext) -> RouterDecision:
        title = str(context.entry_workorder.get("title", ""))
        speciality = str(context.entry_workorder.get("speciality", ""))
        score = 0
        matched_by = "fallback"
        reason = "未命中特征"

        if "应用接口响应超时" in title:
            score = 100
            matched_by = "title"
            reason = "按工单标题命中应用接口响应超时 playbook"
        elif speciality == "应用":
            score = 55
            matched_by = "speciality"
            reason = "按专业域命中应用类故障处置 playbook"

        return RouterDecision(
            playbook_id=self.id,
            playbook_name=self.name,
            score=score,
            matched_by=matched_by,
            reason=reason,
        )

    def diagnose(
        self,
        *,
        context: TicketContext,
        toolbox: FaultDisposalToolbox,
        reasoner: TemplateReasoner,
        router_decision: RouterDecision,
        session_id: str,
    ) -> DiagnosisResult:
        (
            related_workorders,
            root_cause_ticket,
            app_snapshot,
            slow_sql_snapshot,
            tool_calls,
        ) = self._collect_diagnosis_inputs(context=context, toolbox=toolbox)

        messages = self._render_messages(
            context=context,
            reasoner=reasoner,
            session_id=session_id,
            related_workorders=related_workorders,
            root_cause_ticket=root_cause_ticket,
            app_snapshot=app_snapshot,
            slow_sql_snapshot=slow_sql_snapshot,
        )

        return DiagnosisResult(
            session_id=session_id,
            router=router_decision,
            playbook_id=self.id,
            playbook_name=self.name,
            reasoner=getattr(reasoner, "last_used_reasoner", reasoner.name),
            messages=messages,
            tool_calls=tool_calls,
        )

    def diagnose_stream(
        self,
        *,
        context: TicketContext,
        toolbox: FaultDisposalToolbox,
        reasoner: TemplateReasoner,
        router_decision: RouterDecision,
        session_id: str,
    ):
        yield {
            "event": "session",
            "session": {
                "sessionId": session_id,
                "playbookId": self.id,
                "playbookName": self.name,
            },
            "router": router_decision.to_dict(),
        }

        related_workorders, related_call = toolbox.load_related_workorders(context)
        yield {
            "event": "status",
            "stage": "ticket-correlation",
            "message": f"已完成同时间窗告警检索，发现 {len(related_workorders)} 条关联事件，正在比对触发顺序与影响对象。",
            "toolCall": related_call.to_dict(),
        }

        root_cause_ticket, match_call = toolbox.get_root_cause_candidate(
            context.entry_workorder,
            related_workorders,
        )
        if not root_cause_ticket:
            raise RuntimeError("No root-cause slow SQL workorder found for application timeout playbook")

        yield {
            "event": "status",
            "stage": "root-cause-correlation",
            "message": "已完成关联告警比对，发现存在可继续下钻的依赖侧异常线索，开始采集应用与数据库证据。",
            "toolCall": match_call.to_dict(),
        }

        app_snapshot, app_call = toolbox.get_application_timeout_snapshot(
            context.entry_workorder,
        )
        yield {
            "event": "status",
            "stage": "application-api-observation",
            "message": (
                f"应用指标采样完成：接口 P95 {app_snapshot.get('apiLatency', {}).get('p95', 0)}ms，"
                f"P99 {app_snapshot.get('apiLatency', {}).get('p99', 0)}ms，"
                f"超时率 {app_snapshot.get('timeoutRate', '--')}。"
            ),
            "toolCall": app_call.to_dict(),
        }
        yield {
            "event": "status",
            "stage": "application-runtime-observation",
            "message": (
                f"运行态检查完成：JVM CPU {app_snapshot.get('jvmCpuUsage', '--')}，"
                f"Full GC {app_snapshot.get('fullGcCount', '--')} 次，"
                f"Tomcat 活跃线程 {app_snapshot.get('tomcatThreads', {}).get('active', '--')}/"
                f"{app_snapshot.get('tomcatThreads', {}).get('max', '--')}。"
            ),
            "toolCall": app_call.to_dict(),
        }
        yield {
            "event": "status",
            "stage": "dependency-wait-analysis",
            "message": (
                f"依赖等待信号升高：连接池占用 {app_snapshot.get('dbConnectionPool', {}).get('usage', '--')}，"
                f"连接等待 P95 {app_snapshot.get('dbConnectionPool', {}).get('waitP95Ms', '--')}ms，"
                "正在继续下钻数据库会话与等待指标。"
            ),
            "toolCall": app_call.to_dict(),
        }

        slow_sql_snapshot, slow_sql_call = toolbox.get_related_slow_sql_snapshot(
            root_cause_ticket,
        )
        yield {
            "event": "status",
            "stage": "database-analysis",
            "message": (
                f"数据库侧采样完成：活跃会话 {slow_sql_snapshot.get('activeSessions', '--')}，"
                f"数据库 P95 {slow_sql_snapshot.get('dbLatencyP95Ms', '--')}ms，"
                f"异常连接占用 {slow_sql_snapshot.get('occupiedConnections', '--')}。"
            ),
            "toolCall": slow_sql_call.to_dict(),
        }
        yield {
            "event": "status",
            "stage": "model-reasoning",
            "message": "跨层证据已采集完成，正在由模型综合工单、应用指标、依赖等待和数据库观测结果生成诊断结论。",
            "toolCall": slow_sql_call.to_dict(),
        }

        raw_narrative_text = ""
        narrative_text = ""
        for event in reasoner.stream_application_timeout_narrative(
            source_workorder=context.entry_workorder,
            root_cause_workorder=root_cause_ticket,
            related_workorders=related_workorders,
            app_snapshot=app_snapshot,
            slow_sql_snapshot=slow_sql_snapshot,
            session_id=session_id,
        ):
            if event.get("event") == "content-delta":
                raw_narrative_text += str(event.get("text", ""))
                next_narrative_text = self._extract_visible_narrative(
                    raw_narrative_text,
                    require_preferred_marker=True,
                )
                if next_narrative_text:
                    delta_text = next_narrative_text[len(narrative_text) :]
                    narrative_text = next_narrative_text
                    if delta_text:
                        yield {
                            "event": "content-delta",
                            "text": delta_text,
                        }
            elif event.get("event") == "narrative-complete":
                completed_text = str(event.get("text", "")).strip() or raw_narrative_text.strip()
                narrative_text = (
                    self._extract_visible_narrative(completed_text) or narrative_text.strip()
                )

        narrative_text = self._ensure_fault_snapshot_note(narrative_text)

        if not narrative_text.strip():
            fallback_messages = self._render_messages(
                context=context,
                reasoner=reasoner,
                session_id=session_id,
                related_workorders=related_workorders,
                root_cause_ticket=root_cause_ticket,
                app_snapshot=app_snapshot,
                slow_sql_snapshot=slow_sql_snapshot,
            )
            narrative_text = "\n\n".join(
                message.content.strip()
                for message in fallback_messages
                if message.content.strip()
            )

        completion_message = self._build_stream_completion_message(
            session_id=session_id,
            source_workorder=context.entry_workorder,
            root_cause_ticket=root_cause_ticket,
            app_snapshot=app_snapshot,
            slow_sql_snapshot=slow_sql_snapshot,
            narrative_text=narrative_text,
        )
        yield {
            "event": "message",
            "message": completion_message.to_dict(),
        }

        yield {
            "event": "complete",
            "session": {
                "sessionId": session_id,
                "playbookId": self.id,
                "playbookName": self.name,
                "reasoner": getattr(reasoner, "last_used_reasoner", reasoner.name),
            },
            "toolCalls": [
                related_call.to_dict(),
                match_call.to_dict(),
                app_call.to_dict(),
                slow_sql_call.to_dict(),
            ],
        }

    def execute_action(
        self,
        *,
        operation: dict,
        toolbox: FaultDisposalToolbox,
        reasoner: TemplateReasoner,
        session_id: str,
    ) -> ActionExecutionResult:
        result, tool_call = toolbox.execute_kill_slow_sql(operation)
        clear_alarm_result, clear_alarm_call = toolbox.clear_related_alarms(operation)
        verification_result, verification_call = toolbox.collect_recovery_verification(
            operation,
            result.get("recovery", {}),
        )
        result = {
            **result,
            "clearAlarm": clear_alarm_result,
            "verification": verification_result,
        }
        message = reasoner.render_action_result(
            operation=operation,
            result=result,
            session_id=session_id,
        )
        updated_operation = ActionProposal(
            id=operation.get("id", ""),
            type=operation.get("type", ""),
            title=operation.get("title", ""),
            summary=operation.get("summary", ""),
            status="success",
            risk_level=operation.get("riskLevel", operation.get("risk_level", "medium")),
            params={
                key: value
                for key, value in operation.items()
                if key
                not in {
                    "id",
                    "type",
                    "title",
                    "summary",
                    "status",
                    "riskLevel",
                    "risk_level",
                    "result",
                }
            }
            | {"result": result},
        )
        return ActionExecutionResult(
            session_id=session_id,
            operation=updated_operation,
            messages=[message],
            tool_calls=[tool_call, clear_alarm_call, verification_call],
        )

    def _collect_diagnosis_inputs(
        self,
        *,
        context: TicketContext,
        toolbox: FaultDisposalToolbox,
    ):
        related_workorders, related_call = toolbox.load_related_workorders(context)
        root_cause_ticket, match_call = toolbox.get_root_cause_candidate(
            context.entry_workorder,
            related_workorders,
        )
        if not root_cause_ticket:
            raise RuntimeError("No root-cause slow SQL workorder found for application timeout playbook")

        app_snapshot, app_call = toolbox.get_application_timeout_snapshot(
            context.entry_workorder,
        )
        slow_sql_snapshot, slow_sql_call = toolbox.get_related_slow_sql_snapshot(
            root_cause_ticket,
        )

        return (
            related_workorders,
            root_cause_ticket,
            app_snapshot,
            slow_sql_snapshot,
            [related_call, match_call, app_call, slow_sql_call],
        )

    def _render_messages(
        self,
        *,
        context: TicketContext,
        reasoner: TemplateReasoner,
        session_id: str,
        related_workorders: list[dict],
        root_cause_ticket: dict,
        app_snapshot: dict,
        slow_sql_snapshot: dict,
    ):
        messages = reasoner.render_application_timeout_messages(
            source_workorder=context.entry_workorder,
            root_cause_workorder=root_cause_ticket,
            related_workorders=related_workorders,
            app_snapshot=app_snapshot,
            slow_sql_snapshot=slow_sql_snapshot,
            session_id=session_id,
        )
        baseline_snapshot = self._build_recovery_baseline_snapshot(
            app_snapshot=app_snapshot,
            slow_sql_snapshot=slow_sql_snapshot,
        )

        for message in messages:
            if message.action:
                message.action.params["workflowSessionId"] = session_id
                message.action.params["playbookId"] = self.id
                message.action.params["preRecoverySnapshot"] = baseline_snapshot

        return messages

    def _build_stream_completion_message(
        self,
        *,
        session_id: str,
        source_workorder: dict,
        root_cause_ticket: dict,
        app_snapshot: dict,
        slow_sql_snapshot: dict,
        narrative_text: str,
    ) -> AgentMessage:
        action = ActionProposal(
            id=f"kill-slow-sql-{root_cause_ticket.get('workorderNo', '')}",
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
                "workflowSessionId": session_id,
                "sqlId": slow_sql_snapshot.get("sqlId", ""),
                "targetSummary": slow_sql_snapshot.get(
                    "targetSummary",
                    "数据库核心业务慢 SQL 会话",
                ),
                "sourceWorkorderNo": source_workorder.get("workorderNo", ""),
                "sourceAlarmUniqueId": source_workorder.get("id", ""),
                "rootCauseWorkorderNo": root_cause_ticket.get("workorderNo", ""),
                "rootCauseAlarmUniqueId": root_cause_ticket.get("id", ""),
                "deviceName": root_cause_ticket.get("deviceName", ""),
                "manageIp": root_cause_ticket.get("manageIp", ""),
                "locateName": root_cause_ticket.get("locateName", ""),
                "playbookId": self.id,
                "preRecoverySnapshot": self._build_recovery_baseline_snapshot(
                    app_snapshot=app_snapshot,
                    slow_sql_snapshot=slow_sql_snapshot,
                ),
            },
        )

        return AgentMessage(
            content=narrative_text.strip(),
            process_blocks=[],
            action=action,
        )

    def _build_recovery_baseline_snapshot(
        self,
        *,
        app_snapshot: dict,
        slow_sql_snapshot: dict,
    ) -> dict:
        return {
            "capturedAt": str(
                app_snapshot.get("timeWindow", {}).get("start")
                or app_snapshot.get("capturedAt")
                or ""
            ),
            "windowMinutes": int(app_snapshot.get("timeWindow", {}).get("durationMinutes") or 5),
            "windowSeconds": 30,
            "apiP95Ms": app_snapshot.get("apiLatency", {}).get("p95", 0),
            "dbP95Ms": slow_sql_snapshot.get("dbLatencyP95Ms", 0),
            "connectionPoolUsagePct": str(
                app_snapshot.get("dbConnectionPool", {}).get("usage", "0%")
            ).replace("%", ""),
            "timeoutRatePct": str(app_snapshot.get("timeoutRate", "0%")).replace("%", ""),
        }

    def _extract_visible_narrative(
        self,
        raw_text: str,
        *,
        require_preferred_marker: bool = False,
    ) -> str:
        preferred_markers = [
            "## 工单接管\n\n我已接管工单",
            "## 工单接管\r\n\r\n我已接管工单",
            "## 工单接管\n\n",
            "## 工单接管\r\n\r\n",
        ]
        for marker in preferred_markers:
            marker_index = raw_text.rfind(marker)
            if marker_index != -1:
                return raw_text[marker_index:].strip()

        if require_preferred_marker:
            return ""

        fallback_marker = "## 工单接管"
        marker_index = raw_text.rfind(fallback_marker)
        if marker_index != -1:
            return raw_text[marker_index:].strip()

        return ""

    def _ensure_fault_snapshot_note(self, narrative_text: str) -> str:
        text = str(narrative_text or "").strip()
        if not text or "已生成故障快照" in text:
            return text

        key_findings_patterns = [
            r"(关键发现\s*[:：][\s\S]*?)(\n##\s+根因结论)",
            r"(###\s*关键发现[\s\S]*?)(\n##\s+根因结论)",
        ]
        for pattern in key_findings_patterns:
            replaced = re.sub(
                pattern,
                lambda match: f"{match.group(1).rstrip()}\n\n注：已生成故障快照。\n{match.group(2)}",
                text,
                count=1,
            )
            if replaced != text:
                return replaced

        return text
