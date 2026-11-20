"""Execute a confirmed retry of the bounded Portal CMDB lookup."""
from __future__ import annotations

import json
import logging
from contextlib import aclosing

from agentscope.permission import PermissionBehavior

from ...agents.skill_system import resolve_effective_skills
from ...constant import WORKING_DIR
from ...extensions.integrations.zgops_cmdb.portal_asset_lookup import (
    lookup_portal_cmdb_asset,
    portal_asset_lookup_available,
)
from ...extensions.security.execution_policy import check_tool
from ...runtime.builder import AgentBuilder


logger = logging.getLogger(__name__)


def cmdb_enabled(workspace) -> bool:
    if workspace.agent_id != "gateway":
        return False
    try:
        skills = resolve_effective_skills(workspace.workspace_dir or WORKING_DIR, "console")
    except Exception:
        logger.warning("Could not resolve the Portal CMDB skill", exc_info=True)
        return False
    return portal_asset_lookup_available(workspace.agent_id, skills, {"channel": "console"})


async def retry_cmdb_lookup(workspace, chat, name: str, approval_level: str) -> str:
    if not cmdb_enabled(workspace):
        return "当前智能体未开放 CMDB 精确查询。"
    params = {"name": name}
    governor = AgentBuilder._init_governor(workspace.workspace_dir or WORKING_DIR)
    try:
        if governor is None and await check_tool(lookup_portal_cmdb_asset.__name__, params):
            return "治理策略要求审批，未执行 CMDB 查询。"
        context = {
            "agent_id": workspace.agent_id,
            "session_id": chat.session_id,
            "user_id": chat.user_id,
            "channel": chat.channel,
            "approval_level": approval_level,
        }
        from ...extensions.security import portal_capabilities as permissions

        context[permissions.CONTEXT_KEY] = permissions.invocation_for(
            chat.user_id, workspace.agent_id, chat.session_id, chat.channel,
        )
        tool = AgentBuilder._wrap_tool(lookup_portal_cmdb_asset, workspace.agent_id, context, governor)
        decision = await tool.check_permissions(params)
        if decision.behavior != PermissionBehavior.ALLOW:
            return "治理策略未允许本次 CMDB 查询。"
        result = await tool(**(decision.updated_input if decision.updated_input is not None else params))
        if hasattr(result, "aclose"):
            async with aclosing(result):
                result = await anext(result)
        payload = json.loads(result.content[0].text)
    except PermissionError as exc:
        return str(exc)
    except (ValueError, AttributeError, IndexError, StopAsyncIteration):
        return "智观 CMDB 未返回可用的查询结果。"
    finally:
        if governor is not None:
            governor.stop()

    if payload.get("status") != "ok":
        return payload["message"]
    rows = []
    for asset in payload["assets"]:
        asset_id = asset.get("_id")
        rows.append(f"- 资产：{asset['name']}" + (f"；标识：{asset_id}" if asset_id is not None else ""))
    return "\n".join([payload["message"], *rows])
