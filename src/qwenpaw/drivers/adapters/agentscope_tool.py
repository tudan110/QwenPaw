# -*- coding: utf-8 -*-
"""AgentScope runtime adapter for Driver capabilities.

Driver owns capability discovery and policy execution.  This module is the
thin boundary that turns those protocol-neutral capabilities into
AgentScope ``ToolBase`` instances for the agent runtime.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from agentscope.message import (
    Base64Source,
    DataBlock,
    TextBlock,
    ToolResultState,
)
from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.tool import ToolBase, ToolChunk

from ..capabilities import (
    DriverCapability,
    DriverInvocation,
    DriverInvocationResult,
)

logger = logging.getLogger(__name__)

DriverInvoker = Callable[[DriverInvocation], Awaitable[DriverInvocationResult]]


def _text_block(text: str) -> Any:
    return TextBlock(type="text", text=text)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    model_dump_json = getattr(value, "model_dump_json", None)
    if callable(model_dump_json):
        return model_dump_json(indent=2)
    try:
        return json.dumps(value, ensure_ascii=False, default=str, indent=2)
    except TypeError:
        return str(value)


def _blocks_from_mcp_content(content: Any) -> list[Any]:
    blocks: list[Any] = []
    for item in content or []:
        text = getattr(item, "text", None)
        if text is not None:
            blocks.append(_text_block(str(text)))
            continue

        data = getattr(item, "data", None)
        mime_type = getattr(item, "mimeType", None)
        if data is not None and mime_type:
            blocks.append(
                DataBlock(
                    source=Base64Source(
                        type="base64",
                        media_type=str(mime_type),
                        data=str(data),
                    ),
                ),
            )
            continue

        resource = getattr(item, "resource", None)
        if resource is not None:
            resource_text = getattr(resource, "text", None)
            blocks.append(
                _text_block(
                    (
                        str(resource_text)
                        if resource_text is not None
                        else _stringify(resource)
                    ),
                ),
            )
            continue

        blocks.append(_text_block(_stringify(item)))
    return blocks


def _blocks_from_value(value: Any) -> list[Any]:
    content = getattr(value, "content", None)
    is_mcp_call_result = content is not None and hasattr(value, "isError")
    if is_mcp_call_result:
        blocks = _blocks_from_mcp_content(content)
        structured = getattr(value, "structuredContent", None)
        if structured is not None:
            blocks.append(_text_block(_stringify(structured)))
        return blocks or [_text_block("")]
    return [_text_block(_stringify(value))]


def _tool_chunk_from_driver_result(result: DriverInvocationResult) -> Any:
    if result.ok:
        value = result.value
        state = (
            ToolResultState.ERROR
            if bool(getattr(value, "isError", False))
            else ToolResultState.SUCCESS
        )
        return ToolChunk(
            content=_blocks_from_value(value),
            state=state,
            is_last=True,
            metadata=dict(result.metadata or {}),
        )

    error_payload = {
        "ok": False,
        "type": result.error_type,
        "message": result.message,
        "metadata": result.metadata,
    }
    denied = result.error_type in {"permission_denied", "driver_policy_denied", "driver_policy_approval_required"}
    return ToolChunk(
        content=[_text_block(_stringify(error_payload))],
        state=ToolResultState.DENIED if denied else ToolResultState.ERROR,
        is_last=True,
        metadata=dict(result.metadata or {}),
    )


class DriverCapabilityTool(ToolBase):
    """Expose one Driver capability as an AgentScope ToolBase instance."""

    name = ""
    description = ""
    input_schema: dict[str, Any] = {}
    is_concurrency_safe = False
    is_read_only = False
    is_external_tool = False
    is_state_injected = False
    is_mcp = False
    mcp_name = None

    def __init__(
        self,
        capability: DriverCapability,
        invoker: DriverInvoker,
        request_context: dict[str, str] | None = None,
    ) -> None:
        self.name = capability.exposure.tool_name or capability.name
        self.description = capability.description
        self.input_schema = dict(capability.input_schema or {})
        self._capability = capability
        self._invoker = invoker
        self._request_context = dict(request_context or {})

    async def check_permissions(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> Any:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="Driver capability policy is handled by Driver.",
        )

    async def __call__(self, **kwargs: Any) -> Any:
        result = await self._invoker(
            DriverInvocation(
                capability_id=self._capability.capability_id,
                payload=dict(kwargs or {}),
                request_context=self._request_context,
            ),
        )
        return _tool_chunk_from_driver_result(result)


class WorkOrderExportCheckTool(DriverCapabilityTool):
    """Prepare a controlled export with the authorized work-order list tool."""

    is_read_only = True

    def __init__(
        self, capability: DriverCapability, invoker: DriverInvoker,
        request_context: dict[str, str],
    ) -> None:
        super().__init__(capability, invoker, request_context)
        from .work_order_export import WORK_ORDER_EXPORT_TOOL

        self.name = WORK_ORDER_EXPORT_TOOL
        self.description = (
            "准备待办或已办工单明细导出，按当前单次上限核验。"
            "仅用于导出请求，必须保留用户的筛选范围。通过后返回用户确认下载的链接，而非工单明细。"
            "请原样返回链接、条数、上限或拒绝原因，未确认前不要说已经下载。"
        )
        self.input_schema = {
            "type": "object",
            "properties": {
                "classify": {"type": "integer", "enum": [1, 5], "description": "1=待办，5=已办"},
                "startTime": {"type": "string", "description": "可选，YYYY-MM-DD HH:mm:ss"},
                "endTime": {"type": "string", "description": "可选，YYYY-MM-DD HH:mm:ss"},
            },
            "required": ["classify"],
            "additionalProperties": False,
        }

    async def __call__(self, **kwargs: Any) -> Any:
        from .work_order_export import preflight

        supported = self._capability.input_schema.get("properties") or {}
        if any(key in kwargs and key not in supported for key in ("startTime", "endTime")):
            return ToolChunk(
                content=[_text_block("当前工单接口不支持指定的时间筛选，无法核验导出范围，未导出文件。")],
                state=ToolResultState.ERROR,
                is_last=True,
            )
        page_schema = supported.get("per_page")
        page_cap = page_schema.get("maximum") if isinstance(page_schema, dict) else None
        state, message = await preflight(
            self._invoker, self._capability.capability_id, self._request_context, kwargs,
            page_size_cap=page_cap if type(page_cap) is int and page_cap > 0 else None,
        )
        return ToolChunk(content=[message], state=state, is_last=True)


async def build_driver_agent_tools(
    driver_manager: Any | None,
    request_context: dict[str, str],
    *,
    discovery_states: dict[str, str] | None = None,
) -> tuple[list[ToolBase], list[str]]:
    """Build AgentScope tools and prompt hints from active Drivers.

    Keeping this assembly here lets ``stream_query`` stay focused on request
    streaming while Driver remains responsible for capability discovery and
    the AgentScope adapter boundary.
    """
    states = discovery_states if discovery_states is not None else {}
    states.clear()
    if driver_manager is None:
        return [], []

    try:
        drivers = await driver_manager.list_drivers()
    except Exception:
        states["*"] = "mcp_discovery_failed"
        logger.warning("Could not list Drivers for tool discovery")
        return [], []

    from ...extensions.security import portal_capabilities as permissions

    scope = permissions.invocation_from_context(request_context)
    overrides = await permissions.read_settings(scope) if scope is not None else {}
    tools: list[ToolBase] = []
    order_lists: list[DriverCapability] = []
    for driver in drivers:
        if not driver.enabled or driver.status != "active":
            continue
        if getattr(driver, "protocol", None) == "mcp" and overrides.get(("mcp", driver.name), (None, None))[0] == "revoked":
            states[driver.name] = "user_revoked"
            continue
        try:
            capabilities = await driver_manager.list_driver_capabilities(
                driver.name,
                kind="tool",
                request_context=request_context,
            )
            exposed = [cap for cap in capabilities if cap.exposure.as_tool]
            driver_tools = [
                DriverCapabilityTool(cap, driver_manager.invoke_capability, request_context)
                for cap in exposed
            ]
            order_lists.extend(
                cap for cap in exposed
                if cap.protocol == "mcp"
                and cap.driver_name == "order"
                and cap.name == "listWorkOrders"
            )
        except (ConnectionError, TimeoutError):
            states[driver.name] = "mcp_transport_unavailable"
            logger.warning(
                "Driver '%s' tool transport unavailable", driver.name
            )
            continue
        except Exception:
            states[driver.name] = "mcp_discovery_failed"
            logger.warning("Driver '%s' tool discovery failed", driver.name)
            continue
        states[driver.name] = (
            "mcp_ready" if driver_tools else "no_exposed_tools"
        )
        tools.extend(driver_tools)

    if not tools:
        return [], []

    from ...agents.prompt import build_driver_policy_recheck_hint
    from ...extensions.security.execution_policy import enabled as production_guards

    if len(order_lists) == 1 and production_guards():
        tools.append(WorkOrderExportCheckTool(
            order_lists[0], driver_manager.invoke_capability, request_context,
        ))
    return tools, [build_driver_policy_recheck_hint()]
