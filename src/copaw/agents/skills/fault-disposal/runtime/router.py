from __future__ import annotations

from .models import RouterDecision, TicketContext
from .playbooks import ApplicationTimeoutPlaybook, GenericAlarmPlaybook


class TicketRouter:
    def __init__(self) -> None:
        self.playbooks = [
            ApplicationTimeoutPlaybook(),
            GenericAlarmPlaybook(),
        ]

    def route(self, context: TicketContext):
        decisions: list[tuple[RouterDecision, object]] = []
        for playbook in self.playbooks:
            decision = playbook.match(context)
            decisions.append((decision, playbook))

        return max(decisions, key=lambda item: item[0].score)
