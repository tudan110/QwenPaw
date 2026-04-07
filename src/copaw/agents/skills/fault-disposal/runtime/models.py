from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TicketContext:
    entry_workorder: dict[str, Any]
    workorders: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    alarm_code: str = ""
    source: str = "portal"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RouterDecision:
    playbook_id: str
    playbook_name: str
    score: int
    matched_by: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolCallRecord:
    name: str
    stage: str
    summary: str
    request: dict[str, Any]
    response: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProcessBlock:
    id: str
    kind: str
    icon: str
    title: str
    subtitle: str
    content: str
    default_open: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["defaultOpen"] = payload.pop("default_open")
        return payload


@dataclass
class ActionProposal:
    id: str
    type: str
    title: str
    summary: str
    status: str
    risk_level: str
    params: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["riskLevel"] = payload.pop("risk_level")
        payload.update(payload.pop("params"))
        return payload


@dataclass
class AgentMessage:
    content: str
    process_blocks: list[ProcessBlock] = field(default_factory=list)
    action: ActionProposal | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "kind": "assistant",
            "content": self.content,
            "processBlocks": [block.to_dict() for block in self.process_blocks],
        }
        if self.action:
            payload["action"] = self.action.to_dict()
        return payload


@dataclass
class DiagnosisResult:
    session_id: str
    router: RouterDecision
    playbook_id: str
    playbook_name: str
    reasoner: str
    messages: list[AgentMessage]
    tool_calls: list[ToolCallRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session": {
                "sessionId": self.session_id,
                "playbookId": self.playbook_id,
                "playbookName": self.playbook_name,
                "reasoner": self.reasoner,
            },
            "router": self.router.to_dict(),
            "messages": [message.to_dict() for message in self.messages],
            "toolCalls": [call.to_dict() for call in self.tool_calls],
        }


@dataclass
class ActionExecutionResult:
    session_id: str
    operation: ActionProposal
    messages: list[AgentMessage]
    tool_calls: list[ToolCallRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session": {
                "sessionId": self.session_id,
            },
            "operation": self.operation.to_dict(),
            "messages": [message.to_dict() for message in self.messages],
            "toolCalls": [call.to_dict() for call in self.tool_calls],
        }
