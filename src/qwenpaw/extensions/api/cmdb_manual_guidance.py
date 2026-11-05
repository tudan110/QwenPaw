# -*- coding: utf-8 -*-
"""CMDB-grounded manual guidance without remote access or credentials."""

from __future__ import annotations

import re
import shlex
from collections import deque
from typing import Any


PUBLIC_DEPLOYMENT_FIELDS = (
    "deployment_kind",
    "deployment_type",
    "deploy_type",
    "cluster_id",
    "cluster_name",
    "k8s_name",
    "kube_context",
    "namespace",
    "namespace_name",
    "pod_name",
    "container_name",
    "docker_name",
    "workload_name",
    "workload_kind",
    "node_name",
    "NodeName",
    "service_name",
    "db_port",
    "db_ip",
    "manage_ip",
    "db_version",
    "db_role",
)
_ENVIRONMENTS = {
    "k3s": "kubernetes",
    "k8s": "kubernetes",
    "kubernetes": "kubernetes",
    "docker": "docker",
    "host": "host",
    "baremetal": "host",
    "physicalmachine": "host",
    "vserver": "host",
    "主机": "host",
    "虚拟机": "host",
}
_PARAMETERS = {
    "KUBE_CONTEXT": ("kube_context",),
    "NAMESPACE": ("namespace", "namespace_name"),
    "MYSQL_POD": ("pod_name",),
    "MYSQL_CONTAINER": ("container_name",),
    "MYSQL_DOCKER_CONTAINER": ("docker_name", "container_name"),
    "DB_PORT": ("db_port",),
    "DB_HOST": ("db_ip", "manage_ip"),
}


def public_deployment_attributes(ci: dict[str, Any]) -> dict[str, str]:
    result = {}
    for key in PUBLIC_DEPLOYMENT_FIELDS:
        value = ci.get(key)
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            continue
        text = str(value).strip()
        if (
            text
            and len(text) <= 240
            and not any(ord(char) < 32 for char in text)
        ):
            result[key] = text
    return result


def _identity(node: dict[str, Any]) -> str:
    return str(node.get("resId") or node.get("_id") or node.get("id") or "")


def _model(node: dict[str, Any]) -> str:
    return str(node.get("ciType") or node.get("ci_type") or "").lower()


def _attributes(node: dict[str, Any]) -> dict[str, str]:
    value = node.get("publicAttributes")
    return public_deployment_attributes(
        value if isinstance(value, dict) else node
    )


def deployment_edges(payload: Any) -> list[dict[str, str]]:
    result = {}

    def walk(value):
        if isinstance(value, dict):
            kind = (
                value.get("relation_type")
                or value.get("relationType")
                or value.get("relation")
            )
            if isinstance(kind, str) and kind.lower() == "deploy":
                source = (
                    value.get("src_ci_id")
                    or value.get("source")
                    or value.get("parent")
                )
                target = (
                    value.get("dst_ci_id")
                    or value.get("target")
                    or value.get("child")
                )
                source = (
                    _identity(source)
                    if isinstance(source, dict)
                    else str(source or "")
                )
                target = (
                    _identity(target)
                    if isinstance(target, dict)
                    else str(target or "")
                )
                if source and target:
                    result[(source, target)] = {
                        "src_ci_id": source,
                        "dst_ci_id": target,
                        "relation_type": "deploy",
                    }
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return list(result.values())


def _placement_nodes(topology: dict[str, Any]) -> list[dict[str, Any]]:
    root = topology.get("rootResource") or {}
    nodes = {_identity(node): node for node in topology.get("resources", [])}
    nodes[_identity(root)] = root
    parents: dict[str, list[str]] = {}
    for edge in topology.get("edges", []) or []:
        kind = str(
            edge.get("relation_type") or edge.get("relationType") or ""
        ).lower()
        if kind != "deploy":
            continue
        source = str(edge.get("src_ci_id") or edge.get("source") or "")
        target = str(edge.get("dst_ci_id") or edge.get("target") or "")
        if source in nodes and target in nodes:
            parents.setdefault(target, []).append(source)
    queue = deque([_identity(root)])
    visited = set()
    result = []
    while queue:
        identity = queue.popleft()
        if identity in visited:
            continue
        visited.add(identity)
        if identity in nodes:
            result.append(nodes[identity])
        queue.extend(parents.get(identity, []))
    return result


