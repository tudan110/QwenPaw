"""Server-side dispositions for findings with an existing safe runtime control."""
from __future__ import annotations

from pathlib import Path

from ..exceptions import SkillsError
from ..extensions.security import call_admission
from . import component_events


def _usable(value: str) -> bool:
    return value != "[标识已隐藏]" and call_admission.valid_identifier(value)


def _skill_entries(workspace: Path) -> dict:
    from ..agents.skill_system.store import read_skill_manifest

    return read_skill_manifest(workspace).get("skills", {})


def with_actions(report: dict | None, workspaces: dict[str, Path]) -> dict | None:
    if not report:
        return report
    manifests = {}
    rules = None
    visible_rows = []
    for index, item in enumerate(report["rows"]):
        row = dict(item)
        if row["status"] == "findings" and _usable(row["name"]):
            name, scope = row["name"], row["scope"]
            if row["kind"] == "skill" and scope in workspaces:
                if scope not in manifests:
                    manifests[scope] = _skill_entries(workspaces[scope])
                entry = manifests[scope].get(name)
                if isinstance(entry, dict):
                    row["action"] = {
                        "index": index,
                        "kind": "disable_skill",
                        "done": not entry.get("enabled", False),
                    }
            elif row["kind"] == "mcp" and scope in workspaces:
                if rules is None:
                    rules = call_admission.read_rules()
                rule = rules.get(call_admission.Target("mcp_service", name), {})
                row["action"] = {
                    "index": index,
                    "kind": "isolate_mcp",
                    "done": rule.get("decision") == "deny",
                }
        visible_rows.append(row)
    return {**report, "rows": visible_rows}


def apply(report: dict, index: int, workspaces: dict[str, Path], *, actor: str) -> tuple[str, str | None]:
    row = report["rows"][index]
    action = row.get("action")
    if not action:
        raise ValueError("该检查项没有可由本页执行的处置，请通过对应管理入口处理。")
    if action["done"]:
        return "该组件已停用或隔离，无需重复操作。", None
    name, scope = row["name"], row["scope"]
    if action["kind"] == "disable_skill":
        from ..agents.skill_system.store import get_workspace_skills_dir, safe_skill_dir
        from ..agents.skill_system.workspace_service import SkillService

        workspace = workspaces[scope]
        try:
            skill = safe_skill_dir(get_workspace_skills_dir(workspace), name)
        except SkillsError as exc:
            raise ValueError("该技能已变化或不再存在，请重新扫描。") from exc
        if not (skill / "SKILL.md").is_file() or not (
            SkillService(workspace).disable_skill(name)["success"]
        ):
            raise ValueError("该技能已变化或不再存在，请重新扫描。")
        before, after = {"enabled": True}, {"enabled": False}
        component_events.record(
            "skill", name, scope, before, after, supply=True,
            summaries=(before, after), visible_fields={"enabled"},
        )
        return "已停用该数字员工的技能，未删除文件。", scope

    # This dispatch control is deployment-wide by connection identifier.
    from ..drivers.errors import DriverCardError
    from ..drivers.storage import list_card_paths, load_card

    cards = workspaces[scope] / "drivers"
    matches = [
        path for path in list_card_paths(cards)
        if path.parent.name == "mcp" and path.stem == name
    ]
    try:
        valid = len(matches) == 1 and load_card(matches[0]).name == name
    except (DriverCardError, ValueError):
        valid = False
    if not valid:
        raise ValueError("该连接已变化或不再存在，请重新扫描。")
    target = call_admission.Target("mcp_service", name)
    previous = call_admission.read_rules().get(target, {})
    if previous.get("decision") != "deny":
        call_admission.save_rule(
            target, revision=previous.get("revision", 0), decision="deny",
            risk=previous.get("risk", "high"), reason="扫描发现项：管理员隔离", actor=actor,
        )
        before, after = {"isolated": False}, {"isolated": True}
        component_events.record(
            "mcp", name, "全局", before, after, supply=True,
            summaries=(before, after), visible_fields={"isolated"},
        )
    return "已隔离该连接，后续调用被拒绝，未删除配置。", None
