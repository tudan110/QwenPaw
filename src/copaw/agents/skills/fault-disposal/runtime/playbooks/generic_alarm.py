from __future__ import annotations

from ..models import ActionExecutionResult, DiagnosisResult, RouterDecision, TicketContext
from ..reasoners import TemplateReasoner
from ..tool_adapters import FaultDisposalToolbox


class GenericAlarmPlaybook:
    id = "generic-alarm"
    name = "通用告警处置"

    def match(self, context: TicketContext) -> RouterDecision:
        return RouterDecision(
            playbook_id=self.id,
            playbook_name=self.name,
            score=1,
            matched_by="default",
            reason="通用兜底 playbook",
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
        messages = reasoner.render_generic_alarm_messages(
            entry_workorder=context.entry_workorder,
            session_id=session_id,
        )
        return DiagnosisResult(
            session_id=session_id,
            router=router_decision,
            playbook_id=self.id,
            playbook_name=self.name,
            reasoner=getattr(reasoner, "last_used_reasoner", reasoner.name),
            messages=messages,
            tool_calls=[],
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
        yield {
            "event": "status",
            "stage": "routing",
            "message": "当前工单尚未匹配到专用处置流程，正在切换到通用分析模式。",
        }
        for message in reasoner.render_generic_alarm_messages(
            entry_workorder=context.entry_workorder,
            session_id=session_id,
        ):
            yield {
                "event": "message",
                "message": message.to_dict(),
            }
        yield {
            "event": "complete",
            "session": {
                "sessionId": session_id,
                "playbookId": self.id,
                "playbookName": self.name,
                "reasoner": getattr(reasoner, "last_used_reasoner", reasoner.name),
            },
            "toolCalls": [],
        }

    def execute_action(
        self,
        *,
        operation: dict,
        toolbox: FaultDisposalToolbox,
        reasoner: TemplateReasoner,
        session_id: str,
    ) -> ActionExecutionResult:
        raise RuntimeError("Generic alarm playbook has no executable actions yet")