def _environment(
    topology: dict[str, Any]
) -> tuple[str, bool, list[dict[str, Any]]]:
    root = topology.get("rootResource") or {}
    placement = _placement_nodes(topology)
    attrs = _attributes(root)
    explicit = {
        _ENVIRONMENTS[value.lower()]
        for key, value in attrs.items()
        if key in ("deployment_kind", "deployment_type", "deploy_type")
        and value.lower() in _ENVIRONMENTS
    }
    if len(explicit) > 1:
        return "unknown", False, [root]
    models = [_model(node) for node in placement[1:]]
    pod_models = {"pod", "kubernetes_pod", "k8s_pod"}
    kubernetes_models = {"kubernetes", "k3s", "k8s"}
    if explicit == {"host"} and any(
        model in kubernetes_models | pod_models | {"docker", "container"}
        for model in models
    ):
        return "unknown", False, [root]
    environment = ""
    if any(model in kubernetes_models | pod_models for model in models):
        environment = "kubernetes"
    elif explicit:
        environment = explicit.pop()
    elif attrs.get("pod_name") and (
        attrs.get("namespace") or attrs.get("namespace_name")
    ):
        environment = "kubernetes"
    else:
        for model in models:
            if model in ("docker", "physicalmachine", "vserver"):
                environment = "docker" if model == "docker" else "host"
                break
    if environment:
        ambiguous = any(
            sum(model in group for model in models) > 1
            for group in (
                kubernetes_models,
                pod_models,
                {"docker", "container"},
                {"physicalmachine"},
                {"vserver"},
            )
        )
        return (
            environment,
            not ambiguous,
            [root] if ambiguous else placement,
        )
    related = {_model(node) for node in topology.get("resources", [])}
    if "kubernetes" in related:
        return "kubernetes", False, [root]
    if "docker" in related:
        return "docker", False, [root]
    return "unknown", False, [root]


