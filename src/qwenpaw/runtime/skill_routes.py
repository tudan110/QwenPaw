"""Request-local routing hints for the bundled business skills.

DriverCard.enabled is the only switch. This module does not execute scripts
or relax Driver policy; it gives skills an explicit, credential-free route.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Stable Driver keys used by the deployment skills, not display names.
SKILL_DRIVERS: dict[str, tuple[str, ...]] = {
    "real-alarm": ("alarm",),
    "zgops-cmdb": ("cmdb-query",),
    "order-workflow": ("order",),
    "inspection-analyst": ("cmdb-query", "inspection"),
    "resource-insight-query": ("resource",),
    "monitoring-overview-query": ("resource",),
    "web-availability-monitor": ("web-check-app",),
    "alarm-analyst": ("cmdb-query", "alarm", "inspection", "resource"),
}

_RULES = """# Skill execution routes
The following request-local routes override static MCP-first statements in
the listed skills and workspace instructions. Resolve each capability
separately; one skill can use both MCP and scripts.
- script: MCP is disabled or not configured. Directly run the existing
  script documented by that skill, with its normal authorization, parameters,
  dependencies and credentials. Do not probe MCP first. If the script or
  required configuration is missing, report that gap; do not enable MCP.
- mcp: use only the listed exposed tools. Driver authorization and approval
  still run at invocation time. Missing tools are NOT permission to use a
  script; tool whitelist exclusions must not be bypassed.
- blocked: no exposed tools; do not bypass access restrictions via scripts.
- unavailable: status is unknown or the enabled Driver is not ready. Do not
  treat loading/configuration errors as disabled or not configured. Report
  the condition; do not probe alternate identities or endpoints.
  Only reason=mcp_transport_unavailable confirms a discovery transport
  failure: a read-only operation may use its documented script once.
For MCP calls, empty successful results and parseable authentication,
permission, parameter or business errors never trigger script fallback.
Only an explicitly identified connection/transport or protocol failure may
fall back once for a read-only operation. A generic execution_error is not
proof of such a failure. Never replay a write via script after an MCP call
whose outcome is unknown. Keep existing write approvals. Ordinary inspection
scripts must use --no-notify; changing transport must not send notifications.
Use the skill's existing script commands, time windows, pagination and output
rules. Routes are not evidence that credentials or script dependencies work.
"""


async def build_skill_route_hint(
    driver_manager: Any,
    effective_skills: list[str],
    tools: list[Any],
    *,
    discovery_states: dict[str, str] | None = None,
) -> str | None:
    """Read workspace state without inferring absence from tool failure."""
    selected = sorted(set(effective_skills).intersection(SKILL_DRIVERS))
    if not selected:
        return None
    infos = None
    if driver_manager is not None:
        try:
            # Include malformed cards (protocol may be unknown), so a broken
            # alarm card cannot silently become "not configured".
            infos = {
                info.name: info for info in await driver_manager.list_drivers()
            }
        except Exception:
            logger.warning("Could not resolve business skill Driver state")

    exposed: dict[str, list[str]] = {}
    for tool in tools:
        capability = getattr(tool, "_capability", None)
        if capability is not None and capability.protocol == "mcp":
            exposed.setdefault(capability.driver_name, []).append(tool.name)

    routes = []
    for skill in selected:
        for driver in SKILL_DRIVERS[skill]:
            info = infos.get(driver) if infos is not None else None
            names = sorted(exposed.get(driver, []))
            discovery = (discovery_states or {}).get(
                driver, (discovery_states or {}).get("*")
            )
            if infos is None:
                route, reason = "unavailable", "driver_state_unknown"
            elif info is None:
                route, reason = "script", "mcp_not_configured"
            elif info.status == "error" or info.protocol != "mcp":
                route, reason = "unavailable", "driver_configuration_error"
            elif not info.enabled:
                route, reason = "script", "mcp_disabled"
            elif info.status != "active":
                route, reason = "unavailable", "mcp_not_ready"
            elif discovery in {
                "mcp_transport_unavailable",
                "mcp_discovery_failed",
            }:
                route = "unavailable"
                reason = discovery
            elif not names:
                route, reason = "blocked", "no_exposed_tools"
            else:
                route, reason = "mcp", "mcp_ready"
            routes.append(
                {
                    "skill": skill,
                    "driver": driver,
                    "route": route,
                    "reason": reason,
                    "tools": names if route == "mcp" else [],
                }
            )
    return _RULES + "\n" + json.dumps(routes, ensure_ascii=False, indent=2)
