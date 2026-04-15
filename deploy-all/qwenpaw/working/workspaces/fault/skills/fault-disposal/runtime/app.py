from __future__ import annotations

from uuid import uuid4

from .models import ActionExecutionResult, DiagnosisResult, TicketContext
from .reasoners import CopawReasoner, TemplateReasoner
from .router import TicketRouter
from .tool_adapters import FaultDisposalToolbox


class FaultDisposalAgentApp:
    def __init__(self) -> None:
        self.router = TicketRouter()
        self.reasoner = CopawReasoner(fallback=TemplateReasoner())
        self.toolbox = FaultDisposalToolbox()

    def diagnose(self, payload: dict) -> DiagnosisResult:
        context = TicketContext(
            entry_workorder=payload.get("entryWorkorder") or {},
            workorders=payload.get("workorders") or [],
            tags=payload.get("tags") or [],
            alarm_code=payload.get("alarmCode") or "",
            source=payload.get("source") or "portal",
        )
        session_id = payload.get("sessionId") or f"fds-{uuid4().hex[:12]}"
        router_decision, playbook = self.router.route(context)
        return playbook.diagnose(
            context=context,
            toolbox=self.toolbox,
            reasoner=self.reasoner,
            router_decision=router_decision,
            session_id=session_id,
        )

    def diagnose_stream(self, payload: dict):
        context = TicketContext(
            entry_workorder=payload.get("entryWorkorder") or {},
            workorders=payload.get("workorders") or [],
            tags=payload.get("tags") or [],
            alarm_code=payload.get("alarmCode") or "",
            source=payload.get("source") or "portal",
        )
        session_id = payload.get("sessionId") or f"fds-{uuid4().hex[:12]}"
        router_decision, playbook = self.router.route(context)
        yield from playbook.diagnose_stream(
            context=context,
            toolbox=self.toolbox,
            reasoner=self.reasoner,
            router_decision=router_decision,
            session_id=session_id,
        )

    def execute_action(self, payload: dict) -> ActionExecutionResult:
        session_id = payload.get("sessionId") or f"fds-{uuid4().hex[:12]}"
        playbook_id = payload.get("playbookId") or ""
        operation_payload = dict(payload.get("operation") or {})

        if playbook_id == "application-timeout":
            from .playbooks import ApplicationTimeoutPlaybook

            playbook = ApplicationTimeoutPlaybook()
        else:
            from .playbooks import GenericAlarmPlaybook

            playbook = GenericAlarmPlaybook()

        return playbook.execute_action(
            operation=operation_payload,
            toolbox=self.toolbox,
            reasoner=self.reasoner,
            session_id=session_id,
        )