def _valid_parameter(name: str, value: str) -> bool:
    if name == "DB_PORT":
        return bool(re.fullmatch(r"[0-9]{1,5}", value)) and (
            1 <= int(value) <= 65535
        )
    if name in ("NAMESPACE", "MYSQL_CONTAINER"):
        return len(value) <= 63 and bool(
            re.fullmatch(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", value)
        )
    if name == "MYSQL_POD":
        return len(value) <= 253 and all(
            len(label) <= 63
            and re.fullmatch(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", label)
            for label in value.split(".")
        )
    if name == "MYSQL_DOCKER_CONTAINER":
        return bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", value))
    return not any(ord(char) < 32 for char in value)


def _parameter_source(
    name: str, node: dict[str, Any], root: dict[str, Any]
) -> bool:
    if _identity(node) == _identity(root):
        return True
    model = _model(node)
    if name == "KUBE_CONTEXT":
        return model == "kubernetes"
    if name in ("NAMESPACE", "MYSQL_POD"):
        return model in (
            "pod",
            "kubernetes_pod",
            "k8s_pod",
            "docker",
            "container",
        )
    if name in ("MYSQL_CONTAINER", "MYSQL_DOCKER_CONTAINER"):
        return model in ("docker", "container")
    return False


def build_manual_operation_guide(
    topology: dict[str, Any],
    *,
    alarm_title: str = "",
) -> dict[str, Any] | None:
    root = topology.get("rootResource") or {}
    if not _identity(root) or not _model(root):
        return None
    environment, confirmed, placement = _environment(topology)
    related = [
        {
            "id": _identity(node),
            "name": str(node.get("name") or ""),
            "type": _model(node),
        }
        for node in topology.get("resources", [])
        if _model(node)
        in ("kubernetes", "docker", "physicalmachine", "vserver")
    ]
    required = ["DB_PORT", "DB_USER"]
    if environment == "kubernetes":
        required = [
            "KUBE_CONTEXT",
            "NAMESPACE",
            "MYSQL_POD",
            "MYSQL_CONTAINER",
            *required,
        ]
    elif environment == "docker":
        required = ["MYSQL_DOCKER_CONTAINER", *required]
    else:
        required = ["DB_HOST", *required]
    if _model(root) != "mysql":
        required = []
    known = {}
    for parameter in required:
        values = {
            attrs[key]
            for node in placement
            for attrs in [_attributes(node)]
            for key in _PARAMETERS.get(parameter, ())
            if _parameter_source(parameter, node, root)
            and key in attrs
            and _valid_parameter(parameter, attrs[key])
        }
        if len(values) == 1:
            known[parameter] = values.pop()
    missing = [name for name in required if name not in known]
    label = {
        "kubernetes": "K3s / Kubernetes",
        "docker": "裸 Docker",
        "host": "主机",
        "unknown": "待确认部署环境",
    }[environment]
    lines = [
        "### 部署环境与人工操作边界",
        f"- 目标 CI：`{_identity(root)}`；组件：`{_model(root)}`；路径：{label}。",
        "- 仅依据 CMDB，系统未访问服务器、集群或数据库；以下命令由运维在已有授权环境中手动执行。",
        "- 不提供或向 AI 提交密码、私钥、登录 token；已知 CMDB 字段不代表权限、连通性或运行状态已验证。",
        "- "
        + (
            "部署方式有 CMDB 明确字段或 deploy 链支持，仍需现场核对当前目标。"
            if confirmed
            else "部署方式或具体承载目标尚未唯一确认；关联到平台不等于部署于该平台，下面是条件性路径，先核对 CMDB 承载关系再使用。"
        ),
        "- "
        + (
            "CMDB 查询范围尚不完整，不能把本指南称为完整承载链。"
            if topology.get("queryComplete") is False
            else "查询范围取全不等于承载链完整；缺少实例边或超出层级的关系仍待确认。"
        ),
    ]
    if missing:
        lines.append(
            "- 待现场填写／核对："
            + "、".join(f"`{name}`" for name in missing)
            + "；不能直接复制未填的模板执行。"
        )
    if _model(root) != "mysql":
        lines.extend(
            [
                "1. 在已有授权入口核对目标部署、版本和当前状态；多候选先确认，不默认任选。",
                "2. 根据该组件实际部署路径使用对应客户端／运维 SOP，不套用 MySQL 命令。",
                "3. 结合本次证据给条件性修复、审批和回退步骤；最后验证组件与业务，不把告警消失当已修复。",
            ]
        )
        return _guide_result(
            environment, confirmed, related, known, missing, lines
        )

    assignments = [
        f"{name}={shlex.quote(known.get(name, '<运维现场确认并填写>'))}"
        for name in required
    ]
    lines.extend(
        [
            "1. **准备授权环境和参数（人工，尚未执行）**。"
            "只使用现有授权入口，不由 AI 建立 SSH 连接；根据目标 CI 核对下列值。",
            "```bash",
            *assignments,
            "```",
        ]
    )
    if environment == "kubernetes":
        lines.extend(
            [
                "2. **在授权的 K3s / Kubernetes 管理环境定位实例**。"
                "选择正确 context 和 Namespace；根据实际承载关系核对 Pod。"
                "多个候选时停止并确认主库／副本，不能用第一条结果代替核验。",
                "```bash",
                "kubectl config get-contexts",
                'kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" '
                "get pods -o wide",
                'kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" '
                'get pod "$MYSQL_POD" '
                "-o jsonpath='{.spec.containers[*].name}'",
                "```",
                "若运维使用已有授权的 K3s 管理机 CLI，"
                "可将上述 kubectl 前缀替换为 `sudo k3s kubectl`；"
                "不要求向 AI 提供登录信息。",
                "3. **登录正确的 MySQL 容器**。核对容器名，确认镜像有 mysql 客户端；密码只在本地交互输入。",
                "```bash",
                'kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" '
                'exec -it "$MYSQL_POD" -c "$MYSQL_CONTAINER" -- '
                'mysql --host=127.0.0.1 --port="$DB_PORT" '
                '--user="$DB_USER" --password',
                "```",
                "若容器没有客户端，不临时创建调试 Pod；"
                "由运维选择已有授权客户端。"
                "只有已确认 Service/端口时才可采用现有连接或端口转发方案。",
            ]
        )
    elif environment == "docker":
        lines.extend(
            [
                "2. **由运维在已授权的 Docker 宿主环境核对目标容器**；"
                "关联到 Docker 不代表已证明裸 Docker 部署，先确认承载关系。",
                "```bash",
                "docker ps --format '{{.ID}} {{.Names}} {{.Status}}'",
                'docker inspect "$MYSQL_DOCKER_CONTAINER" '
                "--format '{{.Name}} {{.State.Status}}'",
                "```",
                "3. **容器内登录 MySQL**。确认目标与客户端，密码自行交互输入；不要把宿主或同 IP 的其他容器当目标。",
                "```bash",
                'docker exec -it "$MYSQL_DOCKER_CONTAINER" '
                'mysql --host=127.0.0.1 --port="$DB_PORT" '
                '--user="$DB_USER" --password',
                "```",
            ]
        )
    else:
        lines.extend(
            [
                "2. **确认主机／托管数据库的实际访问路径**。"
                "由运维使用已有授权入口或数据库客户端；"
                "未知部署时不要按关联平台猜容器路径。",
                "3. **连接目标数据库**。核对地址和端口，不默认 root 账号；密码自行交互输入。",
                "```bash",
                'mysql --host="$DB_HOST" --port="$DB_PORT" '
                '--user="$DB_USER" --password',
                "```",
            ]
        )
    lines.extend(
        [
            "4. **数据库内先核对实例、版本、角色，再只读排查**。确认连接的是目标实例；权限不足就记录缺口，不申请或回传密码。",
            "```sql",
            "SELECT @@hostname, @@port, @@version, @@read_only;",
            "SHOW FULL PROCESSLIST;",
            "SHOW VARIABLES WHERE Variable_name IN "
            "('performance_schema', 'slow_query_log', "
            "'long_query_time', 'log_output');",
            "```",
            "确认 performance_schema 已启用、表可用且有权限后，"
            "查看慢 SQL 摘要；不要为取数据直接开启日志或修改全局配置。",
            "```sql",
            "SELECT SCHEMA_NAME, DIGEST_TEXT, COUNT_STAR,",
            "       SUM_TIMER_WAIT / 1000000000000 AS total_seconds,",
            "       AVG_TIMER_WAIT / 1000000000000 AS avg_seconds",
            "FROM performance_schema.events_statements_summary_by_digest",
            "ORDER BY SUM_TIMER_WAIT DESC LIMIT 10;",
            "```",
            "锁等待按现场确认的版本选择："
            "MySQL 8 使用 performance_schema.data_lock_waits；"
            "MySQL 5.7 使用 information_schema.INNODB_LOCK_WAITS。"
            "目标 SQL／库名由现场核验后做 EXPLAIN，"
            "不用会实际执行语句的 EXPLAIN ANALYZE 代替。",
            "5. **依据证据选择处置，需人工确认审批后执行**。"
            "慢查询计数不能单独证明缺索引，也不能直接批量 KILL；"
            "先确认具体会话、阻塞链、事务、主从角色和业务影响。",
            "如确认需要终止某条异常查询，由运维重新取得当前会话 ID 后执行条件性模板；占位符不能直接运行。",
            "```sql",
            "KILL QUERY <现场重新核验的会话ID>;",
            "```",
            "KILL QUERY 不一定释放整个事务或锁；终止连接可能引起事务回滚。"
            "索引、参数修改、重启、切库需另外核验窗口、备份及回退方案，"
            "未知表／列时不编造 DDL。",
            "6. **恢复验证与后续治理（人工，未验证）**。"
            "复查会话、锁等待、慢查询摘要及延迟；"
            "K3s / Docker 场景同时核对工作负载状态，再验证实际业务请求。"
            "依据变更记录回退已实施配置／SQL变更，"
            "不能声称 KILL 可恢复原事务；告警消失不等于业务恢复。",
            "只反馈脱敏后的必要结果，不向 AI 上传凭证或敏感 SQL 参数。本指南为待人工执行建议，不新增自动执行 action。",
        ]
    )
    return _guide_result(
        environment, confirmed, related, known, missing, lines
    )


def _guide_result(environment, confirmed, related, known, missing, lines):
    return {
        "source": "cmdb-only",
        "executionMode": "manual-only",
        "deploymentKind": environment,
        "deploymentConfirmed": confirmed,
        "relatedPlatforms": related,
        "knownParameters": known,
        "missingParameters": missing,
        "markdown": "\n\n".join(lines),
    }
