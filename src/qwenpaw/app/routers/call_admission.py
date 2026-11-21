"""Administrator endpoints for call admission policy and side-effect-free checks."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...extensions.api.access_policy import require_browser_origin
from ...extensions.security import call_admission as policy
from ...extensions.security.execution_policy import enabled as production_guards_enabled
from .security_evidence import require_evidence_admin

router = APIRouter(
    prefix="/security/call-admission",
    tags=["call-admission"],
    dependencies=[Depends(require_evidence_admin)],
)


class TargetInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["tool", "script", "api", "mcp_service", "mcp_tool"]
    name: str = Field(min_length=1, max_length=150)
    service: str = Field(default="", max_length=150)

    def target(self) -> policy.Target:
        if (
            not policy.valid_identifier(self.name)
            or (self.kind == "mcp_tool" and not policy.valid_identifier(self.service))
            or (self.kind != "mcp_tool" and self.service)
        ):
            raise HTTPException(422, "请填写精确工具名或 MCP 服务标识，不支持 URL、空格和通配符。")
        target = policy.Target(self.kind, self.name, self.service)
        if self.kind == "tool" and self.name == policy.CMDB_LOOKUP:
            raise HTTPException(422, "请在业务 API 分类配置智观 CMDB 精确查询。")
        if self.kind in {"api", "script"} and target not in policy.catalog():
            raise HTTPException(422, "此 API 或脚本尚未接入逐项控制。")
        return target


class RuleUpdate(TargetInput):
    revision: int = Field(ge=0)
    decision: Literal["inherit", "deny"]
    risk: policy.Risk
    reason: str = Field(max_length=240)

    @field_validator("reason")
    @classmethod
    def reason_required(cls, value: str) -> str:
        value = value.strip()
        if not value or not value.isprintable():
            raise ValueError("请输入单行评估或变更理由。")
        return value


@router.get("")
def list_rules() -> dict:
    try:
        rules = policy.read_rules()
    except policy.PolicyUnavailable as exc:
        raise HTTPException(503, "无法读取调用准入策略。") from exc
    catalog = policy.catalog()
    return {
        "production_guards": production_guards_enabled(),
        "items": [
            policy.describe(target, rules.get(target), catalog.get(target))
            for target in sorted(catalog.keys() | rules.keys())
        ],
    }


@router.put("")
def update_rule(request: Request, body: RuleUpdate) -> dict:
    require_browser_origin(request)
    actor = request.state.access_identity.user_id
    if not actor:
        raise HTTPException(403, "无法确认配置变更主体。")
    target = body.target()
    try:
        rule = policy.save_rule(
            target, revision=body.revision, decision=body.decision,
            risk=body.risk, reason=body.reason, actor=actor,
        )
    except policy.PolicyConflict as exc:
        raise HTTPException(409, "策略已被其他管理员修改，请刷新后再操作。") from exc
    except policy.PolicyUnavailable as exc:
        raise HTTPException(503, "未能写入调用准入策略，请核对后端存储。") from exc
    return policy.describe(target, rule, policy.catalog().get(target))


@router.post("/check")
def check_rule(request: Request, body: TargetInput) -> dict:
    """Run the same restriction query as dispatch, never invoke the target."""
    require_browser_origin(request)
    target = body.target()
    active = target.kind != "script" or production_guards_enabled()
    try:
        blocked = policy.blocked_by(target, script_rules=active)
    except policy.PolicyUnavailable as exc:
        raise HTTPException(503, "策略不可读取，运行时将拒绝受该策略检查的调用。") from exc
    decision = "deny" if blocked else (
        "inherit" if active else "inactive"
    )
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "blocked_by": blocked.name if blocked else None,
    }
