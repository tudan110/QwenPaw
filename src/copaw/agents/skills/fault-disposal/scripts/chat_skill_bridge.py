#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path


def _load_runtime_modules():
    skill_root = Path(__file__).resolve().parents[1]
    if str(skill_root) not in sys.path:
        sys.path.insert(0, str(skill_root))

    from runtime.models import TicketContext
    from runtime.playbooks import ApplicationTimeoutPlaybook, GenericAlarmPlaybook
    from runtime.reasoners import TemplateReasoner
    from runtime.router import TicketRouter
    from runtime.tool_adapters import FaultDisposalToolbox

    return (
        TicketContext,
        TicketRouter,
        FaultDisposalToolbox,
        TemplateReasoner,
        ApplicationTimeoutPlaybook,
        GenericAlarmPlaybook,
    )


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _load_context(context_file: str) -> dict:
    raw_text = Path(context_file).expanduser().read_text(encoding="utf-8")
    payload = json.loads(raw_text or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError("Context JSON must be an object")
    return payload


def _render_process_block(block) -> str:
    parts = [f"## {block.title}"]
    if block.subtitle:
      parts.append(f"> {block.subtitle}")
    if block.content:
      parts.append(str(block.content).strip())
    return "\n\n".join(part for part in parts if part)


def _render_portal_action_block(action_payload: dict) -> str:
    return "\n".join(
        [
            "```portal-action",
            json.dumps(action_payload, ensure_ascii=False, indent=2),
            "```",
        ]
    )


def _render_messages_to_markdown(messages: list, *, include_action_block: bool) -> str:
    sections: list[str] = []

    for message in messages:
        if getattr(message, "content", ""):
            sections.append(str(message.content).strip())

        for block in getattr(message, "process_blocks", []) or []:
            rendered_block = _render_process_block(block)
            if rendered_block:
                sections.append(rendered_block)

        action = getattr(message, "action", None)
        if action:
            action_payload = action.to_dict()
            sections.extend(
                [
                    "## 建议动作",
                    f"- 动作名称：{action_payload.get('title') or action_payload.get('type') or '未命名动作'}",
                    f"- 动作摘要：{action_payload.get('summary') or '无'}",
                    f"- 风险等级：{action_payload.get('riskLevel') or action_payload.get('risk_level') or 'medium'}",
                    "",
                    "如确认执行当前建议动作，请直接回复：`执行建议动作`。",
                ]
            )
            if include_action_block:
                sections.append(_render_portal_action_block(action_payload))

    return "\n\n".join(section for section in sections if section).strip()


def _collect_diagnosis_messages(payload: dict):
    (
        TicketContext,
        TicketRouter,
        FaultDisposalToolbox,
        TemplateReasoner,
        _ApplicationTimeoutPlaybook,
        _GenericAlarmPlaybook,
    ) = _load_runtime_modules()

    context = TicketContext(
        entry_workorder=payload.get("entryWorkorder") or {},
        workorders=payload.get("workorders") or [],
        tags=payload.get("tags") or [],
        alarm_code=payload.get("alarmCode") or "",
        source=payload.get("source") or "portal-chat",
    )
    session_id = payload.get("sessionId") or f"fault-skill-{uuid.uuid4().hex[:12]}"

    router = TicketRouter()
    toolbox = FaultDisposalToolbox()
    reasoner = TemplateReasoner()
    router_decision, playbook = router.route(context)

    if playbook.id == "application-timeout":
        (
            related_workorders,
            root_cause_ticket,
            app_snapshot,
            slow_sql_snapshot,
            _tool_calls,
        ) = playbook._collect_diagnosis_inputs(context=context, toolbox=toolbox)
        messages = playbook._render_messages(
            context=context,
            reasoner=reasoner,
            session_id=session_id,
            related_workorders=related_workorders,
            root_cause_ticket=root_cause_ticket,
            app_snapshot=app_snapshot,
            slow_sql_snapshot=slow_sql_snapshot,
        )
        return {
            "sessionId": session_id,
            "routerDecision": router_decision.to_dict(),
            "playbookId": playbook.id,
            "playbookName": playbook.name,
            "messages": messages,
        }

    diagnosis = playbook.diagnose(
        context=context,
        toolbox=toolbox,
        reasoner=reasoner,
        router_decision=router_decision,
        session_id=session_id,
    )
    return {
        "sessionId": diagnosis.session_id,
        "routerDecision": diagnosis.router.to_dict(),
        "playbookId": diagnosis.playbook_id,
        "playbookName": diagnosis.playbook_name,
        "messages": diagnosis.messages,
    }


def _execute_default_action(payload: dict):
    (
        TicketContext,
        TicketRouter,
        FaultDisposalToolbox,
        TemplateReasoner,
        _ApplicationTimeoutPlaybook,
        _GenericAlarmPlaybook,
    ) = _load_runtime_modules()

    context = TicketContext(
        entry_workorder=payload.get("entryWorkorder") or {},
        workorders=payload.get("workorders") or [],
        tags=payload.get("tags") or [],
        alarm_code=payload.get("alarmCode") or "",
        source=payload.get("source") or "portal-chat",
    )
    session_id = payload.get("sessionId") or f"fault-skill-{uuid.uuid4().hex[:12]}"
    router = TicketRouter()
    toolbox = FaultDisposalToolbox()
    reasoner = TemplateReasoner()
    _router_decision, playbook = router.route(context)

    if playbook.id != "application-timeout":
        raise RuntimeError("当前工单类型没有可执行的标准处置动作")

    (
        related_workorders,
        root_cause_ticket,
        app_snapshot,
        slow_sql_snapshot,
        _tool_calls,
    ) = playbook._collect_diagnosis_inputs(context=context, toolbox=toolbox)
    messages = playbook._render_messages(
        context=context,
        reasoner=reasoner,
        session_id=session_id,
        related_workorders=related_workorders,
        root_cause_ticket=root_cause_ticket,
        app_snapshot=app_snapshot,
        slow_sql_snapshot=slow_sql_snapshot,
    )
    action = next((message.action for message in messages if getattr(message, "action", None)), None)
    if not action:
        raise RuntimeError("当前诊断结果未生成可执行动作")

    execution = playbook.execute_action(
        operation=action.to_dict(),
        toolbox=toolbox,
        reasoner=reasoner,
        session_id=session_id,
    )
    return {
        "sessionId": execution.session_id,
        "playbookId": playbook.id,
        "playbookName": playbook.name,
        "messages": execution.messages,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Standard skill bridge for fault-disposal chat orchestration",
    )
    parser.add_argument("command", choices=["diagnose", "execute"])
    parser.add_argument("--context-file", required=True)
    args = parser.parse_args()

    payload = _load_context(args.context_file)
    if args.command == "diagnose":
        result = _collect_diagnosis_messages(payload)
        print(
            _render_messages_to_markdown(
                result["messages"],
                include_action_block=True,
            )
        )
        return

    result = _execute_default_action(payload)
    print(
        _render_messages_to_markdown(
            result["messages"],
            include_action_block=False,
        )
    )


if __name__ == "__main__":
    main()
