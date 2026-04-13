from __future__ import annotations

from typing import Protocol

from ..models import ActionExecutionResult, DiagnosisResult, RouterDecision, TicketContext
from ..reasoners import TemplateReasoner
from ..tool_adapters import FaultDisposalToolbox


class Playbook(Protocol):
    id: str
    name: str

    def match(self, context: TicketContext) -> RouterDecision:
        ...

    def diagnose(
        self,
        *,
        context: TicketContext,
        toolbox: FaultDisposalToolbox,
        reasoner: TemplateReasoner,
        router_decision: RouterDecision,
        session_id: str,
    ) -> DiagnosisResult:
        ...

    def diagnose_stream(
        self,
        *,
        context: TicketContext,
        toolbox: FaultDisposalToolbox,
        reasoner: TemplateReasoner,
        router_decision: RouterDecision,
        session_id: str,
    ):
        ...

    def execute_action(
        self,
        *,
        operation: dict,
        toolbox: FaultDisposalToolbox,
        reasoner: TemplateReasoner,
        session_id: str,
    ) -> ActionExecutionResult:
        ...
