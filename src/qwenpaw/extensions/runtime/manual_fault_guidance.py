# -*- coding: utf-8 -*-
"""Inject fixed manual-operation policy without modifying user messages."""

from __future__ import annotations

from agentscope.agent import Agent
from agentscope.middleware import MiddlewareBase

from qwenpaw.hooks.base import LifecycleHook
from qwenpaw.runtime.hooks import HookContext, HookResult
from qwenpaw.runtime.phases import Phase

MANUAL_FAULT_GUIDANCE_INSTRUCTIONS = "\n".join(
    (
        "[CMDB 人工处置指南约束]",
        (
            "核心要求：结合 CMDB 明确的实际部署环境给完整处置建议，不能只给组件内部操作。"
            "K3s/Kubernetes、裸 Docker、主机或托管环境使用对应访问路径，"
            "关联到平台不自动等于部署于该平台。"
        ),
        (
            "完整人工步骤应包含：已有授权环境准备 → 目标/容器确认 → 组件访问 → "
            "版本和实例核验 → 只读排查 → 条件性修复及审批 → 恢复验证；"
            "每步注明执行位置、前提和风险。"
        ),
        (
            "首轮回答的处置建议必须从 Step 0「进入管理环境」开始，"
            "环境表或总流程图不能代替操作步骤。若从服务器操作，"
            "先给运维人工 SSH 到已确认管理机的模板；"
            "已有授权 kubeconfig 的终端可直接操作。"
            "K3s 场景必须先核对 context、Namespace、Pod、容器，"
            "再给 kubectl exec -- mysql，不能直接从 mysql -h 开始；"
            "禁止 AI 执行 SSH 不等于禁止给用户人工命令。"
        ),
        (
            "K8s 与 Docker 同时出现在关联列表时，先说明承载关系未唯一确认，"
            "并给条件性平台访问路径；不能用斜杠合并当成已确认部署，"
            "也不能因参数缺失省掉管理入口。部署宿主机不自动等于控制平面，"
            "数据库管理 IP 不自动等于 SSH 地址。"
        ),
        (
            "CMDB db_port 可能是 NodePort/Service/宿主映射端口，"
            "不能直接用作容器内 MySQL 监听端口；"
            "容器内 DB_PORT 须有明确监听字段或运维现场核验。"
            "CMDB login_user 不作为指令账号，也不展示登录字段，"
            "DB_USER 由运维本地填写。宿主阈值告警和内存配置大小"
            "不能直接证明慢 SQL 根因或资源耗尽。"
        ),
        (
            "当前只能用 CMDB 提供部署关系和字段；"
            "系统不得自行 SSH、kubectl exec 或登录数据库补证据，"
            "不索要/获取服务器和数据库密码、私钥、登录 token。"
            "已配置 MCP 的内部鉴权照常。"
        ),
        (
            "参数有 CMDB 依据才绑定；未知 context、Namespace、Pod、容器、账号、"
            "端口由运维现场确认，不默认 root/default/mysql-0。"
            "密码只在运维本地交互输入，不提交给 AI。"
        ),
        (
            "用户需要执行的运维命令和多行 shell/SQL 必须完整展示并可复制；"
            "不要只显示内部 skill 脚本调用，也不要为简短或详细模式删掉访问前置步骤。"
        ),
        (
            "人工指南未执行，不能写已登录、已验证或已修复；"
            "它不生成自动执行 action。慢 SQL 不默认 KILL，"
            "只有具体证据、当前目标与审批满足后才给条件性处置。"
            "既有业务接口的权限和审批不扩大。"
        ),
    )
)


class ManualFaultPromptMiddleware(MiddlewareBase):
    """Transform only the model's system prompt, never persisted user input."""

    async def on_system_prompt(self, agent: Agent, current_prompt: str) -> str:
        if MANUAL_FAULT_GUIDANCE_INSTRUCTIONS in current_prompt:
            return current_prompt
        return (
            current_prompt.rstrip()
            + "\n\n"
            + MANUAL_FAULT_GUIDANCE_INSTRUCTIONS
        )


class ManualFaultGuidanceHook(LifecycleHook):
    """Install the policy on the current request's newly constructed agent."""

    phase = Phase.PRE_EXECUTE
    name = "portal_manual_fault_guidance"
    priority = 100

    async def run(self, ctx: HookContext) -> HookResult:
        request_context = getattr(ctx.request, "request_context", None)
        if (
            getattr(ctx.request, "channel", None) == "console"
            and isinstance(request_context, dict)
            and request_context.get("portal_manual_fault_guidance") is True
        ):
            # AgentScope 2.0.2 snapshots this list at construction and has no
            # public post-construction registration method.
            middlewares = getattr(
                ctx.agent, "_system_prompt_middlewares", None
            )
            if not isinstance(middlewares, list):
                raise RuntimeError(
                    "AgentScope system-prompt middleware is unavailable"
                )
            if not any(
                isinstance(item, ManualFaultPromptMiddleware)
                for item in middlewares
            ):
                middlewares.append(ManualFaultPromptMiddleware())
        return HookResult()
