from __future__ import annotations

import asyncio
import csv
import html
import io
import json
import os
import re
import zipfile
import base64
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import httpx
import pandas as pd
from dotenv import dotenv_values

DEFAULT_SUPPORTED_FORMATS = [
    ".csv",
    ".tsv",
    ".xlsx",
    ".xls",
    ".json",
    ".txt",
    ".md",
    ".docx",
    ".png",
    ".jpg",
    ".jpeg",
]

DEFAULT_RELATION_TYPES = ["contain", "deploy", "install", "connect"]

DEFAULT_MODEL_TEMPLATES = [
    {"name": "Department", "alias": "部门", "unique_key": "name"},
    {"name": "product", "alias": "产品", "unique_key": "name"},
    {"name": "project", "alias": "应用", "unique_key": "name"},
    {"name": "PhysicalMachine", "alias": "物理机", "unique_key": "name"},
    {"name": "vserver", "alias": "虚拟机", "unique_key": "name"},
    {"name": "networkdevice", "alias": "网络设备", "unique_key": "name"},
    {"name": "database", "alias": "数据库", "unique_key": "name"},
    {"name": "mysql", "alias": "mySQL", "unique_key": "name"},
    {"name": "PostgreSQL", "alias": "PostgreSQL", "unique_key": "name"},
    {"name": "redis", "alias": "Redis", "unique_key": "name"},
    {"name": "Kafka", "alias": "Kafka", "unique_key": "name"},
    {"name": "elasticsearch", "alias": "elasticsearch", "unique_key": "name"},
    {"name": "nginx", "alias": "Nginx", "unique_key": "name"},
    {"name": "apache", "alias": "Apache", "unique_key": "name"},
    {"name": "docker", "alias": "docker", "unique_key": "name"},
    {"name": "kubernetes", "alias": "kubernetes", "unique_key": "name"},
    {"name": "dcim_idc", "alias": "数据中心", "unique_key": "name"},
    {"name": "dcim_server_room", "alias": "机房", "unique_key": "name"},
    {"name": "dcim_rack", "alias": "机柜", "unique_key": "name"},
    {"name": "ipam_subnet", "alias": "子网", "unique_key": "name"},
    {"name": "ipam_address", "alias": "IP地址", "unique_key": "name"},
]

DEFAULT_ATTRIBUTE_FIELDS = {
    "Department": ["name"],
    "product": ["name"],
    "project": ["name"],
    "PhysicalMachine": ["name", "asset_code", "private_ip", "status", "vendor", "model", "os_version"],
    "vserver": ["name", "asset_code", "private_ip", "status", "os_version"],
    "networkdevice": ["name", "asset_code", "private_ip", "status", "vendor", "model", "upstream_resource"],
    "database": ["name", "private_ip", "status"],
    "mysql": ["name", "private_ip", "status", "version", "service_port", "deploy_target"],
    "PostgreSQL": ["name", "private_ip", "status", "version", "service_port", "deploy_target"],
    "redis": ["name", "private_ip", "status", "version", "service_port", "deploy_target"],
    "Kafka": ["name", "private_ip", "status", "version", "service_port", "deploy_target"],
    "elasticsearch": ["name", "private_ip", "status", "version", "service_port", "deploy_target"],
    "nginx": ["name", "private_ip", "status", "version", "service_port", "deploy_target"],
    "apache": ["name", "private_ip", "status", "version", "service_port", "deploy_target"],
    "docker": ["name", "private_ip", "status", "version", "deploy_target"],
    "kubernetes": ["name", "private_ip", "status", "version", "deploy_target"],
    "dcim_idc": ["name"],
    "dcim_server_room": ["name"],
    "dcim_rack": ["name"],
    "ipam_subnet": ["name"],
    "ipam_address": ["name"],
}

DEFAULT_GROUP_HINTS = {
    "Department": "部门组织",
    "users": "部门组织",
    "product": "业务",
    "project": "业务",
    "PhysicalMachine": "计算资源",
    "vserver": "计算资源",
    "networkdevice": "网络设备",
    "database": "数据库",
    "mysql": "数据库",
    "PostgreSQL": "数据库",
    "redis": "中间件",
    "Kafka": "中间件",
    "elasticsearch": "中间件",
    "nginx": "中间件",
    "apache": "中间件",
    "docker": "容器",
    "kubernetes": "容器",
    "dcim_idc": "IDC",
    "dcim_server_room": "IDC",
    "dcim_rack": "IDC",
    "ipam_subnet": "IPAM",
    "ipam_address": "IPAM",
}

FIELD_ALIASES = {
    "asset_code": ["asset_code", "资产编号", "资源编号", "设备编号", "设备编码", "实例编号", "sn编号", "p_id", "pid"],
    "name": [
        "name",
        "名称",
        "设备名称",
        "资源名称",
        "实例名",
        "实例名称",
        "主机名",
        "主机名称",
        "主机标识",
        "网络节点名",
        "组件实例",
        "project_name",
        "product_name",
        "db_instance",
        "middleware_name",
        "vserver_name",
        "hostname",
        "host name",
        "server name",
    ],
    "ci_type": ["ci_type", "type", "资源类型", "设备类型", "实例类型", "设备大类", "组件类别", "模型", "类型", "_type"],
    "private_ip": [
        "private_ip",
        "ip",
        "ip地址",
        "管理ip",
        "管理地址",
        "管理ip地址",
        "内网ip",
        "ip address",
        "address",
        "db_ip",
        "middleware_ip",
    ],
    "public_ip": ["public_ip", "公网ip", "外网ip"],
    "status": ["status", "状态", "运行状态", "设备状态", "上线情况", "当前可用性", "状态描述"],
    "department": ["department", "部门", "bu", "业务单元"],
    "product": ["product", "产品", "产品线"],
    "project": ["project", "应用", "项目", "系统", "业务系统", "业务归属", "所属应用"],
    "idc": ["idc", "机房", "数据中心", "idc机房"],
    "server_room": ["server_room", "机房分区", "机房区域", "server room"],
    "rack": ["rack", "机柜", "机柜位置"],
    "subnet": ["subnet", "网段", "子网", "cidr"],
    "host_name": ["host_name", "宿主机", "部署主机", "主机", "所属主机", "宿主机/集群"],
    "deploy_target": ["deploy_target", "部署目标", "运行节点", "部署节点", "AssociatedVM", "AssociatedPhyMachine"],
    "upstream_resource": ["upstream_resource", "上联核心", "上级设备", "上联设备"],
    "os_version": ["os_version", "操作系统", "操作系统版本", "os", "系统版本"],
    "vendor": ["vendor", "厂商", "品牌", "厂商品牌"],
    "model": ["model", "型号", "机型", "规格型号", "服务器型号", "设备型号"],
    "version": ["version", "版本", "版本号", "数据库版本", "设备软件版本"],
    "service_port": ["service_port", "端口", "服务端口", "db_port", "middleware_port"],
    "monitor_status": ["monitor_status", "监控接入", "监控状态"],
    "owner": ["owner", "负责人", "维护团队", "owner", "运维负责人"],
    "environment": ["environment", "环境", "env", "运行环境"],
    "description": ["description", "描述", "备注", "说明"],
    "dev_no": ["dev_no", "设备编码", "设备编号", "网络设备编码", "网络设备编号"],
    "dev_name": ["dev_name", "设备名称", "网络设备名称", "节点名称"],
    "manage_ip": ["manage_ip", "管理ip", "管理地址", "管理ip地址", "设备管理ip"],
    "dev_model": ["dev_model", "设备型号", "设备规格", "网络设备型号"],
    "dev_class": ["dev_class", "设备大类", "网络设备类型", "设备分类"],
    "alarm_status": ["alarm_status", "告警状态", "高级状态元数据", "状态编码"],
    "dev_software_version": ["dev_software_version", "设备软件版本", "软件版本", "软件版本号"],
    "dev_sn": ["dev_sn", "设备序列号", "序列号", "序列号sn", "设备sn"],
    "property_no": ["property_no"],
    "city": ["city", "地市", "城市"],
    "county": ["county", "区县", "区"],
    "data_center": ["data_center", "所属数据中心"],
    "platform": ["platform", "平台", "采集平台", "纳管平台"],
    "op_duty": ["op_duty", "运维负责人", "运维组", "责任人", "维护人"],
    "u_count": ["u_count", "u数", "设备u数"],
    "u_start": ["u_start", "起始u位", "起始u", "开始u位"],
    "cabinet": ["cabinet", "所属机柜", "机柜柜位"],
}

RELATION_FIELD_ALIASES = {
    "source_model": ["source_model", "源模型", "源资源模型", "源类型", "源资源类型", "父模型", "上游模型", "from_model"],
    "source_field": ["source_field", "source_unique_field", "源字段", "源属性", "源唯一字段", "源标识字段", "父字段", "from_field"],
    "source_value": ["source_value", "source_unique_value", "源值", "源资源", "源资源标识", "源实例", "源名称", "源资源名称", "父资源", "from", "source"],
    "target_model": ["target_model", "目标模型", "目标资源模型", "目标类型", "目标资源类型", "子模型", "下游模型", "to_model"],
    "target_field": ["target_field", "target_unique_field", "目标字段", "目标属性", "目标唯一字段", "目标标识字段", "子字段", "to_field"],
    "target_value": ["target_value", "target_unique_value", "目标值", "目标资源", "目标资源标识", "目标实例", "目标名称", "目标资源名称", "子资源", "to", "target"],
    "relation_type": ["relation_type", "关系", "关系类型", "关联类型", "连接类型", "link_type", "relation"],
}

RELATION_TYPE_ALIASES = {
    "contain": ["contain", "包含", "归属", "属于", "所属", "拥有", "纳管"],
    "deploy": ["deploy", "部署", "运行于", "部署于", "宿主", "挂载"],
    "install": ["install", "安装", "安装于", "实例化"],
    "connect": ["connect", "连接", "关联", "依赖", "上联", "下联", "通信"],
}

CI_TYPE_ALIASES = {
    "Department": ["department", "部门", "bu", "业务单元"],
    "product": ["product", "产品", "产品线"],
    "project": ["project", "应用", "项目", "业务系统", "system"],
    "PhysicalMachine": ["physicalmachine", "物理机", "服务器", "server", "裸机"],
    "vserver": ["vserver", "虚拟机", "vm", "虚机"],
    "networkdevice": ["networkdevice", "交换机", "路由器", "防火墙", "网络设备", "switch", "router", "firewall"],
    "database": ["database", "数据库"],
    "mysql": ["mysql", "my sql"],
    "PostgreSQL": ["postgresql", "postgres", "pgsql"],
    "redis": ["redis"],
    "Kafka": ["kafka"],
    "elasticsearch": ["elasticsearch", "es"],
    "nginx": ["nginx"],
    "apache": ["apache"],
    "docker": ["docker"],
    "kubernetes": ["kubernetes", "k8s"],
    "dcim_idc": ["dcim_idc", "数据中心", "idc", "机房"],
    "dcim_server_room": ["dcim_server_room", "机房分区", "机房区域"],
    "dcim_rack": ["dcim_rack", "机柜", "rack"],
    "ipam_subnet": ["ipam_subnet", "子网", "网段", "cidr"],
    "ipam_address": ["ipam_address", "ip地址", "ip"],
}

STATUS_ALIASES = {
    "运行中": "在线",
    "正常": "在线",
    "在线": "在线",
    "active": "在线",
    "up": "在线",
    "已在cmdb": "已纳管",
    "已关联采集": "已纳管",
    "已接入": "已纳管",
    "y": "已纳管",
    "是": "已纳管",
    "已纳管": "已纳管",
    "已纳观": "已纳管",
    "未监控": "未监控",
    "pending": "未监控",
    "未接管": "未监控",
    "待纳管": "未监控",
    "n": "未监控",
    "否": "未监控",
    "offline": "离线",
    "关机": "离线",
    "停机": "离线",
    "离线": "离线",
    "down": "离线",
}

RESOURCE_DEPLOY_TYPES = {"PhysicalMachine", "vserver", "docker", "kubernetes"}
RESOURCE_CONTAIN_TYPES = {
    "networkdevice",
    "database",
    "mysql",
    "PostgreSQL",
    "redis",
    "Kafka",
    "elasticsearch",
    "nginx",
    "apache",
}
SOFTWARE_RESOURCE_TYPES = {
    "database",
    "mysql",
    "PostgreSQL",
    "redis",
    "Kafka",
    "elasticsearch",
    "nginx",
    "apache",
    "docker",
    "kubernetes",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
PRIMARY_RESOURCE_FIELDS = {
    "asset_code",
    "name",
    "private_ip",
    "ci_type",
    "deploy_target",
    "host_name",
    "upstream_resource",
}
RESOURCE_VALUE_FIELDS = PRIMARY_RESOURCE_FIELDS | {
    "status",
    "vendor",
    "model",
    "version",
    "service_port",
    "monitor_status",
    "project",
    "department",
    "environment",
    "description",
}
EXCLUDED_SHEET_KEYWORDS = ("测试", "说明", "readme", "示例", "样例")
RELATION_SHEET_KEYWORDS = ("relation", "relations", "关系", "拓扑", "链路", "依赖", "mapping")
RESOURCE_IMPORT_LLM_STEP_TIMEOUT_SECONDS = float(
    os.environ.get("RESOURCE_IMPORT_LLM_STEP_TIMEOUT", "180"),
)
RESOURCE_IMPORT_LLM_STEP_TIMEOUT_MAX_SECONDS = float(
    os.environ.get("RESOURCE_IMPORT_LLM_STEP_TIMEOUT_MAX", "600"),
)
RESOURCE_IMPORT_PRECHECK_LIMIT = int(
    os.environ.get("RESOURCE_IMPORT_PRECHECK_LIMIT", "12"),
)

ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass
class ParsedFile:
    filename: str
    extension: str
    rows: list[dict[str, Any]]
    warnings: list[str]
    logs: list[str]


@dataclass
class SheetMappingPlan:
    sheet_kind: str
    default_ci_type: str
    mappings: dict[str, tuple[str, str]]
    reason: str = ""


@dataclass
class ResourceImportRuntime:
    client: Any | None
    source: str


def _emit_progress(
    progress_callback: ProgressCallback | None,
    *,
    stage: str,
    message: str,
    percent: int | None = None,
) -> None:
    if not progress_callback:
        return
    payload: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "message": message,
    }
    if percent is not None:
        payload["percent"] = max(0, min(100, int(percent)))
    progress_callback(payload)


def _should_retry_llm_mapping(exc: Exception) -> bool:
    text = _clean_text(exc).lower()
    if not text:
        return False
    return any(
        token in text
        for token in (
            "too_many_requests",
            "rate limit",
            "429",
            "connection",
            "connect",
            "temporarily unavailable",
            "service unavailable",
            "network",
            "reset by peer",
        )
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _default_env_file() -> Path:
    return Path.cwd() / ".env"


def _normalize_token(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("（", "(").replace("）", ")")
    return re.sub(r"[\s_\-()/\\:：]+", "", text)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _normalize_header(header: str) -> str:
    text = _clean_text(header).lower()
    text = text.replace("（", "(").replace("）", ")")
    return re.sub(r"[\s_\-()/\\:：]+", "", text)


def _parse_env() -> dict[str, str]:
    selected_path = Path(os.environ.get("VEOPS_ENV_FILE", str(_default_env_file())))
    values = {
        key: str(value)
        for key, value in dotenv_values(selected_path).items()
        if value is not None
    }
    if not values:
        raise RuntimeError(f"未找到可用的 CMDB 环境文件：{selected_path}")
    return values


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text


def _parse_json_loose(text: str) -> Any:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise RuntimeError("LLM 返回为空")

    fenced_match = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", cleaned, flags=re.IGNORECASE)
    if fenced_match:
        cleaned = fenced_match.group(1).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    first_object = cleaned.find("{")
    last_object = cleaned.rfind("}")
    if first_object != -1 and last_object > first_object:
        candidate = cleaned[first_object:last_object + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    first_array = cleaned.find("[")
    last_array = cleaned.rfind("]")
    if first_array != -1 and last_array > first_array:
        candidate = cleaned[first_array:last_array + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    raise RuntimeError(f"LLM 返回不是合法 JSON: {cleaned}")


class VeopsCmdbClient:
    def __init__(self, base_url: str, username: str, password: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.client = httpx.Client(
            timeout=timeout,
            headers={"Accept-Language": "zh"},
        )
        self.relation_type_map: dict[str, int] = {}

    @classmethod
    def from_skill_env(cls) -> "VeopsCmdbClient":
        env = _parse_env()
        return cls(
            base_url=env["VEOPS_BASE_URL"],
            username=env["VEOPS_USERNAME"],
            password=env["VEOPS_PASSWORD"],
        )

    def login(self) -> None:
        response = self.client.post(
            f"{self.base_url}/api/v1/acl/login",
            json={"username": self.username, "password": self.password},
        )
        payload = _safe_json(response)
        if response.status_code >= 400:
            raise RuntimeError(f"CMDB 登录失败: {payload}")
        token = payload.get("token") if isinstance(payload, dict) else None
        if not token:
            raise RuntimeError("CMDB 登录响应缺少 token")
        self.client.headers["Access-Token"] = str(token)

    def close(self) -> None:
        self.client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_payload: Any = None,
    ) -> Any:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        response = self.client.request(method, url, params=params, json=json_payload)
        payload = _safe_json(response)
        if response.status_code >= 400:
            raise RuntimeError(f"{method.upper()} {path} 失败: {payload}")
        return payload

    def get_ci_types(self) -> list[dict[str, Any]]:
        payload = self.request("GET", "/api/v0.1/ci_types", params={"per_page": 200})
        return payload.get("ci_types", []) if isinstance(payload, dict) else []

    def get_ci_type_groups(self) -> list[dict[str, Any]]:
        payload = self.request("GET", "/api/v0.1/ci_types/groups", params={"need_other": True})
        if isinstance(payload, list):
            return payload
        return payload.get("groups", payload.get("result", [])) or []

    def create_ci_type_group(self, name: str) -> Any:
        return self.request(
            "POST",
            "/api/v0.1/ci_types/groups",
            json_payload={"name": name},
        )

    def update_ci_type_group(self, group_id: int | str, *, name: str, type_ids: list[int]) -> Any:
        return self.request(
            "PUT",
            f"/api/v0.1/ci_types/groups/{group_id}",
            json_payload={
                "name": name,
                "type_ids": type_ids,
            },
        )

    def create_ci_type(
        self,
        *,
        name: str,
        alias: str,
        unique_key: int | str,
        parent_ids: list[int] | None = None,
        icon: str = "",
    ) -> tuple[Any, Any]:
        payload = {
            "name": name,
            "alias": alias or name,
            "unique_key": unique_key,
        }
        if parent_ids:
            payload["parent_ids"] = parent_ids
        if icon is not None:
            payload["icon"] = icon
        response = self.request(
            "POST",
            "/api/v0.1/ci_types",
            json_payload=payload,
        )
        type_id = None
        if isinstance(response, dict):
            type_id = response.get("type_id") or response.get("id")
            if type_id is None and isinstance(response.get("result"), dict):
                type_id = response["result"].get("type_id") or response["result"].get("id")
        return type_id, response

    def create_ci_type_inheritance(self, parent_ids: list[int], child_id: int | str) -> Any:
        return self.request(
            "POST",
            "/api/v0.1/ci_types/inheritance",
            json_payload={
                "parent_ids": parent_ids,
                "child_id": child_id,
            },
        )

    def get_relation_types(self) -> list[dict[str, Any]]:
        payload = self.request("GET", "/api/v0.1/relation_types")
        relation_types = payload if isinstance(payload, list) else payload.get("result", payload)
        results = relation_types if isinstance(relation_types, list) else []
        self.relation_type_map = {
            str(item.get("name")): int(item.get("id"))
            for item in results
            if item.get("name") and item.get("id") is not None
        }
        return results

    def get_ci_type_attributes(self, type_id: int | str) -> list[dict[str, Any]]:
        payload = self.request("GET", f"/api/v0.1/ci_types/{type_id}/attributes")
        if isinstance(payload, list):
            return payload
        return payload.get("attributes", payload.get("result", [])) or []

    def get_ci_type_preference_attributes(self, type_id: int | str) -> list[dict[str, Any]]:
        payload = self.request("GET", f"/api/v0.1/preference/ci_types/{type_id}/attributes")
        if isinstance(payload, list):
            return payload
        return payload.get("attributes", payload.get("result", [])) or []

    def get_attribute_library(self, *, page_size: int = 500, page: int = 1) -> list[dict[str, Any]]:
        payload = self.request(
            "GET",
            "/api/v0.1/attributes/s",
            params={"page_size": page_size, "page": page},
        )
        if isinstance(payload, list):
            return payload
        return payload.get("attributes", payload.get("result", [])) or []

    def get_ci_type_parent_relations(self, type_id: int | str) -> list[dict[str, Any]]:
        payload = self.request("GET", f"/api/v0.1/ci_type_relations/{type_id}/parents")
        if isinstance(payload, list):
            return payload
        return payload.get("parents", payload.get("result", [])) or []

    def get_ci_type_relations(self, type_id: int | str) -> list[dict[str, Any]]:
        payload = self.request("GET", "/api/v0.1/ci_type_relations", params={"ci_type_id": type_id})
        if isinstance(payload, list):
            return payload
        return payload.get("relations", payload.get("result", [])) or []

    def create_ci_type_relation(
        self,
        parent_type_id: int | str,
        child_type_id: int | str,
        *,
        relation_type_id: int | str,
        constraint: str = "0",
        parent_attr_ids: list[int | str] | None = None,
        child_attr_ids: list[int | str] | None = None,
    ) -> tuple[Any, Any]:
        payload: dict[str, Any] = {
            "relation_type_id": relation_type_id,
        }
        if constraint != "":
            payload["constraint"] = str(constraint)
        if parent_attr_ids is not None:
            payload["parent_attr_ids"] = parent_attr_ids
        if child_attr_ids is not None:
            payload["child_attr_ids"] = child_attr_ids
        response = self.request(
            "POST",
            f"/api/v0.1/ci_type_relations/{parent_type_id}/{child_type_id}",
            json_payload=payload,
        )
        relation_id = None
        if isinstance(response, dict):
            relation_id = response.get("ctr_id") or response.get("id")
            if relation_id is None and isinstance(response.get("result"), dict):
                relation_id = response["result"].get("ctr_id") or response["result"].get("id")
        return relation_id, response

    def query_ci(self, query: str, *, count: int = 5) -> list[dict[str, Any]]:
        payload = self.request("GET", "/api/v0.1/ci/s", params={"q": query, "count": count})
        if isinstance(payload, list):
            return payload
        for key in ("result", "items", "cis", "rows"):
            if isinstance(payload.get(key), list):
                return payload[key]
        if isinstance(payload.get("data"), list):
            return payload["data"]
        return []

    def create_ci(
        self,
        ci_type: str,
        attributes: dict[str, Any],
        *,
        exist_policy: str = "reject",
        unique_key: str = "",
    ) -> tuple[Any, Any]:
        payload = {
            "ci_type": ci_type,
            "no_attribute_policy": "ignore",
            "exist_policy": exist_policy,
            **attributes,
        }
        response = self.request("POST", "/api/v0.1/ci", json_payload=payload)
        ci_id = _extract_ci_id(response)
        if ci_id is None:
            ci_id = self.lookup_ci_id(ci_type, attributes, unique_key=unique_key)
        return ci_id, response

    def update_ci(self, ci_id: Any, ci_type: str, attributes: dict[str, Any]) -> tuple[Any, Any]:
        payload = {
            "ci_type": ci_type,
            "no_attribute_policy": "ignore",
            **attributes,
        }
        response = self.request("PUT", f"/api/v0.1/ci/{ci_id}", json_payload=payload)
        updated_ci_id = _extract_ci_id(response) or ci_id
        return updated_ci_id, response

    def delete_ci(self, ci_id: Any) -> Any:
        return self.request("DELETE", f"/api/v0.1/ci/{ci_id}")

    def get_ci_by_id(self, ci_id: Any) -> dict[str, Any] | None:
        items = self.query_ci(f"id:{ci_id}", count=1)
        if items:
            return items[0]
        return None

    def lookup_ci_id(self, ci_type: str, attributes: dict[str, Any], *, unique_key: str = "") -> Any:
        filters = [f"_type:{ci_type}"]
        for key in [unique_key, "asset_code", "private_ip", "name"]:
            key = _clean_text(key)
            if not key:
                continue
            value = _clean_text(attributes.get(key))
            if value:
                filters.append(f"{key}:{quote(value, safe='._-:/')}")
                break
        items = self.query_ci(",".join(filters), count=1)
        if items:
            return _extract_ci_id(items[0])
        return None

    def create_relation(self, src_ci_id: Any, dst_ci_id: Any, relation_type: str) -> tuple[Any, Any]:
        response = self.request("POST", f"/api/v0.1/ci_relations/{src_ci_id}/{dst_ci_id}")
        return _extract_ci_relation_id(response), response

    def delete_relation(self, relation_id: Any) -> Any:
        return self.request("DELETE", f"/api/v0.1/ci_relations/{relation_id}")


class ResourceImportLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        vision_model: str | None = None,
        timeout: float = 300.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.vision_model = vision_model or model
        self.timeout = timeout
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
                "Content-Type": "application/json",
            },
        )

    @classmethod
    def from_env_optional(cls) -> "ResourceImportLLMClient | None":
        try:
            env = _parse_env()
        except Exception:
            return None
        base_url = str(env.get("RESOURCE_IMPORT_LLM_BASE_URL") or "").strip()
        api_key = str(env.get("RESOURCE_IMPORT_LLM_API_KEY") or "").strip()
        model = str(env.get("RESOURCE_IMPORT_LLM_MODEL") or "").strip()
        vision_model = str(env.get("RESOURCE_IMPORT_LLM_VISION_MODEL") or "").strip()
        timeout = float(env.get("RESOURCE_IMPORT_LLM_TIMEOUT") or 300.0)
        if not base_url or not api_key or not model:
            return None
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            vision_model=vision_model or None,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    def _extract_text(self, payload: Any) -> str:
        if isinstance(payload, dict):
            if isinstance(payload.get("choices"), list) and payload["choices"]:
                message = payload["choices"][0].get("message") or {}
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    text_parts = []
                    for item in content:
                        if item.get("type") == "text":
                            text_parts.append(str(item.get("text") or ""))
                    return "\n".join(text_parts).strip()
            if isinstance(payload.get("output"), list):
                fragments: list[str] = []
                for item in payload["output"]:
                    for content in item.get("content", []) or []:
                        if content.get("type") == "output_text":
                            fragments.append(str(content.get("text") or ""))
                if fragments:
                    return "\n".join(fragments).strip()
        return str(payload)

    async def _request_json(self, *, model: str, messages: list[dict[str, Any]]) -> Any:
        response = await self.client.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": messages,
            },
        )
        payload = _safe_json(response)
        if response.status_code >= 400:
            raise RuntimeError(f"LLM 请求失败: {payload}")
        text = self._extract_text(payload).strip()
        return _parse_json_loose(text)

    async def map_sheet_headers(
        self,
        *,
        sheet_name: str,
        headers: list[str],
        sample_rows: list[dict[str, Any]],
        ci_types: list[str],
    ) -> SheetMappingPlan:
        prompt = {
            "sheet_name": sheet_name,
            "headers": headers,
            "sample_rows": sample_rows,
            "available_fields": sorted({*FIELD_ALIASES.keys(), *RELATION_FIELD_ALIASES.keys()}),
            "available_ci_types": ci_types,
            "rules": [
                "只做字段语义匹配，不要臆造字段。",
                "如果这个 sheet 明显不是资产/配置清单，而是说明、备注、测试点，sheet_kind 返回 note。",
                "如果这个 sheet 明显是在描述资源之间的关系、上下游、父子依赖、关系映射，sheet_kind 返回 relation。",
                "如果字段无法确定，target 填 unknown。",
                "default_ci_type 仅在 sheet 整体语义明确时填写，否则留空。",
            ],
            "output_schema": {
                "sheet_kind": "asset|relation|note|unknown",
                "default_ci_type": "string",
                "reason": "string",
                "mappings": [{"source": "string", "target": "string", "confidence": "high|medium|low"}],
            },
        }
        result = await self._request_json(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "你是 CMDB 资源导入映射助手。你的任务是把客户原始字段映射到标准字段，只能依据表头、sheet 名称和样例值判断，不能补造不存在的信息。",
                },
                {
                    "role": "user",
                    "content": json.dumps(prompt, ensure_ascii=False),
                },
            ],
        )
        mappings: dict[str, tuple[str, str]] = {}
        for item in result.get("mappings", []) or []:
            source = _clean_text(item.get("source"))
            target = _clean_text(item.get("target")) or "unknown"
            confidence = _clean_text(item.get("confidence")) or "low"
            if source:
                mappings[source] = (target, confidence)
        return SheetMappingPlan(
            sheet_kind=_clean_text(result.get("sheet_kind")) or "unknown",
            default_ci_type=_clean_text(result.get("default_ci_type")),
            mappings=mappings,
            reason=_clean_text(result.get("reason")),
        )

    async def extract_rows_from_image(self, *, filename: str, content: bytes) -> list[dict[str, Any]]:
        encoded = base64.b64encode(content).decode("ascii")
        suffix = Path(filename).suffix.lower().lstrip(".") or "png"
        prompt = {
            "task": "从图片中的资源清单或表格中提取结构化记录。",
            "rules": [
                "只提取图片中明确可见的信息。",
                "每一行记录保留原始字段名，不要映射成标准字段。",
                "如果图片不是资产清单而只是说明文字，返回 rows=[]。",
            ],
            "output_schema": {
                "rows": [{"原始字段名": "字段值"}],
            },
        }
        result = await self._request_json(
            model=self.vision_model,
            messages=[
                {
                    "role": "system",
                    "content": "你是图片资产清单提取助手，只能抽取可见内容，不能推测缺失信息。",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": json.dumps(prompt, ensure_ascii=False)},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/{suffix};base64,{encoded}"},
                        },
                    ],
                },
            ],
        )
        rows = result.get("rows")
        if not isinstance(rows, list):
            return []
        return [item for item in rows if isinstance(item, dict)]


def _extract_response_text(payload: Any) -> str:
    if hasattr(payload, "text") and isinstance(getattr(payload, "text"), str):
        return str(getattr(payload, "text") or "").strip()

    content = getattr(payload, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        fragments: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    fragments.append(str(item.get("text")))
                elif item.get("type") == "output_text" and item.get("text"):
                    fragments.append(str(item.get("text")))
            elif hasattr(item, "text") and getattr(item, "text"):
                fragments.append(str(getattr(item, "text")))
        return "\n".join(fragment.strip() for fragment in fragments if fragment).strip()

    if isinstance(payload, str):
        return payload.strip()

    return str(payload).strip()


async def _consume_model_response(response: Any) -> str:
    if hasattr(response, "__aiter__"):
        accumulated = ""
        async for chunk in response:
            current = _extract_response_text(chunk)
            if not current:
                continue
            if current.startswith(accumulated):
                accumulated = current
            else:
                accumulated += current
        return accumulated.strip()
    return _extract_response_text(response)


class AnthropicResourceImportLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        vision_model: str | None = None,
        timeout: float = 300.0,
    ) -> None:
        import anthropic

        self.model = model
        self.vision_model = vision_model or model
        self.timeout = timeout
        self.client = anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=base_url or None,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        return None

    async def _request_json(self, *, model: str, content: list[dict[str, Any]]) -> Any:
        response = await self.client.messages.create(
            model=model,
            max_tokens=1800,
            messages=[{"role": "user", "content": content}],
        )
        text = _extract_response_text(response)
        return _parse_json_loose(text)

    async def map_sheet_headers(
        self,
        *,
        sheet_name: str,
        headers: list[str],
        sample_rows: list[dict[str, Any]],
        ci_types: list[str],
    ) -> SheetMappingPlan:
        prompt = {
            "sheet_name": sheet_name,
            "headers": headers,
            "sample_rows": sample_rows,
            "available_fields": sorted({*FIELD_ALIASES.keys(), *RELATION_FIELD_ALIASES.keys()}),
            "available_ci_types": ci_types,
            "rules": [
                "只做字段语义匹配，不要臆造字段。",
                "如果这个 sheet 明显不是资产/配置清单，而是说明、备注、测试点，sheet_kind 返回 note。",
                "如果这个 sheet 明显是在描述资源之间的关系、上下游、父子依赖、关系映射，sheet_kind 返回 relation。",
                "如果字段无法确定，target 填 unknown。",
                "default_ci_type 仅在 sheet 整体语义明确时填写，否则留空。",
                "输出必须是 JSON。",
            ],
            "output_schema": {
                "sheet_kind": "asset|relation|note|unknown",
                "default_ci_type": "string",
                "reason": "string",
                "mappings": [{"source": "string", "target": "string", "confidence": "high|medium|low"}],
            },
        }
        result = await self._request_json(
            model=self.model,
            content=[
                {
                    "type": "text",
                    "text": (
                        "你是 CMDB 资源导入映射助手。"
                        "只能依据表头、sheet 名称和样例值判断，不能补造不存在的信息。"
                        "请直接输出 JSON。"
                    ),
                },
                {"type": "text", "text": json.dumps(prompt, ensure_ascii=False)},
            ],
        )
        mappings: dict[str, tuple[str, str]] = {}
        for item in result.get("mappings", []) or []:
            source = _clean_text(item.get("source"))
            target = _clean_text(item.get("target")) or "unknown"
            confidence = _clean_text(item.get("confidence")) or "low"
            if source:
                mappings[source] = (target, confidence)
        return SheetMappingPlan(
            sheet_kind=_clean_text(result.get("sheet_kind")) or "unknown",
            default_ci_type=_clean_text(result.get("default_ci_type")),
            mappings=mappings,
            reason=_clean_text(result.get("reason")),
        )

    async def extract_rows_from_image(self, *, filename: str, content: bytes) -> list[dict[str, Any]]:
        encoded = base64.b64encode(content).decode("ascii")
        suffix = Path(filename).suffix.lower()
        media_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }.get(suffix, "image/png")
        prompt = {
            "task": "从图片中的资源清单或表格中提取结构化记录。",
            "rules": [
                "只提取图片中明确可见的信息。",
                "每一行记录保留原始字段名，不要映射成标准字段。",
                "如果图片不是资产清单而只是说明文字，返回 rows=[]。",
                "输出必须是 JSON。",
            ],
            "output_schema": {"rows": [{"原始字段名": "字段值"}]},
        }
        result = await self._request_json(
            model=self.vision_model,
            content=[
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": encoded,
                    },
                },
                {"type": "text", "text": json.dumps(prompt, ensure_ascii=False)},
            ],
        )
        rows = result.get("rows")
        if not isinstance(rows, list):
            return []
        return [item for item in rows if isinstance(item, dict)]


class GeminiResourceImportLLMClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        vision_model: str | None = None,
        timeout: float = 300.0,
    ) -> None:
        from google import genai
        from google.genai import types as genai_types

        self.model = model
        self.vision_model = vision_model or model
        self.timeout = timeout
        self._genai_types = genai_types
        self.client = genai.Client(
            api_key=api_key,
            http_options=genai_types.HttpOptions(timeout=int(timeout * 1000)),
        )

    async def aclose(self) -> None:
        return None

    async def _request_json(self, *, model: str, parts: list[Any]) -> Any:
        response = await self.client.aio.models.generate_content(
            model=model,
            contents=parts,
            config=self._genai_types.GenerateContentConfig(
                max_output_tokens=1800,
                response_mime_type="application/json",
            ),
        )
        text = _extract_response_text(response)
        return _parse_json_loose(text)

    async def map_sheet_headers(
        self,
        *,
        sheet_name: str,
        headers: list[str],
        sample_rows: list[dict[str, Any]],
        ci_types: list[str],
    ) -> SheetMappingPlan:
        prompt = {
            "sheet_name": sheet_name,
            "headers": headers,
            "sample_rows": sample_rows,
            "available_fields": sorted({*FIELD_ALIASES.keys(), *RELATION_FIELD_ALIASES.keys()}),
            "available_ci_types": ci_types,
            "rules": [
                "只做字段语义匹配，不要臆造字段。",
                "如果这个 sheet 明显不是资产/配置清单，而是说明、备注、测试点，sheet_kind 返回 note。",
                "如果这个 sheet 明显是在描述资源之间的关系、上下游、父子依赖、关系映射，sheet_kind 返回 relation。",
                "如果字段无法确定，target 填 unknown。",
                "default_ci_type 仅在 sheet 整体语义明确时填写，否则留空。",
                "输出必须是 JSON。",
            ],
            "output_schema": {
                "sheet_kind": "asset|relation|note|unknown",
                "default_ci_type": "string",
                "reason": "string",
                "mappings": [{"source": "string", "target": "string", "confidence": "high|medium|low"}],
            },
        }
        result = await self._request_json(
            model=self.model,
            parts=[
                self._genai_types.Part(
                    text=(
                        "你是 CMDB 资源导入映射助手。"
                        "只能依据表头、sheet 名称和样例值判断，不能补造不存在的信息。"
                        "请直接输出 JSON。"
                    ),
                ),
                self._genai_types.Part(text=json.dumps(prompt, ensure_ascii=False)),
            ],
        )
        mappings: dict[str, tuple[str, str]] = {}
        for item in result.get("mappings", []) or []:
            source = _clean_text(item.get("source"))
            target = _clean_text(item.get("target")) or "unknown"
            confidence = _clean_text(item.get("confidence")) or "low"
            if source:
                mappings[source] = (target, confidence)
        return SheetMappingPlan(
            sheet_kind=_clean_text(result.get("sheet_kind")) or "unknown",
            default_ci_type=_clean_text(result.get("default_ci_type")),
            mappings=mappings,
            reason=_clean_text(result.get("reason")),
        )

    async def extract_rows_from_image(self, *, filename: str, content: bytes) -> list[dict[str, Any]]:
        suffix = Path(filename).suffix.lower()
        mime_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }.get(suffix, "image/png")
        prompt = {
            "task": "从图片中的资源清单或表格中提取结构化记录。",
            "rules": [
                "只提取图片中明确可见的信息。",
                "每一行记录保留原始字段名，不要映射成标准字段。",
                "如果图片不是资产清单而只是说明文字，返回 rows=[]。",
                "输出必须是 JSON。",
            ],
            "output_schema": {"rows": [{"原始字段名": "字段值"}]},
        }
        result = await self._request_json(
            model=self.vision_model,
            parts=[
                self._genai_types.Part(
                    inline_data=self._genai_types.Blob(
                        mime_type=mime_type,
                        data=content,
                    ),
                ),
                self._genai_types.Part(text=json.dumps(prompt, ensure_ascii=False)),
            ],
        )
        rows = result.get("rows")
        if not isinstance(rows, list):
            return []
        return [item for item in rows if isinstance(item, dict)]


def _build_runtime_client_from_agent(agent_id: str) -> Any | None:
    try:
        from qwenpaw.config.config import load_agent_config
        from qwenpaw.providers.provider_manager import ProviderManager

        manager = ProviderManager.get_instance()
        model_slot = load_agent_config(agent_id).active_model or manager.get_active_model()
        if not model_slot or not model_slot.provider_id or not model_slot.model:
            return None

        provider = manager.get_provider(model_slot.provider_id)
        if not provider:
            return None

        if provider.chat_model == "AnthropicChatModel":
            return AnthropicResourceImportLLMClient(
                base_url=provider.base_url,
                api_key=provider.api_key,
                model=model_slot.model,
            )
        if provider.chat_model == "GeminiChatModel":
            return GeminiResourceImportLLMClient(
                api_key=provider.api_key,
                model=model_slot.model,
            )
        return ResourceImportLLMClient(
            base_url=provider.base_url,
            api_key=provider.api_key,
            model=model_slot.model,
        )
    except Exception:
        return None


async def resolve_resource_import_runtime(agent_id: str | None = None) -> ResourceImportRuntime:
    if agent_id:
        agent_client = _build_runtime_client_from_agent(agent_id)
        if agent_client:
            return ResourceImportRuntime(
                client=agent_client,
                source=f"当前页面模型配置({agent_id})",
            )
    return ResourceImportRuntime(client=None, source="规则映射")


async def resolve_resource_import_llm_client(agent_id: str | None = None) -> Any | None:
    runtime = await resolve_resource_import_runtime(agent_id)
    return runtime.client


def _extract_ci_id(payload: Any) -> Any:
    if isinstance(payload, dict):
        for key in ("id", "ci_id", "_id"):
            value = payload.get(key)
            if value not in (None, ""):
                return value
        for key in ("result", "data", "ci", "item"):
            value = payload.get(key)
            result = _extract_ci_id(value)
            if result not in (None, ""):
                return result
    if isinstance(payload, list):
        for item in payload:
            result = _extract_ci_id(item)
            if result not in (None, ""):
                return result
    return None


def _extract_ci_type_relation_id(payload: Any) -> Any:
    if isinstance(payload, dict):
        for key in ("ctr_id", "id", "relation_id"):
            value = payload.get(key)
            if value not in (None, ""):
                return value
        for key in ("result", "data", "item"):
            value = payload.get(key)
            result = _extract_ci_type_relation_id(value)
            if result not in (None, ""):
                return result
    if isinstance(payload, list):
        for item in payload:
            result = _extract_ci_type_relation_id(item)
            if result not in (None, ""):
                return result
    return None


def _extract_ci_relation_id(payload: Any) -> Any:
    if isinstance(payload, dict):
        for key in ("cr_id", "id", "relation_id"):
            value = payload.get(key)
            if value not in (None, ""):
                return value
        for key in ("result", "data", "item"):
            value = payload.get(key)
            result = _extract_ci_relation_id(value)
            if result not in (None, ""):
                return result
    if isinstance(payload, list):
        for item in payload:
            result = _extract_ci_relation_id(item)
            if result not in (None, ""):
                return result
    return None


def _match_field(header: str) -> tuple[str, str]:
    normalized = _normalize_header(header)
    for target, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if normalized == _normalize_header(alias):
                return target, "high"
    for target, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            alias_token = _normalize_header(alias)
            if alias_token and len(alias_token) >= 5 and (alias_token in normalized or normalized in alias_token):
                return target, "medium"
    return "unknown", "low"


def _match_relation_field(header: str) -> tuple[str, str]:
    normalized = _normalize_header(header)
    for target, aliases in RELATION_FIELD_ALIASES.items():
        for alias in aliases:
            if normalized == _normalize_header(alias):
                return target, "high"
    for target, aliases in RELATION_FIELD_ALIASES.items():
        for alias in aliases:
            alias_token = _normalize_header(alias)
            if alias_token and len(alias_token) >= 3 and (alias_token in normalized or normalized in alias_token):
                return target, "medium"
    return "unknown", "low"


def _sheet_name_hint(sheet_name: str, alias_index: dict[str, str]) -> str:
    normalized = _normalize_ci_type(sheet_name, alias_index)
    return "" if normalized == sheet_name else normalized


def _sample_sheet_rows(rows: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    sampled: list[dict[str, Any]] = []
    if len(rows) <= limit:
        candidate_rows = rows
    else:
        middle_index = max(0, len(rows) // 2)
        tail_count = max(1, limit - 3)
        candidate_rows = [
            *rows[:2],
            rows[middle_index],
            *rows[-tail_count:],
        ]
    seen_rows: set[str] = set()
    for row in candidate_rows:
        fingerprint = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
        if fingerprint in seen_rows:
            continue
        seen_rows.add(fingerprint)
        sampled.append(
            {
                key: _clean_text(value)
                for key, value in row.items()
                if key != "_sheet" and _clean_text(value)
            }
        )
    return sampled


def _sheet_llm_timeout_seconds(*, row_count: int, header_count: int) -> float:
    base_timeout = max(RESOURCE_IMPORT_LLM_STEP_TIMEOUT_SECONDS, 60.0)
    scaled_timeout = base_timeout + max(0.0, header_count - 12) * 6.0 + max(0.0, row_count - 20) * 0.6
    return min(max(base_timeout, scaled_timeout), RESOURCE_IMPORT_LLM_STEP_TIMEOUT_MAX_SECONDS)


def _looks_like_note_sheet(sheet_name: str, headers: list[str]) -> bool:
    normalized_sheet_name = _clean_text(sheet_name)
    if any(token in normalized_sheet_name for token in EXCLUDED_SHEET_KEYWORDS):
        return True
    normalized_headers = {_normalize_header(header) for header in headers}
    note_header_groups = [
        {"测试点", "说明"},
        {"说明", "备注"},
    ]
    for group in note_header_groups:
        if all(_normalize_header(item) in normalized_headers for item in group):
            return True
    return False


def _looks_like_relation_sheet(sheet_name: str, headers: list[str]) -> bool:
    normalized_sheet_name = _clean_text(sheet_name).lower()
    if any(token in normalized_sheet_name for token in RELATION_SHEET_KEYWORDS):
        return True

    matched_fields = {
        _match_relation_field(header)[0]
        for header in headers
        if _match_relation_field(header)[0] != "unknown"
    }
    if {"source_value", "target_value"} <= matched_fields:
        return True
    if {"source_model", "target_model"} <= matched_fields and (
        "relation_type" in matched_fields or "source_value" in matched_fields or "target_value" in matched_fields
    ):
        return True
    return False


def _row_has_relation_signal(fields: dict[str, Any]) -> bool:
    source_value = _clean_text(fields.get("source_value"))
    target_value = _clean_text(fields.get("target_value"))
    if source_value and target_value:
        return True
    return False


def _normalize_relation_type(value: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    normalized = _normalize_token(cleaned)
    for relation_type, aliases in RELATION_TYPE_ALIASES.items():
        if normalized == _normalize_token(relation_type):
            return relation_type
        for alias in aliases:
            if normalized == _normalize_token(alias):
                return relation_type
    return cleaned


async def _resolve_sheet_mapping_plan(
    *,
    sheet_name: str,
    rows: list[dict[str, Any]],
    alias_index: dict[str, str],
    model_templates: list[dict[str, Any]],
    llm_client: Any | None,
) -> tuple[SheetMappingPlan, str]:
    headers = sorted({key for row in rows for key in row.keys() if key != "_sheet"})
    sheet_timeout_seconds = _sheet_llm_timeout_seconds(
        row_count=len(rows),
        header_count=len(headers),
    )
    retry_timeout_seconds = min(
        RESOURCE_IMPORT_LLM_STEP_TIMEOUT_MAX_SECONDS,
        max(sheet_timeout_seconds + 120.0, sheet_timeout_seconds * 1.75),
    )
    default_ci_type = _sheet_name_hint(sheet_name, alias_index)
    heuristic_sheet_kind = (
        "note"
        if _looks_like_note_sheet(sheet_name, headers)
        else "relation"
        if _looks_like_relation_sheet(sheet_name, headers)
        else "asset"
    )
    heuristic_mappings = {
        header: (_match_relation_field(header) if heuristic_sheet_kind == "relation" else _match_field(header))
        for header in headers
    }
    heuristic_plan = SheetMappingPlan(
        sheet_kind=heuristic_sheet_kind,
        default_ci_type=default_ci_type,
        mappings=heuristic_mappings,
        reason="规则映射",
    )

    if not llm_client or heuristic_sheet_kind in {"relation", "note"}:
        return heuristic_plan, "规则映射"

    try:
        llm_plan = None
        last_exception: Exception | None = None
        for attempt in range(2):
            try:
                current_timeout_seconds = sheet_timeout_seconds if attempt == 0 else retry_timeout_seconds
                llm_plan = await asyncio.wait_for(
                    llm_client.map_sheet_headers(
                        sheet_name=sheet_name,
                        headers=headers,
                        sample_rows=_sample_sheet_rows(rows),
                        ci_types=[str(item.get("name") or "") for item in model_templates if item.get("name")],
                    ),
                    timeout=current_timeout_seconds,
                )
                break
            except asyncio.TimeoutError:
                last_exception = asyncio.TimeoutError(
                    f"单个sheet映射超过 {current_timeout_seconds:.0f}s"
                )
                if attempt >= 1:
                    raise
                continue
            except Exception as exc:  # noqa: BLE001
                last_exception = exc
                if attempt >= 1 or not _should_retry_llm_mapping(exc):
                    raise
                await asyncio.sleep(1.0 + attempt)
        if llm_plan is None and last_exception is not None:
            raise last_exception
        merged_mappings: dict[str, tuple[str, str]] = {}
        for header in headers:
            llm_target, llm_confidence = llm_plan.mappings.get(header, ("unknown", "low"))
            if llm_target != "unknown":
                merged_mappings[header] = (llm_target, llm_confidence)
            else:
                merged_mappings[header] = heuristic_mappings.get(header, ("unknown", "low"))
        return SheetMappingPlan(
            sheet_kind=llm_plan.sheet_kind or heuristic_plan.sheet_kind,
            default_ci_type=llm_plan.default_ci_type or heuristic_plan.default_ci_type,
            mappings=merged_mappings,
            reason=llm_plan.reason or "LLM 映射",
        ), "LLM辅助映射"
    except asyncio.TimeoutError:
        return heuristic_plan, (
            "规则映射"
            f"（LLM超时: 单个sheet映射超过 {sheet_timeout_seconds:.0f}s）"
        )
    except Exception as exc:  # noqa: BLE001
        return heuristic_plan, f"规则映射（LLM不可用: {exc}）"


def _build_type_alias_index(model_templates: list[dict[str, Any]]) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for template in model_templates:
        name = str(template.get("name") or "").strip()
        alias = str(template.get("alias") or "").strip()
        if name:
            alias_map[_normalize_token(name)] = name
        if alias:
            alias_map[_normalize_token(alias)] = name
    for ci_type, aliases in CI_TYPE_ALIASES.items():
        alias_map[_normalize_token(ci_type)] = ci_type
        for alias in aliases:
            alias_map[_normalize_token(alias)] = ci_type
    return alias_map


def _normalize_ci_type(value: str, alias_index: dict[str, str]) -> str:
    raw = _clean_text(value)
    if not raw:
        return ""
    direct = alias_index.get(_normalize_token(raw))
    if direct:
        return direct
    lowered = raw.lower()
    if "redis" in lowered:
        return "redis"
    if "mysql" in lowered:
        return "mysql"
    if "postgres" in lowered:
        return "PostgreSQL"
    if "kafka" in lowered:
        return "Kafka"
    if lowered in {"es", "elasticsearch"}:
        return "elasticsearch"
    if "nginx" in lowered:
        return "nginx"
    if "docker" in lowered:
        return "docker"
    if "k8s" in lowered or "kubernetes" in lowered:
        return "kubernetes"
    if any(token in lowered for token in ("switch", "router", "network", "交换机", "交换", "路由", "防火墙", "负载均衡", "loadbalance", "lb")):
        return "networkdevice"
    if any(token in lowered for token in ("vm", "vserver", "虚拟")):
        return "vserver"
    if any(token in lowered for token in ("server", "服务器", "物理机", "baremetal")):
        return "PhysicalMachine"
    return raw


def _normalize_status(value: str) -> str:
    raw = _clean_text(value)
    if not raw:
        return ""
    direct = STATUS_ALIASES.get(raw)
    if direct:
        return direct
    lowered = raw.lower()
    return STATUS_ALIASES.get(lowered, raw)


def _normalize_ip(value: str) -> tuple[str, bool]:
    text = _clean_text(value)
    if not text:
        return "", False
    text = text.replace("；", ";").split(";", 1)[0].strip()
    if "/" in text:
        candidate = text.split("/", 1)[0].strip()
    else:
        candidate = text
    try:
        normalized = str(ip_address(candidate))
        return normalized, normalized != value.strip()
    except ValueError:
        octets = candidate.split(".")
        if len(octets) == 4 and all(part.isdigit() for part in octets):
            try:
                normalized = ".".join(str(int(part, 10)) for part in octets)
                ip_address(normalized)
                return normalized, normalized != value.strip()
            except ValueError:
                pass
        return text, False


def _infer_subnet(explicit_subnet: str, private_ip: str) -> str:
    if explicit_subnet:
        return explicit_subnet
    if not private_ip:
        return ""
    try:
        network = ip_network(f"{private_ip}/24", strict=False)
        return str(network)
    except ValueError:
        return ""


def _normalize_service_port(value: str) -> tuple[str, bool, bool]:
    text = _clean_text(value)
    if not text:
        return "", False, False
    compact = re.sub(r"\s+", "", text)
    if compact.isdigit():
        return compact, compact != text, False
    parts = [part for part in re.split(r"[/,;|]+", compact) if part]
    if len(parts) == 1 and parts[0].isdigit():
        normalized = parts[0]
        return normalized, normalized != text, False
    if len(parts) > 1 and all(part.isdigit() for part in parts):
        return "", True, True
    return text, False, True


def _read_csv_rows(filename: str, content: bytes) -> list[dict[str, Any]]:
    text = content.decode("utf-8-sig", errors="ignore")
    sample = text[:2048]
    dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|") if sample.strip() else csv.excel
    frame = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, sep=dialect.delimiter)
    return frame.fillna("").to_dict(orient="records")


def _read_excel_rows(filename: str, content: bytes) -> list[dict[str, Any]]:
    try:
        suffix = Path(filename).suffix.lower()
        engine = "openpyxl" if suffix in {".xlsx", ".xlsm"} else None
        workbook = pd.read_excel(
            io.BytesIO(content),
            sheet_name=None,
            dtype=str,
            engine=engine,
        )
    except ImportError as exc:
        raise RuntimeError(
            "当前服务运行环境缺少 Excel 解析依赖 openpyxl，"
            "请在启动 QwenPaw 的 Python 环境中安装 `openpyxl` 后重试。"
        ) from exc

    rows: list[dict[str, Any]] = []
    for sheet_name, frame in workbook.items():
        for row in frame.fillna("").to_dict(orient="records"):
            normalized = dict(row)
            normalized["_sheet"] = sheet_name
            rows.append(normalized)
    return rows


def _read_json_rows(content: bytes) -> list[dict[str, Any]]:
    payload = json.loads(content.decode("utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "rows", "data", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def _parse_text_blocks(text: str) -> list[dict[str, Any]]:
    blocks = re.split(r"\n\s*\n", text)
    rows: list[dict[str, Any]] = []
    for block in blocks:
        row: dict[str, Any] = {}
        for line in block.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                row[_clean_text(key)] = _clean_text(value)
            elif "：" in line:
                key, value = line.split("：", 1)
                row[_clean_text(key)] = _clean_text(value)
        if row:
            rows.append(row)
    return rows


def _read_docx_rows(content: bytes) -> list[dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    text = re.sub(r"</w:p>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return _parse_text_blocks(text)


async def _read_image_rows(
    filename: str,
    content: bytes,
    llm_client: Any | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not llm_client:
        return [], ["当前页面所选模型未提供可用的多模态解析能力，图片文件暂时无法自动抽取。"]
    try:
        rows = await llm_client.extract_rows_from_image(filename=filename, content=content)
        return rows, []
    except Exception as exc:  # noqa: BLE001
        return [], [f"{filename} 图片解析失败：{exc}"]


async def parse_uploaded_file(
    filename: str,
    content: bytes,
    *,
    llm_client: Any | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ParsedFile:
    suffix = Path(filename).suffix.lower()
    logs = [f"开始解析文件：{filename}"]
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    _emit_progress(
        progress_callback,
        stage="file_reading",
        message=f"正在读取文件 {filename}",
        percent=8,
    )
    if suffix in {".csv", ".tsv"}:
        rows = _read_csv_rows(filename, content)
    elif suffix in {".xlsx", ".xls"}:
        rows = _read_excel_rows(filename, content)
    elif suffix == ".json":
        rows = _read_json_rows(content)
    elif suffix in {".txt", ".md"}:
        rows = _parse_text_blocks(content.decode("utf-8", errors="ignore"))
    elif suffix == ".docx":
        rows = _read_docx_rows(content)
    elif suffix in IMAGE_SUFFIXES:
        rows, image_warnings = await _read_image_rows(filename, content, llm_client=llm_client)
        warnings.extend(image_warnings)
    else:
        warnings.append(f"{filename} 暂不支持自动解析，将保留为待扩展格式。")
    logs.append(f"读取到 {len(rows)} 条原始行（含说明页/非资产行，后续步骤会继续筛除）")
    _emit_progress(
        progress_callback,
        stage="file_reading",
        message=f"{filename} 读取完成，共识别到 {len(rows)} 条原始行",
        percent=16,
    )
    return ParsedFile(
        filename=filename,
        extension=suffix,
        rows=rows,
        warnings=warnings,
        logs=logs,
    )


def _resource_key(ci_type: str, name: str, private_ip: str) -> str:
    anchor = private_ip or name
    return f"{ci_type}::{anchor}".lower()


def _ensure_node(
    nodes: dict[str, dict[str, Any]],
    *,
    ci_type: str,
    name: str,
    category: str,
    generated: bool,
    attributes: dict[str, Any] | None = None,
    source_rows: list[dict[str, Any]] | None = None,
) -> str | None:
    name = _clean_text(name)
    if not name:
        return None
    key = _resource_key(ci_type, name, "")
    existing = nodes.get(key)
    payload = {
        "previewKey": key,
        "ciType": ci_type,
        "name": name,
        "category": category,
        "generated": generated,
        "attributes": attributes or {"name": name},
        "sourceRows": source_rows or [],
        "selected": True,
    }
    if existing:
        existing["sourceRows"] = [*existing.get("sourceRows", []), *(payload["sourceRows"] or [])]
        return key
    nodes[key] = payload
    return key


def _append_relation(
    relations: dict[tuple[str, str, str], dict[str, Any]],
    *,
    source_key: str | None,
    target_key: str | None,
    relation_type: str,
    confidence: str,
    reason: str,
) -> None:
    if not source_key or not target_key or source_key == target_key:
        return
    key = (source_key, target_key, relation_type)
    if key in relations:
        return
    relations[key] = {
        "sourceKey": source_key,
        "targetKey": target_key,
        "relationType": relation_type,
        "confidence": confidence,
        "reason": reason,
        "selected": True,
    }


def _build_preview_key(parsed_file: ParsedFile, sheet_name: str, row_index: int) -> str:
    return f"row::{parsed_file.filename}::{sheet_name or 'Sheet1'}::{row_index}"


def _row_has_resource_signal(fields: dict[str, Any]) -> bool:
    value_fields = [key for key in RESOURCE_VALUE_FIELDS if _clean_text(fields.get(key))]
    if not value_fields:
        return False
    if any(key in PRIMARY_RESOURCE_FIELDS for key in value_fields):
        return True
    return len(value_fields) >= 3


def _collect_confirmation_issues(ci_type: str, attributes: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if not _clean_text(attributes.get("name")):
        issues.append("名称")
    if ci_type in {"PhysicalMachine", "vserver", "networkdevice"} and not _clean_text(attributes.get("private_ip")):
        issues.append("IP")
    if ci_type == "networkdevice" and not _clean_text(attributes.get("model")):
        issues.append("型号")
    if ci_type in SOFTWARE_RESOURCE_TYPES and not _clean_text(attributes.get("version")):
        issues.append("版本")
    if ci_type in SOFTWARE_RESOURCE_TYPES and not _clean_text(attributes.get("service_port")):
        issues.append("端口")
    if ci_type in SOFTWARE_RESOURCE_TYPES and not _clean_text(attributes.get("deploy_target")):
        issues.append("部署节点")
    return issues


def _find_existing_ci(
    client: VeopsCmdbClient | None,
    ci_type: str,
    attributes: dict[str, Any],
    *,
    fallback_name: str = "",
    unique_key: str = "",
) -> dict[str, Any] | None:
    if client is None or not ci_type or ci_type == "unknown":
        return None

    candidates: list[tuple[str, str]] = []
    for field in [unique_key, "asset_code", "private_ip", "name"]:
        field = _clean_text(field)
        if not field:
            continue
        value = _clean_text(attributes.get(field))
        if value and all(existing_field != field for existing_field, _ in candidates):
            candidates.append((field, value))
    if fallback_name and all(name != "name" for name, _ in candidates):
        candidates.append(("name", fallback_name))

    for field, value in candidates:
        try:
            items = client.query_ci(
                f"_type:{ci_type},{field}:{quote(value, safe='._-:/')}",
                count=1,
            )
        except Exception:
            continue
        if not items:
            continue
        item = items[0]
        ci_id = _extract_ci_id(item)
        if ci_id in (None, ""):
            continue
        return {
            "ciId": ci_id,
            "matchField": field,
            "matchValue": value,
            "name": _clean_text(
                item.get("name")
                or item.get("ci_name")
                or item.get("label")
                or item.get("title")
            ),
            "status": _clean_text(item.get("status") or item.get("state")),
        }
    return None


def _extract_type_id(payload: Any) -> int | None:
    if payload is None:
        return None
    if isinstance(payload, bool):
        return None
    if isinstance(payload, int):
        return payload
    text = _clean_text(payload)
    if text.isdigit():
        return int(text)
    return None


def _resolve_attribute_id_from_metadata(
    metadata: dict[str, Any],
    attribute_name: str,
    *,
    preferred_ci_type: str = "",
) -> int | None:
    direct_id = _extract_type_id(attribute_name)
    if direct_id is not None:
        return direct_id

    target_name = _clean_text(attribute_name)
    if not target_name:
        return None

    def _find_definition_id(
        definitions: list[dict[str, Any]],
        names: list[str],
    ) -> int | None:
        exact_names = [_clean_text(item) for item in names if _clean_text(item)]
        if not exact_names:
            return None

        for candidate_name in exact_names:
            normalized_candidate = _normalize_token(candidate_name)
            for definition in definitions:
                if not isinstance(definition, dict):
                    continue
                attribute_id = _extract_type_id(definition.get("id"))
                if attribute_id is None:
                    continue
                definition_name = _clean_text(definition.get("name"))
                definition_alias = _clean_text(definition.get("alias"))
                if definition_name == candidate_name or definition_alias == candidate_name:
                    return attribute_id
                if normalized_candidate and (
                    _normalize_token(definition_name) == normalized_candidate
                    or _normalize_token(definition_alias) == normalized_candidate
                ):
                    return attribute_id
        return None

    ci_types = [
        item
        for item in (metadata.get("ciTypes") or [])
        if isinstance(item, dict)
    ]
    preferred_type = next(
        (item for item in ci_types if _clean_text(item.get("name")) == _clean_text(preferred_ci_type)),
        None,
    )
    preferred_definitions = list((preferred_type or {}).get("attributeDefinitions") or [])
    all_definitions = [
        definition
        for ci_type in ci_types
        for definition in (ci_type.get("attributeDefinitions") or [])
        if isinstance(definition, dict)
    ]

    direct_match = _find_definition_id(preferred_definitions, [target_name]) or _find_definition_id(
        all_definitions,
        [target_name],
    )
    if direct_match is not None:
        return direct_match

    canonical_field, _confidence = _match_field(target_name)
    canonical_names: list[str] = [target_name]
    if canonical_field != "unknown":
        canonical_names.append(canonical_field)
        canonical_names.extend(FIELD_ALIASES.get(canonical_field, []))
        canonical_names.extend(SPECIAL_ATTRIBUTE_NAME_CANDIDATES.get(canonical_field, []))

    if preferred_type and canonical_field != "unknown":
        resolved_name = _resolve_cmdb_attribute_name(preferred_type, canonical_field)
        if resolved_name:
            canonical_names.insert(0, resolved_name)

    mapped_match = _find_definition_id(preferred_definitions, canonical_names) or _find_definition_id(
        all_definitions,
        canonical_names,
    )
    if mapped_match is not None:
        return mapped_match

    attribute_library = [
        item
        for item in (metadata.get("attributeLibrary") or [])
        if isinstance(item, dict)
    ]
    library_match = _find_definition_id(attribute_library, canonical_names)
    if library_match is not None:
        return library_match

    return None


def _build_ci_type_state(
    ci_types: list[dict[str, Any]],
    ci_type_groups: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    type_map = {
        _clean_text(item.get("name")): item
        for item in ci_types
        if isinstance(item, dict) and _clean_text(item.get("name"))
    }
    group_map = {
        _clean_text(group.get("name")): group
        for group in (
            _normalize_group_snapshot(item)
            for item in ci_type_groups
            if isinstance(item, dict)
        )
        if _clean_text(group.get("name"))
    }
    return type_map, group_map


def _refresh_ci_type_state(
    client: VeopsCmdbClient,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    return _build_ci_type_state(client.get_ci_types(), client.get_ci_type_groups())


def _attach_model_to_group(
    client: VeopsCmdbClient,
    *,
    group: dict[str, Any],
    group_name: str,
    model_id: int,
) -> bool:
    group_id = _extract_type_id(group.get("id"))
    if group_id is None:
        raise RuntimeError(f"分组 {group_name} 缺少可用 id，无法挂接模型")

    type_ids = {
        ci_type_id
        for ci_type_id in (
            _extract_type_id(item.get("id"))
            for item in (group.get("ciTypes") or [])
            if isinstance(item, dict)
        )
        if ci_type_id is not None
    }
    if model_id in type_ids:
        return False
    type_ids.add(model_id)
    client.update_ci_type_group(group_id, name=group_name, type_ids=sorted(type_ids))
    return True


def _prepare_import_structure(
    client: VeopsCmdbClient,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    preview = payload.get("preview") or {}
    structure_analysis = preview.get("structureAnalysis") or {}
    items = structure_analysis.get("items") or []
    if not isinstance(items, list):
        return []

    metadata = load_resource_import_metadata()
    type_map, group_map = _refresh_ci_type_state(client)
    results: list[dict[str, Any]] = []

    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        resource_label = _clean_text(raw_item.get("resourceLabel")) or _clean_text(raw_item.get("resourceCiType")) or "待确认资源"
        group_name = _clean_text(raw_item.get("selectedGroupName")) or _clean_text(raw_item.get("suggestedGroupName"))
        model_name = _clean_text(raw_item.get("selectedModelName")) or _clean_text(raw_item.get("resourceCiType"))
        model_draft = raw_item.get("modelDraft") or {}
        model_alias = _clean_text(model_draft.get("alias")) or model_name
        unique_key_name = _clean_text(model_draft.get("uniqueKey"))
        inherit_from = _clean_text(model_draft.get("inheritFrom"))
        group = group_map.get(group_name) if group_name else None
        group_missing = bool(group_name) and group is None
        if group_missing:
            if not raw_item.get("createGroupApproved"):
                raise RuntimeError(f"{resource_label} 尚未确认创建分组，当前不能继续导入")
            client.create_ci_type_group(group_name)
            _type_map, group_map = _refresh_ci_type_state(client)
            type_map.update(_type_map)
            group = group_map.get(group_name)
            if group is None:
                raise RuntimeError(f"分组 {group_name} 创建后未能在 CMDB 中查询到")
            results.append(
                {
                    "kind": "group",
                    "name": group_name,
                    "status": "created",
                    "message": f"已创建分组 {group_name}",
                }
            )

        if not model_name:
            if group_missing or raw_item.get("createModelApproved"):
                raise RuntimeError(f"{resource_label} 缺少目标模型名称，当前不能继续导入")
            continue

        model = type_map.get(model_name)
        model_missing = model is None
        if model_missing:
            if not raw_item.get("createModelApproved"):
                raise RuntimeError(f"{resource_label} 尚未确认创建模型，当前不能继续导入")
            if not unique_key_name:
                raise RuntimeError(f"{resource_label} 缺少模型唯一标识配置，当前不能继续导入")

            unique_key_id = _resolve_attribute_id_from_metadata(
                metadata,
                unique_key_name,
                preferred_ci_type=inherit_from or model_name,
            )
            if unique_key_id is None:
                raise RuntimeError(
                    f"{resource_label} 的唯一标识字段 {unique_key_name} 未在 CMDB 属性库中找到，当前不能创建模型"
                )
            parent_ids: list[int] = []
            if inherit_from:
                parent = type_map.get(inherit_from)
                parent_id = _extract_type_id((parent or {}).get("id"))
                if parent_id is None:
                    raise RuntimeError(f"模型 {model_name} 继承失败：未找到父模型 {inherit_from}")
                parent_ids = [parent_id]
            model_id, _response = client.create_ci_type(
                name=model_name,
                alias=model_alias or model_name,
                unique_key=unique_key_id,
                parent_ids=parent_ids,
            )
            _type_map, group_map = _refresh_ci_type_state(client)
            type_map.update(_type_map)
            group = group_map.get(group_name) if group_name else group
            model = type_map.get(model_name)
            resolved_model_id = _extract_type_id(model_id) or _extract_type_id((model or {}).get("id"))
            if model is None or resolved_model_id is None:
                raise RuntimeError(f"模型 {model_name} 创建后未能在 CMDB 中查询到")
            results.append(
                {
                    "kind": "model",
                    "name": model_name,
                    "groupName": group_name,
                    "status": "created",
                    "message": f"已创建模型 {model_name}",
                }
            )

        if group_name:
            model_id = _extract_type_id((model or {}).get("id"))
            if model_id is None:
                raise RuntimeError(f"模型 {model_name} 缺少 id，无法继续导入")
            if group is None:
                raise RuntimeError(f"目标分组 {group_name} 不存在，无法挂接模型 {model_name}")
            attached = _attach_model_to_group(
                client,
                group=group,
                group_name=group_name,
                model_id=model_id,
            )
            if attached:
                _type_map, group_map = _refresh_ci_type_state(client)
                type_map.update(_type_map)
                results.append(
                    {
                        "kind": "group-binding",
                        "name": model_name,
                        "groupName": group_name,
                        "status": "attached",
                        "message": f"已将模型 {model_name} 绑定到分组 {group_name}",
                    }
                )

    return results


def _attribute_definitions(type_template: dict[str, Any] | None) -> list[dict[str, Any]]:
    definitions = (type_template or {}).get("attributeDefinitions") or []
    return [item for item in definitions if isinstance(item, dict) and item.get("name")]


def _find_attribute_definition(type_template: dict[str, Any] | None, attribute_name: str) -> dict[str, Any] | None:
    target = _clean_text(attribute_name)
    for item in _attribute_definitions(type_template):
        if _clean_text(item.get("name")) == target:
            return item
    return None


def _resolve_attribute_label(type_template: dict[str, Any] | None, attribute_name: str) -> str:
    for item in _attribute_definitions(type_template):
        if _clean_text(item.get("name")) == _clean_text(attribute_name):
            return str(item.get("alias") or item.get("name") or attribute_name)
    return attribute_name


def _format_choice_options(attribute_definition: dict[str, Any] | None, *, limit: int = 8) -> str:
    if not attribute_definition:
        return ""
    labels: list[str] = []
    for item in (attribute_definition.get("choices") or []):
        if not isinstance(item, dict):
            continue
        label = _clean_text(item.get("label")) or _clean_text(item.get("value"))
        if label and label not in labels:
            labels.append(label)
    if not labels:
        return ""
    trimmed = labels[:limit]
    suffix = " 等" if len(labels) > limit else ""
    return " / ".join(trimmed) + suffix


def _is_name_like_unique_key(unique_key: str) -> bool:
    normalized = _normalize_token(unique_key)
    return normalized.endswith("name") or "instance" in normalized or "hostname" in normalized


def _is_ip_like_unique_key(unique_key: str) -> bool:
    normalized = _normalize_token(unique_key)
    return "ip" in normalized


def _is_code_like_unique_key(unique_key: str) -> bool:
    normalized = _normalize_token(unique_key)
    return any(token in normalized for token in ("code", "no", "id"))


SPECIAL_ATTRIBUTE_NAME_CANDIDATES = {
    "asset_code": ["asset_code", "property_no", "dev_no", "p_id"],
    "name": ["name", "serverName", "dev_name", "db_instance", "middleware_name", "project_name", "product_name", "vserver_name"],
    "private_ip": ["private_ip", "privateIp", "manage_ip", "host_ip", "ip", "db_ip", "middleware_ip"],
    "status": ["status"],
    "model": ["model", "device_spec", "dev_model"],
    "version": ["version", "db_version", "dev_software_version"],
    "service_port": ["service_port", "db_port", "middleware_port", "snmp_port"],
    "owner": ["owner", "op_duty"],
    "deploy_target": ["deploy_target", "AssociatedPhyMachine"],
    "host_name": ["host_name"],
    "os_version": ["os_version", "osVersion"],
    "server_room": ["server_room"],
    "rack": ["rack", "cabinet"],
    "idc": ["idc", "data_center"],
}


def _resolve_cmdb_attribute_name(type_template: dict[str, Any] | None, canonical_field: str) -> str:
    definitions = _attribute_definitions(type_template)
    if not definitions:
        return canonical_field

    attribute_names = {_clean_text(item.get("name")) for item in definitions}
    ordered_candidates: list[str] = [canonical_field]
    ordered_candidates.extend(item for item in FIELD_ALIASES.get(canonical_field, []) if _clean_text(item))
    ordered_candidates.extend(item for item in SPECIAL_ATTRIBUTE_NAME_CANDIDATES.get(canonical_field, []) if _clean_text(item))
    candidate_tokens = {_normalize_token(canonical_field)}
    candidate_tokens.update(_normalize_token(item) for item in FIELD_ALIASES.get(canonical_field, []))
    candidate_tokens.update(_normalize_token(item) for item in SPECIAL_ATTRIBUTE_NAME_CANDIDATES.get(canonical_field, []))
    unique_key = _clean_text((type_template or {}).get("unique_key"))
    if unique_key:
        if canonical_field == "name" and _is_name_like_unique_key(unique_key) and unique_key in attribute_names:
            return unique_key
        if canonical_field == "private_ip" and _is_ip_like_unique_key(unique_key) and unique_key in attribute_names:
            return unique_key
        if canonical_field == "asset_code" and _is_code_like_unique_key(unique_key) and unique_key in attribute_names:
            return unique_key
        if canonical_field == "name" and _is_name_like_unique_key(unique_key):
            candidate_tokens.add(_normalize_token(unique_key))
        if canonical_field == "private_ip" and _is_ip_like_unique_key(unique_key):
            candidate_tokens.add(_normalize_token(unique_key))
        if canonical_field == "asset_code" and _is_code_like_unique_key(unique_key):
            candidate_tokens.add(_normalize_token(unique_key))

    for candidate_name in ordered_candidates:
        normalized_candidate = _normalize_token(candidate_name)
        for item in definitions:
            attr_name = str(item.get("name") or "")
            attr_alias = str(item.get("alias") or "")
            if not normalized_candidate:
                continue
            if (
                _normalize_token(attr_name) == normalized_candidate
                or _normalize_token(attr_alias) == normalized_candidate
            ):
                return attr_name

    for item in definitions:
        attr_name = str(item.get("name") or "")
        attr_alias = str(item.get("alias") or "")
        if _normalize_token(attr_name) in candidate_tokens or _normalize_token(attr_alias) in candidate_tokens:
            return attr_name
    return canonical_field


def _normalize_choice_attribute_value(
    *,
    attribute_definition: dict[str, Any] | None,
    value: str,
    extra_choices: list[dict[str, str]] | None = None,
) -> tuple[str, bool]:
    cleaned_value = _clean_text(value)
    if not cleaned_value:
        return "", False
    if not attribute_definition or not attribute_definition.get("is_choice"):
        return cleaned_value, False

    choice_values = list(attribute_definition.get("choices") or [])
    if extra_choices:
        choice_values.extend(extra_choices)
    if not choice_values:
        return cleaned_value, False

    normalized_input = _normalize_token(cleaned_value)
    for item in choice_values:
        choice_value = _clean_text(item.get("value"))
        choice_label = _clean_text(item.get("label"))
        if cleaned_value == choice_value or normalized_input == _normalize_token(choice_value):
            return choice_value, False
        if choice_label and (cleaned_value == choice_label or normalized_input == _normalize_token(choice_label)):
            return choice_value or choice_label, False

    return "", True


def _attribute_name_by_id(type_template: dict[str, Any] | None, attr_id: Any) -> str:
    if not type_template or attr_id in (None, ""):
        return ""
    try:
        wanted = int(attr_id)
    except Exception:
        return ""
    for item in _attribute_definitions(type_template):
        try:
            current = int(item.get("id"))
        except Exception:
            continue
        if current == wanted:
            return _clean_text(item.get("name"))
    return ""


def _collect_pending_choice_values(
    *,
    type_templates: dict[str, dict[str, Any]],
    ordered_records: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, str]]]:
    type_name_by_id: dict[int, str] = {}
    records_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for name, template in type_templates.items():
        try:
            type_id = int(template.get("id"))
        except Exception:
            continue
        type_name_by_id[type_id] = name
    for record in ordered_records:
        ci_type = _clean_text(record.get("ciType"))
        if ci_type:
            records_by_type[ci_type].append(record)

    pending: dict[tuple[str, str], list[dict[str, str]]] = {}
    for ci_type, type_template in type_templates.items():
        for item in _attribute_definitions(type_template):
            attr_name = _clean_text(item.get("name"))
            ref_attr_id = item.get("choice_reference_attr_id")
            ref_type_ids = item.get("choice_reference_type_ids") or []
            if not attr_name or not ref_attr_id or not ref_type_ids:
                continue
            collected: list[dict[str, str]] = []
            seen_values = {
                _clean_text(choice.get("value"))
                for choice in (item.get("choices") or [])
                if _clean_text(choice.get("value"))
            }
            for ref_type_id in ref_type_ids:
                try:
                    normalized_ref_type_id = int(ref_type_id)
                except Exception:
                    continue
                ref_type_name = type_name_by_id.get(normalized_ref_type_id)
                if not ref_type_name:
                    continue
                ref_template = type_templates.get(ref_type_name)
                ref_attr_name = _attribute_name_by_id(ref_template, ref_attr_id)
                if not ref_attr_name:
                    continue
                for record in records_by_type.get(ref_type_name, []):
                    record_attributes = record.get("attributes") or {}
                    value = _clean_text(record_attributes.get(ref_attr_name))
                    if not value and ref_attr_name == _resolve_cmdb_attribute_name(ref_template, "name"):
                        value = _clean_text(record.get("name"))
                    if not value:
                        continue
                    if value in seen_values:
                        continue
                    seen_values.add(value)
                    collected.append({"value": value, "label": value})
            if collected:
                pending[(ci_type, attr_name)] = collected
    return pending


def _choice_extras_for_attribute(
    *,
    ci_type: str,
    attribute_name: str,
    pending_choice_values: dict[tuple[str, str], list[dict[str, str]]] | None,
) -> list[dict[str, str]]:
    if not pending_choice_values or not ci_type or not attribute_name:
        return []
    return list(pending_choice_values.get((ci_type, attribute_name), []))


def _split_deferred_self_referential_choice_attributes(
    *,
    ci_type: str,
    type_template: dict[str, Any] | None,
    source_attributes: dict[str, Any],
    cmdb_attributes: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not type_template:
        return cmdb_attributes, {}
    try:
        current_type_id = int(type_template.get("id"))
    except Exception:
        return cmdb_attributes, {}

    immediate = dict(cmdb_attributes)
    deferred: dict[str, Any] = {}
    for item in _attribute_definitions(type_template):
        attr_name = _clean_text(item.get("name"))
        ref_attr_id = item.get("choice_reference_attr_id")
        ref_type_ids = item.get("choice_reference_type_ids") or []
        if not attr_name or attr_name not in immediate or not ref_attr_id or current_type_id not in ref_type_ids:
            continue
        ref_attr_name = _attribute_name_by_id(type_template, ref_attr_id)
        if not ref_attr_name:
            continue
        ref_value = _clean_text(source_attributes.get(ref_attr_name))
        if not ref_value and ref_attr_name == _resolve_cmdb_attribute_name(type_template, "name"):
            ref_value = _clean_text(source_attributes.get(ref_attr_name)) or _clean_text(source_attributes.get("name"))
        if not ref_value:
            continue

        current_value = immediate.get(attr_name)
        if isinstance(current_value, list):
            matches_self = ref_value in {_clean_text(entry) for entry in current_value if _clean_text(entry)}
        else:
            matches_self = _clean_text(current_value) == ref_value
        if not matches_self:
            continue
        deferred[attr_name] = immediate.pop(attr_name)
    return immediate, deferred


def _build_cmdb_attributes(
    *,
    ci_type: str,
    canonical_attributes: dict[str, Any],
    type_template: dict[str, Any] | None,
    pending_choice_values: dict[tuple[str, str], list[dict[str, str]]] | None = None,
) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    for key, value in canonical_attributes.items():
        cleaned_value = _clean_text(value)
        if not cleaned_value:
            continue
        target_key = _resolve_cmdb_attribute_name(type_template, key)
        if not target_key:
            continue
        attribute_definition = _find_attribute_definition(type_template, target_key)
        if attribute_definition and attribute_definition.get("is_list"):
            raw_items = _split_reference_values(cleaned_value) or [cleaned_value]
            normalized_items: list[str] = []
            unresolved_choice = False
            extra_choices = _choice_extras_for_attribute(
                ci_type=ci_type,
                attribute_name=target_key,
                pending_choice_values=pending_choice_values,
            )
            for item in raw_items:
                normalized_value, unresolved_choice = _normalize_choice_attribute_value(
                    attribute_definition=attribute_definition,
                    value=item,
                    extra_choices=extra_choices,
                )
                if unresolved_choice:
                    break
                if normalized_value:
                    normalized_items.append(normalized_value)
            if unresolved_choice:
                continue
            if normalized_items:
                attributes[target_key] = normalized_items
            continue

        normalized_value, unresolved_choice = _normalize_choice_attribute_value(
            attribute_definition=attribute_definition,
            value=cleaned_value,
            extra_choices=_choice_extras_for_attribute(
                ci_type=ci_type,
                attribute_name=target_key,
                pending_choice_values=pending_choice_values,
            ),
        )
        if unresolved_choice:
            continue
        attributes[target_key] = normalized_value

    unique_key = _clean_text((type_template or {}).get("unique_key"))
    if unique_key and not _clean_text(attributes.get(unique_key)):
        fallback_field = ""
        if _is_name_like_unique_key(unique_key):
            fallback_field = "name"
        elif _is_ip_like_unique_key(unique_key):
            fallback_field = "private_ip"
        elif _is_code_like_unique_key(unique_key):
            fallback_field = "asset_code"
        fallback_value = _clean_text(canonical_attributes.get(fallback_field)) if fallback_field else ""
        if fallback_value:
            attributes[unique_key] = fallback_value

    return attributes


def _build_preview_attributes(
    attributes: dict[str, Any],
    type_template: dict[str, Any] | None,
) -> dict[str, str]:
    preview_attributes: dict[str, str] = {}
    for key, value in attributes.items():
        cleaned_value = _clean_text(value)
        if not cleaned_value or key == "ci_type" or str(key).startswith("_"):
            continue
        target_key = _resolve_cmdb_attribute_name(type_template, key)
        attr_definition = _find_attribute_definition(type_template, target_key)
        if attr_definition:
            preview_attributes.setdefault(target_key, cleaned_value)
            continue
        preview_attributes.setdefault(key, cleaned_value)
    return preview_attributes


def _resolve_record_display_name(
    attributes: dict[str, Any],
    type_template: dict[str, Any] | None,
) -> str:
    candidate_fields = [
        "name",
        "dev_name",
        _clean_text((type_template or {}).get("unique_key")),
        "asset_code",
        "dev_no",
        "private_ip",
        "manage_ip",
    ]
    for field in candidate_fields:
        value = _clean_text(attributes.get(field))
        if value:
            return value
    return ""


def _build_record_issues(
    *,
    ci_type: str,
    attributes: dict[str, Any],
    mapping_preview: list[dict[str, Any]],
    existing_ci: dict[str, Any] | None,
    type_template: dict[str, Any] | None = None,
    pending_choice_values: dict[tuple[str, str], list[dict[str, str]]] | None = None,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    def to_target_field(field_name: str) -> str:
        resolved = _resolve_cmdb_attribute_name(type_template, field_name)
        return resolved or field_name

    confirmation_labels = _collect_confirmation_issues(ci_type, attributes)
    label_to_field = {
        "名称": "name",
        "IP": "private_ip",
        "型号": "model",
        "版本": "version",
        "端口": "service_port",
        "部署节点": "deploy_target",
    }
    for label in confirmation_labels:
        issues.append(
            {
                "field": to_target_field(label_to_field.get(label, "")),
                "level": "warning",
                "message": f"{label}待确认",
            }
        )

    unique_key = _clean_text((type_template or {}).get("unique_key"))
    cmdb_attributes = _build_cmdb_attributes(
        ci_type=ci_type,
        canonical_attributes=attributes,
        type_template=type_template,
        pending_choice_values=pending_choice_values,
    )
    if unique_key and not _clean_text(cmdb_attributes.get(unique_key)):
        target_field = "name"
        if _is_ip_like_unique_key(unique_key):
            target_field = "private_ip"
        elif _is_code_like_unique_key(unique_key):
            target_field = "asset_code"
        issues.append(
            {
                "field": to_target_field(target_field),
                "level": "warning",
                "message": f"唯一标识 {_resolve_attribute_label(type_template, unique_key)} 待确认",
            }
        )

    seen_mapping_fields: set[str] = set()
    for item in mapping_preview:
        target_field = _clean_text(item.get("targetField"))
        confidence = _clean_text(item.get("confidence"))
        source_field = _clean_text(item.get("sourceField"))
        if target_field in {"", "unknown"} or confidence in {"", "high"} or target_field in seen_mapping_fields:
            continue
        seen_mapping_fields.add(target_field)
        issues.append(
            {
                "field": to_target_field(target_field),
                "level": "warning",
                "message": f"{source_field} 映射到 {target_field} 的置信度为 {confidence}",
            }
        )

    for canonical_field, raw_value in attributes.items():
        if canonical_field == "ci_type":
            continue
        cleaned_value = _clean_text(raw_value)
        if not cleaned_value:
            continue
        target_key = _resolve_cmdb_attribute_name(type_template, canonical_field)
        attr_definition = _find_attribute_definition(type_template, target_key)
        normalized_value, unresolved_choice = _normalize_choice_attribute_value(
            attribute_definition=attr_definition,
            value=cleaned_value,
            extra_choices=_choice_extras_for_attribute(
                ci_type=ci_type,
                attribute_name=target_key,
                pending_choice_values=pending_choice_values,
            ),
        )
        if unresolved_choice:
            option_text = _format_choice_options(attr_definition)
            message = f"{_resolve_attribute_label(type_template, target_key)} 的值 {cleaned_value} 不在系统预定义值中，请手动确认"
            if option_text:
                message += f"。可选值：{option_text}"
            issues.append(
                {
                    "field": target_key or canonical_field,
                    "level": "warning",
                    "message": message,
                }
            )

    if existing_ci:
        match_field = _clean_text(existing_ci.get("matchField")) or "name"
        match_value = _clean_text(existing_ci.get("matchValue"))
        issues.append(
            {
                "field": "importAction",
                "level": "warning",
                "message": f"CMDB 中已存在匹配资源（{match_field}: {match_value}），请确认更新还是跳过",
            }
        )

    return issues


def _validate_required_cmdb_attributes(
    *,
    type_template: dict[str, Any] | None,
    source_attributes: dict[str, Any],
    cmdb_attributes: dict[str, Any],
    pending_choice_values: dict[tuple[str, str], list[dict[str, str]]] | None = None,
) -> list[str]:
    issues: list[str] = []
    ci_type = _clean_text((type_template or {}).get("name"))
    for item in _attribute_definitions(type_template):
        attr_name = _clean_text(item.get("name"))
        if not attr_name or not item.get("required"):
            continue

        value = cmdb_attributes.get(attr_name)
        if isinstance(value, list):
            present = any(_clean_text(entry) for entry in value)
        else:
            present = bool(_clean_text(value))
        if present:
            continue

        raw_value = source_attributes.get(attr_name)
        raw_values: list[str] = []
        if isinstance(raw_value, list):
            raw_values = [_clean_text(entry) for entry in raw_value if _clean_text(entry)]
        else:
            cleaned_raw_value = _clean_text(raw_value)
            if cleaned_raw_value:
                raw_values = [cleaned_raw_value]

        label = _resolve_attribute_label(type_template, attr_name)
        option_text = _format_choice_options(item)
        if raw_values and item.get("is_choice"):
            message = f"{label} 的值 {' / '.join(raw_values)} 不在系统预定义值中"
            extra_choice_text = _format_choice_options(
                {
                    **item,
                    "choices": (item.get("choices") or [])
                    + _choice_extras_for_attribute(
                        ci_type=ci_type,
                        attribute_name=attr_name,
                        pending_choice_values=pending_choice_values,
                    ),
                }
            )
            option_text = extra_choice_text or option_text
            if option_text:
                message += f"，可选值：{option_text}"
            issues.append(message)
            continue

        message = f"缺少必填字段：{label}"
        if option_text:
            message += f"（可选值：{option_text}）"
        issues.append(message)
    return issues


def _snapshot_ci_attributes(
    record: dict[str, Any] | None,
    *,
    type_template: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    allowed_fields = {
        _clean_text(item.get("name"))
        for item in _attribute_definitions(type_template)
        if _clean_text(item.get("name"))
    }
    snapshot: dict[str, Any] = {}
    for key, value in record.items():
        field_name = _clean_text(key)
        if not field_name or field_name.startswith("_"):
            continue
        if field_name in {"ci_type", "ci_type_alias", "unique", "unique_alias"}:
            continue
        if allowed_fields and field_name not in allowed_fields:
            continue
        snapshot[field_name] = value
    return snapshot


def _selected_record_map(resource_groups: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for group in resource_groups:
        for record in (group.get("records") or []):
            if not isinstance(record, dict) or not record.get("selected", True):
                continue
            preview_key = str(record.get("previewKey") or "").strip()
            if preview_key:
                selected[preview_key] = record
    return selected


def _ordered_selected_records(
    resource_groups: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered_records: list[dict[str, Any]] = []
    selected = _selected_record_map(resource_groups)
    if not selected:
        return ordered_records

    original_order: dict[str, int] = {}
    for group in resource_groups:
        for record in (group.get("records") or []):
            preview_key = str(record.get("previewKey") or "").strip()
            if preview_key and preview_key in selected and preview_key not in original_order:
                original_order[preview_key] = len(original_order)

    adjacency: dict[str, set[str]] = {key: set() for key in selected}
    indegree: dict[str, int] = {key: 0 for key in selected}
    for relation in relations or []:
        if not isinstance(relation, dict) or not relation.get("selected", True):
            continue
        source_key = str(relation.get("sourceKey") or "").strip()
        target_key = str(relation.get("targetKey") or "").strip()
        if source_key not in selected or target_key not in selected or source_key == target_key:
            continue
        targets = adjacency.setdefault(source_key, set())
        if target_key in targets:
            continue
        targets.add(target_key)
        indegree[target_key] = indegree.get(target_key, 0) + 1
        indegree.setdefault(source_key, 0)

    ready = sorted((key for key, degree in indegree.items() if degree == 0), key=lambda item: original_order.get(item, 10**9))
    ordered_keys: list[str] = []
    while ready:
        current = ready.pop(0)
        ordered_keys.append(current)
        for target in sorted(adjacency.get(current, set()), key=lambda item: original_order.get(item, 10**9)):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort(key=lambda item: original_order.get(item, 10**9))

    if len(ordered_keys) != len(selected):
        remaining = [key for key in selected if key not in ordered_keys]
        remaining.sort(key=lambda item: original_order.get(item, 10**9))
        ordered_keys.extend(remaining)

    return [selected[key] for key in ordered_keys]


def _preflight_import_resources(
    client: VeopsCmdbClient,
    *,
    type_templates: dict[str, dict[str, Any]],
    ordered_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    pending_choice_values = _collect_pending_choice_values(
        type_templates=type_templates,
        ordered_records=ordered_records,
    )
    for record in ordered_records:
        import_action = _clean_text(record.get("importAction")) or "create"
        ci_type = str(record.get("ciType") or "").strip()
        preview_key = record.get("previewKey")
        if not ci_type or ci_type == "unknown":
            results.append({"previewKey": preview_key, "status": "failed", "message": "资源类型未确认，无法导入"})
            continue

        type_template = type_templates.get(ci_type, {})
        if not type_template:
            results.append({"previewKey": preview_key, "status": "failed", "message": f"目标模型 {ci_type} 不存在或尚未创建完成，当前不能导入"})
            continue

        attributes = {key: value for key, value in (record.get("attributes") or {}).items() if _clean_text(value)}
        display_name = _clean_text(record.get("name")) or _resolve_record_display_name(attributes, type_template)
        if display_name and not _resolve_record_display_name(attributes, type_template):
            fallback_field = _resolve_cmdb_attribute_name(type_template, "name")
            if fallback_field and _find_attribute_definition(type_template, fallback_field):
                attributes[fallback_field] = display_name

        cmdb_attributes = _build_cmdb_attributes(
            ci_type=ci_type,
            canonical_attributes=attributes,
            type_template=type_template,
            pending_choice_values=pending_choice_values,
        )
        unique_key = _clean_text(type_template.get("unique_key"))
        if not display_name and not _clean_text(cmdb_attributes.get(unique_key)):
            results.append({"previewKey": preview_key, "status": "failed", "message": "缺少资源名称或模型唯一标识，无法导入"})
            continue
        if unique_key and not _clean_text(cmdb_attributes.get(unique_key)):
            results.append({"previewKey": preview_key, "status": "failed", "message": f"缺少模型唯一标识字段：{_resolve_attribute_label(type_template, unique_key)}"})
            continue

        required_attribute_issues = _validate_required_cmdb_attributes(
            type_template=type_template,
            source_attributes=attributes,
            cmdb_attributes=cmdb_attributes,
            pending_choice_values=pending_choice_values,
        )
        if required_attribute_issues:
            results.append({"previewKey": preview_key, "status": "failed", "message": "；".join(required_attribute_issues)})
            continue

        existing_ci = _find_existing_ci(
            client,
            ci_type,
            cmdb_attributes,
            fallback_name=display_name,
            unique_key=unique_key,
        ) or (record.get("existingCi") or {})

        if existing_ci and import_action == "create":
            results.append({"previewKey": preview_key, "status": "failed", "ciId": existing_ci.get("ciId"), "message": "CMDB 中已存在匹配资源，请改为更新或跳过"})
            continue
        if not existing_ci and import_action == "update":
            results.append({"previewKey": preview_key, "status": "failed", "message": "CMDB 中未找到待更新资源，请改为新建或重新预览"})
            continue
    return results


def _split_reference_values(value: str) -> list[str]:
    raw = _clean_text(value)
    if not raw:
        return []
    parts = re.split(r"[;,；、/\n]+", raw)
    return [item.strip() for item in parts if item.strip() and item.strip() != "-"]


def _merged_resource_attributes(resource: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for source in (resource.get("attributes") or {}, resource.get("analysisAttributes") or {}):
        if not isinstance(source, dict):
            continue
        for field_name, field_value in source.items():
            if field_name not in merged:
                merged[field_name] = field_value
    return merged


def _build_reference_indexes(resources: list[dict[str, Any]]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    name_index: dict[str, list[str]] = defaultdict(list)
    ip_index: dict[str, list[str]] = defaultdict(list)
    for item in resources:
        name = _normalize_token(item.get("name"))
        if name:
            name_index[name].append(item["previewKey"])
        analysis_attributes = _merged_resource_attributes(item)
        private_ip = _clean_text(analysis_attributes.get("private_ip") or analysis_attributes.get("manage_ip"))
        if private_ip:
            ip_index[private_ip].append(item["previewKey"])
    return name_index, ip_index


def _find_reference_keys(
    value: str,
    *,
    name_index: dict[str, list[str]],
    ip_index: dict[str, list[str]],
) -> list[str]:
    matches: list[str] = []
    for token in _split_reference_values(value):
        normalized_name = _normalize_token(token)
        if normalized_name in name_index:
            matches.extend(name_index[normalized_name])
            continue
        normalized_ip, _ = _normalize_ip(token)
        if normalized_ip in ip_index:
            matches.extend(ip_index[normalized_ip])
    return list(dict.fromkeys(matches))


def _relation_lookup_tokens(value: Any) -> list[str]:
    tokens: list[str] = []
    for raw_token in _split_reference_values(_clean_text(value)) or [_clean_text(value)]:
        cleaned = _clean_text(raw_token)
        if not cleaned:
            continue
        normalized_text = _normalize_token(cleaned)
        if normalized_text:
            tokens.append(f"text::{normalized_text}")
        normalized_ip, _ = _normalize_ip(cleaned)
        if normalized_ip:
            tokens.append(f"ip::{normalized_ip}")
    return list(dict.fromkeys(tokens))


def _is_relation_lookup_field(field_name: str) -> bool:
    normalized = _normalize_token(field_name)
    if not normalized:
        return False
    if normalized in {
        "name",
        "assetcode",
        "privateip",
        "manageip",
        "pid",
        "project",
        "product",
        "department",
        "platform",
        "projectname",
        "devno",
        "devname",
        "dbinstance",
        "middlewarename",
        "vservername",
        "hostname",
    }:
        return True
    return any(token in normalized for token in ("name", "ip", "code", "instance", "host", "device", "resource", "id"))


def _build_resource_relation_lookup(
    resources: list[dict[str, Any]],
    type_templates: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    global_index: dict[str, list[str]] = defaultdict(list)
    type_index: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    field_index: dict[str, dict[str, dict[str, list[str]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    def add_index(container: dict[str, list[str]], token: str, preview_key: str) -> None:
        if not token:
            return
        if preview_key not in container[token]:
            container[token].append(preview_key)

    for item in resources:
        preview_key = str(item.get("previewKey") or "")
        ci_type = _clean_text(item.get("ciType"))
        if not preview_key or not ci_type:
            continue
        type_template = type_templates.get(ci_type) or {}
        unique_key = _clean_text(type_template.get("unique_key"))
        candidate_fields: dict[str, Any] = {}

        if _clean_text(item.get("name")):
            candidate_fields["name"] = item.get("name")

        for source in (item.get("attributes") or {}, item.get("analysisAttributes") or {}):
            for field_name, field_value in source.items():
                if not _clean_text(field_name):
                    continue
                if field_name == unique_key or _is_relation_lookup_field(field_name):
                    candidate_fields.setdefault(field_name, field_value)

        for field_name, field_value in candidate_fields.items():
            for token in _relation_lookup_tokens(field_value):
                add_index(global_index, token, preview_key)
                add_index(type_index[ci_type], token, preview_key)
                add_index(field_index[ci_type][field_name], token, preview_key)

    return {
        "global": global_index,
        "by_type": type_index,
        "by_type_field": field_index,
    }


def _resolve_relation_reference_keys(
    value: Any,
    *,
    lookup: dict[str, Any],
    preferred_type: str = "",
    preferred_field: str | list[str] = "",
    allow_global_fallback: bool = True,
) -> list[str]:
    matches: list[str] = []
    tokens = _relation_lookup_tokens(value)
    if not tokens:
        return []

    if isinstance(preferred_field, str):
        preferred_fields = [_clean_text(preferred_field)] if _clean_text(preferred_field) else []
    else:
        preferred_fields = []
        for item in preferred_field:
            cleaned = _clean_text(item)
            if cleaned and cleaned not in preferred_fields:
                preferred_fields.append(cleaned)

    if preferred_type and preferred_fields:
        for field_name in preferred_fields:
            field_values = lookup["by_type_field"].get(preferred_type, {}).get(field_name, {})
            for token in tokens:
                matches.extend(field_values.get(token, []))
            if matches:
                return list(dict.fromkeys(matches))

    if preferred_type:
        type_values = lookup["by_type"].get(preferred_type, {})
        for token in tokens:
            matches.extend(type_values.get(token, []))
        if matches:
            return list(dict.fromkeys(matches))

    if not allow_global_fallback:
        return []

    for token in tokens:
        matches.extend(lookup["global"].get(token, []))
    return list(dict.fromkeys(matches))


def _infer_relation_type_for_models(
    source_type: str,
    target_type: str,
    type_templates: dict[str, dict[str, Any]],
) -> str:
    target_template = type_templates.get(target_type) or {}
    for parent in (target_template.get("parentTypes") or []):
        if _clean_text(parent.get("name")) == source_type:
            return _normalize_relation_type(parent.get("relationType")) or "contain"
    if source_type in {"project", "product", "Department"}:
        return "contain"
    if target_type in SOFTWARE_RESOURCE_TYPES and source_type in RESOURCE_DEPLOY_TYPES:
        return "deploy"
    return "connect"


def _candidate_parent_values(
    resource: dict[str, Any],
    parent_type: dict[str, Any],
) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    attributes = _merged_resource_attributes(resource)
    parent_name = _clean_text(parent_type.get("name"))
    show_key = _clean_text(parent_type.get("showKey")) or "name"
    child_attr_names = [
        _clean_text(item)
        for item in (parent_type.get("childAttrNames") or [])
        if _clean_text(item)
    ]

    candidate_fields = [*child_attr_names, show_key, parent_name]
    if parent_name == "project":
        candidate_fields.extend(["project", "platform", "project_name"])
    elif parent_name == "product":
        candidate_fields.extend(["product"])
    elif parent_name == "Department":
        candidate_fields.extend(["department"])

    normalized_show_key = _normalize_token(show_key)
    if "ip" in normalized_show_key:
        candidate_fields.extend(["deploy_target", "private_ip", "manage_ip", "host_ip"])
    elif any(token in normalized_show_key for token in ("id", "code", "instance", "name")):
        candidate_fields.extend(["deploy_target", "asset_code", "name", "host_name"])

    for field_name in candidate_fields:
        raw_value = attributes.get(field_name)
        for token in _split_reference_values(_clean_text(raw_value)):
            if token and token not in seen:
                seen.add(token)
                values.append(token)
    return values


def _parent_lookup_fields(parent_type: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    for item in parent_type.get("parentAttrNames") or []:
        cleaned = _clean_text(item)
        if cleaned and cleaned not in fields:
            fields.append(cleaned)
    show_key = _clean_text(parent_type.get("showKey"))
    if show_key and show_key not in fields:
        fields.append(show_key)
    if not fields:
        fields.append("name")
    return fields


def _infer_parent_field_relations(
    resources: list[dict[str, Any]],
    relations: dict[tuple[str, str, str], dict[str, Any]],
    type_templates: dict[str, dict[str, Any]],
) -> None:
    lookup = _build_resource_relation_lookup(resources, type_templates)
    for item in resources:
        ci_type = _clean_text(item.get("ciType"))
        preview_key = str(item.get("previewKey") or "")
        if not ci_type or not preview_key:
            continue
        type_template = type_templates.get(ci_type) or {}
        for parent_type in (type_template.get("parentTypes") or []):
            parent_name = _clean_text(parent_type.get("name"))
            if not parent_name:
                continue
            relation_type = _normalize_relation_type(parent_type.get("relationType")) or _infer_relation_type_for_models(
                parent_name,
                ci_type,
                type_templates,
            )
            parent_lookup_fields = _parent_lookup_fields(parent_type)
            for candidate_value in _candidate_parent_values(item, parent_type):
                for parent_key in _resolve_relation_reference_keys(
                    candidate_value,
                    lookup=lookup,
                    preferred_type=parent_name,
                    preferred_field=parent_lookup_fields,
                    allow_global_fallback=False,
                ):
                    _append_relation(
                        relations,
                        source_key=parent_key,
                        target_key=preview_key,
                        relation_type=relation_type,
                        confidence="high",
                        reason=f"基于 {parent_name} 关联字段自动识别父子关系",
                    )


def _infer_explicit_relation_rows(
    relation_rows: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    relations: dict[tuple[str, str, str], dict[str, Any]],
    type_templates: dict[str, dict[str, Any]],
) -> list[str]:
    lookup = _build_resource_relation_lookup(resources, type_templates)
    alias_index = _build_type_alias_index(list(type_templates.values()))
    warnings: list[str] = []

    for row in relation_rows:
        source_model = _normalize_ci_type(_clean_text(row.get("source_model")), alias_index)
        source_field = _clean_text(row.get("source_field"))
        source_value = _clean_text(row.get("source_value"))
        target_model = _normalize_ci_type(_clean_text(row.get("target_model")), alias_index)
        target_field = _clean_text(row.get("target_field"))
        target_value = _clean_text(row.get("target_value"))
        if source_model and source_field:
            source_canonical_field, _ = _match_field(source_field)
            source_field = _resolve_cmdb_attribute_name(
                type_templates.get(source_model),
                source_canonical_field if source_canonical_field != "unknown" else source_field,
            )
        if target_model and target_field:
            target_canonical_field, _ = _match_field(target_field)
            target_field = _resolve_cmdb_attribute_name(
                type_templates.get(target_model),
                target_canonical_field if target_canonical_field != "unknown" else target_field,
            )
        relation_type = _normalize_relation_type(row.get("relation_type")) or _infer_relation_type_for_models(
            source_model,
            target_model,
            type_templates,
        )

        source_matches = _resolve_relation_reference_keys(
            source_value,
            lookup=lookup,
            preferred_type=source_model,
            preferred_field=source_field,
        )
        target_matches = _resolve_relation_reference_keys(
            target_value,
            lookup=lookup,
            preferred_type=target_model,
            preferred_field=target_field,
        )

        row_label = (
            f"{row.get('filename') or ''} / {row.get('sheet') or ''} 第 {row.get('rowIndex') or ''} 行"
        ).strip(" /")
        if not source_matches or not target_matches:
            warnings.append(
                f"{row_label} 关系未能解析：源 {source_model or '?'}={source_value or '?'}，"
                f"目标 {target_model or '?'}={target_value or '?'}。"
            )
            continue
        if len(source_matches) > 1 or len(target_matches) > 1:
            warnings.append(
                f"{row_label} 关系解析存在歧义：源匹配 {len(source_matches)} 条，目标匹配 {len(target_matches)} 条，已跳过。"
            )
            continue
        resolved_source_type = source_model or _clean_text(
            next((item.get("ciType") for item in resources if item.get("previewKey") == source_matches[0]), "")
        )
        resolved_target_type = target_model or _clean_text(
            next((item.get("ciType") for item in resources if item.get("previewKey") == target_matches[0]), "")
        )
        configured_relation_type = _infer_relation_type_for_models(
            resolved_source_type,
            resolved_target_type,
            type_templates,
        )
        final_relation_type = configured_relation_type or relation_type or "contain"
        _append_relation(
            relations,
            source_key=source_matches[0],
            target_key=target_matches[0],
            relation_type=final_relation_type,
            confidence="high",
            reason="基于显式关系表识别",
        )

    return warnings


def _infer_existing_resource_relations(
    resources: list[dict[str, Any]],
    relations: dict[tuple[str, str, str], dict[str, Any]],
    type_templates: dict[str, dict[str, Any]],
) -> None:
    name_index, ip_index = _build_reference_indexes(resources)
    subnet_network_devices: dict[str, list[str]] = defaultdict(list)
    subnet_compute_resources: dict[str, list[str]] = defaultdict(list)
    resource_type_map = {
        str(item.get("previewKey")): _clean_text(item.get("ciType"))
        for item in resources
        if item.get("previewKey")
    }

    for item in resources:
        preview_key = item["previewKey"]
        ci_type = item["ciType"]
        attributes = _merged_resource_attributes(item)

        for target_key in _find_reference_keys(
            attributes.get("deploy_target") or attributes.get("host_name") or "",
            name_index=name_index,
            ip_index=ip_index,
        ):
            source_type = resource_type_map.get(target_key, "")
            relation_type = _infer_relation_type_for_models(
                source_type,
                ci_type,
                type_templates,
            ) or "deploy"
            _append_relation(
                relations,
                source_key=target_key,
                target_key=preview_key,
                relation_type=relation_type,
                confidence="high" if ci_type in SOFTWARE_RESOURCE_TYPES else "medium",
                reason="基于宿主机/部署节点字段建立部署关系",
            )

        for upstream_key in _find_reference_keys(
            attributes.get("upstream_resource", ""),
            name_index=name_index,
            ip_index=ip_index,
        ):
            _append_relation(
                relations,
                source_key=upstream_key,
                target_key=preview_key,
                relation_type="connect",
                confidence="high",
                reason="基于上联设备字段建立连接关系",
            )

        private_ip = _clean_text(attributes.get("private_ip"))
        if not private_ip:
            continue
        subnet = _infer_subnet("", private_ip)
        if not subnet:
            continue
        if ci_type == "networkdevice":
            subnet_network_devices[subnet].append(preview_key)
        elif ci_type in {"PhysicalMachine", "vserver"} | SOFTWARE_RESOURCE_TYPES:
            subnet_compute_resources[subnet].append(preview_key)

    for subnet, target_keys in subnet_compute_resources.items():
        if subnet not in subnet_network_devices:
            continue
        source_key = subnet_network_devices[subnet][0]
        for target_key in target_keys:
            _append_relation(
                relations,
                source_key=source_key,
                target_key=target_key,
                relation_type="connect",
                confidence="medium",
                reason=f"基于 {subnet} 网段自动推断网络连通关系",
            )


def _build_allowed_relation_rules(
    client: VeopsCmdbClient | None,
    type_templates: dict[str, dict[str, Any]],
    involved_types: set[str],
) -> set[tuple[str, str, str]]:
    if client is None or not involved_types:
        return set()

    relation_rules: set[tuple[str, str, str]] = set()
    fetched_type_ids: set[str] = set()
    for ci_type in involved_types:
        template = type_templates.get(ci_type) or {}
        type_id = str(template.get("id") or "").strip()
        if not type_id or type_id in fetched_type_ids:
            continue
        fetched_type_ids.add(type_id)
        try:
            relations = client.get_ci_type_relations(type_id)
        except Exception:
            continue
        for item in relations:
            parent_name = _clean_text((item.get("parent") or {}).get("name"))
            child_name = _clean_text((item.get("child") or {}).get("name"))
            relation_name = _clean_text(((item.get("relation_type") or {}).get("name")) or item.get("relation_type_name"))
            if parent_name and child_name and relation_name:
                relation_rules.add((parent_name, relation_name, child_name))
    return relation_rules


def _filter_supported_relations(
    relations: dict[tuple[str, str, str], dict[str, Any]],
    resources: list[dict[str, Any]],
    allowed_rules: set[tuple[str, str, str]],
) -> tuple[dict[tuple[str, str, str], dict[str, Any]], list[str]]:
    if not allowed_rules:
        return relations, []

    resource_type_map = {
        str(item.get("previewKey")): _clean_text(item.get("ciType"))
        for item in resources
        if item.get("previewKey")
    }
    filtered: dict[tuple[str, str, str], dict[str, Any]] = {}
    skipped_messages: list[str] = []
    for key, relation in relations.items():
        source_key = str(relation.get("sourceKey") or "")
        target_key = str(relation.get("targetKey") or "")
        relation_type = _clean_text(relation.get("relationType"))
        source_type = resource_type_map.get(source_key, "")
        target_type = resource_type_map.get(target_key, "")
        if (source_type, relation_type, target_type) in allowed_rules:
            filtered[key] = relation
            continue
        filtered[key] = {
            **relation,
            "selected": bool(relation.get("selected", True)),
            "requiresModelRelation": True,
            "reason": (
                f"{relation.get('reason') or '已识别关系'}；"
                f"CMDB 尚未配置 {source_type or '?'} -> {relation_type or '?'} -> {target_type or '?'}，"
                "导入时需先创建模型关系"
            ),
        }
        skipped_messages.append(
            f"待创建模型关系：{source_type or '?'} -> {relation_type or '?'} -> {target_type or '?'}"
        )
    return filtered, skipped_messages


def _prune_redundant_root_relations(
    relations: dict[tuple[str, str, str], dict[str, Any]],
    resources: list[dict[str, Any]],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    resource_type_map = {
        str(item.get("previewKey")): _clean_text(item.get("ciType"))
        for item in resources
        if item.get("previewKey")
    }
    root_types = {"project", "product", "Department"}
    stronger_incoming_targets: set[str] = set()

    for relation in relations.values():
        source_key = str(relation.get("sourceKey") or "")
        target_key = str(relation.get("targetKey") or "")
        relation_type = _clean_text(relation.get("relationType"))
        source_type = resource_type_map.get(source_key, "")
        target_type = resource_type_map.get(target_key, "")
        if not target_key or not source_type or not target_type:
            continue
        if source_type in root_types:
            continue
        if relation_type in {"deploy", "install", "connect", "contain"}:
            stronger_incoming_targets.add(target_key)

    pruned: dict[tuple[str, str, str], dict[str, Any]] = {}
    for key, relation in relations.items():
        source_key = str(relation.get("sourceKey") or "")
        target_key = str(relation.get("targetKey") or "")
        relation_type = _clean_text(relation.get("relationType"))
        source_type = resource_type_map.get(source_key, "")
        target_type = resource_type_map.get(target_key, "")
        if (
            target_key in stronger_incoming_targets
            and source_type in root_types
            and target_type in SOFTWARE_RESOURCE_TYPES
            and relation_type in {"contain", "deploy"}
        ):
            continue
        pruned[key] = relation
    return pruned


def _ensure_selected_model_relations(
    client: VeopsCmdbClient,
    payload: dict[str, Any],
    *,
    type_templates: dict[str, dict[str, Any]],
    resource_type_map: dict[str, str],
    allowed_relation_rules: set[tuple[str, str, str]],
) -> tuple[set[tuple[str, str, str]], list[dict[str, Any]]]:
    ensured_rules = set(allowed_relation_rules)
    results: list[dict[str, Any]] = []
    pending_rules: dict[tuple[str, str, str], dict[str, str]] = {}

    for relation in payload.get("relations") or []:
        if not relation.get("selected", True):
            continue
        source_type = resource_type_map.get(str(relation.get("sourceKey") or ""), "")
        target_type = resource_type_map.get(str(relation.get("targetKey") or ""), "")
        relation_type = _clean_text(relation.get("relationType")) or "contain"
        if not source_type or not target_type:
            continue
        rule = (source_type, relation_type, target_type)
        if rule in ensured_rules:
            continue
        pending_rules.setdefault(
            rule,
            {
                "sourceType": source_type,
                "targetType": target_type,
                "relationType": relation_type,
            },
        )

    for source_type, relation_type, target_type in sorted(pending_rules.keys()):
        source_template = type_templates.get(source_type) or {}
        target_template = type_templates.get(target_type) or {}
        source_type_id = _extract_type_id(source_template.get("id"))
        target_type_id = _extract_type_id(target_template.get("id"))
        relation_type_id = client.relation_type_map.get(relation_type)

        if source_type_id is None or target_type_id is None:
            results.append(
                {
                    "kind": "relation-config",
                    "status": "failed",
                    "sourceType": source_type,
                    "targetType": target_type,
                    "relationType": relation_type,
                    "message": (
                        f"模型关系 {source_type} -> {relation_type} -> {target_type} 缺少模型 ID，"
                        "当前不能创建关系配置"
                    ),
                }
            )
            continue

        if relation_type_id is None:
            results.append(
                {
                    "kind": "relation-config",
                    "status": "failed",
                    "sourceType": source_type,
                    "targetType": target_type,
                    "relationType": relation_type,
                    "message": f"关系类型 {relation_type} 未在 CMDB 关系类型列表中找到，当前不能创建",
                }
            )
            continue

        try:
            relation_config_id, response = client.create_ci_type_relation(
                source_type_id,
                target_type_id,
                relation_type_id=relation_type_id,
                constraint="0",
            )
            ensured_rules.add((source_type, relation_type, target_type))
            results.append(
                {
                    "kind": "relation-config",
                    "status": "success",
                    "sourceType": source_type,
                    "targetType": target_type,
                    "relationType": relation_type,
                    "ctrId": relation_config_id or _extract_ci_type_relation_id(response),
                    "message": f"已创建模型关系 {source_type} -> {relation_type} -> {target_type}",
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "kind": "relation-config",
                    "status": "failed",
                    "sourceType": source_type,
                    "targetType": target_type,
                    "relationType": relation_type,
                    "message": f"创建模型关系失败：{exc}",
                }
            )

    return ensured_rules, results


async def preview_resource_import(
    parsed_files: list[ParsedFile],
    metadata: dict[str, Any],
    *,
    llm_client: Any | None = None,
    runtime_source: str = "",
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    model_templates = metadata.get("ciTypes") or DEFAULT_MODEL_TEMPLATES
    alias_index = _build_type_alias_index(model_templates)
    type_template_map = {
        str(item.get("name")): item
        for item in model_templates
        if isinstance(item, dict) and item.get("name")
    }
    managed_runtime = None
    managed_llm_client = llm_client
    if managed_llm_client is None:
        managed_runtime = await resolve_resource_import_runtime()
        managed_llm_client = managed_runtime.client
        if not runtime_source:
            runtime_source = managed_runtime.source
    field_stats: dict[tuple[str, str], int] = defaultdict(int)
    cleaning_changes: Counter[str] = Counter()
    warnings: list[str] = []
    logs: list[str] = []
    raw_resources: list[dict[str, Any]] = []
    explicit_relation_rows: list[dict[str, Any]] = []
    skipped_rows = 0
    raw_row_total = sum(len(parsed_file.rows) for parsed_file in parsed_files)
    existing_client: VeopsCmdbClient | None = None
    existing_detected_count = 0
    remaining_existing_prechecks = max(0, RESOURCE_IMPORT_PRECHECK_LIMIT)
    precheck_limit_hit = False
    total_sheet_count = sum(
        len({
            _clean_text(row.get("_sheet")) or "Sheet1"
            for row in parsed_file.rows
        })
        for parsed_file in parsed_files
    )
    processed_sheet_count = 0

    try:
        if runtime_source:
            logs.append(f"导入解析引擎：{runtime_source}")
            _emit_progress(
                progress_callback,
                stage="runtime",
                message=f"已切换到解析引擎：{runtime_source}",
                percent=4,
            )
        try:
            if remaining_existing_prechecks > 0:
                existing_client = VeopsCmdbClient.from_skill_env()
                existing_client.login()
                logs.append(
                    f"已连接 CMDB，预览阶段最多预检查 {remaining_existing_prechecks} 条资源是否已存在"
                )
                _emit_progress(
                    progress_callback,
                    stage="cmdb_precheck",
                    message=f"已连接 CMDB，预览阶段将抽样预检查 {remaining_existing_prechecks} 条资源",
                    percent=10,
                )
            else:
                logs.append("预览阶段已关闭存量校验，最终导入时会再次检查资源是否已存在")
        except Exception as exc:  # noqa: BLE001
            existing_client = None
            logs.append(f"CMDB 预检查不可用，将跳过存量校验：{exc}")
            _emit_progress(
                progress_callback,
                stage="cmdb_precheck",
                message=f"CMDB 预检查不可用，稍后导入前会再次校验：{exc}",
                percent=10,
            )

        for parsed_file in parsed_files:
            warnings.extend(parsed_file.warnings)
            logs.extend(parsed_file.logs)

            rows_by_sheet: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
            for row_index, row in enumerate(parsed_file.rows, start=1):
                rows_by_sheet[_clean_text(row.get("_sheet")) or "Sheet1"].append((row_index, row))

            for sheet_name, sheet_rows in rows_by_sheet.items():
                processed_sheet_count += 1
                llm_target = "将调用 LLM 做字段语义映射"
                if not managed_llm_client:
                    llm_target = "当前未连接 LLM，将使用规则映射兜底"
                _emit_progress(
                    progress_callback,
                    stage="sheet_mapping",
                    message=(
                        f"正在解析 {parsed_file.filename} / {sheet_name} "
                        f"({processed_sheet_count}/{max(total_sheet_count, 1)})，{llm_target}"
                    ),
                    percent=12 + int((processed_sheet_count - 1) / max(total_sheet_count, 1) * 60),
                )
                plan, mapping_mode = await _resolve_sheet_mapping_plan(
                    sheet_name=sheet_name,
                    rows=[row for _, row in sheet_rows],
                    alias_index=alias_index,
                    model_templates=model_templates,
                    llm_client=managed_llm_client,
                )
                logs.append(f"{parsed_file.filename} / {sheet_name}: {mapping_mode}")
                _emit_progress(
                    progress_callback,
                    stage="sheet_mapping",
                    message=f"{parsed_file.filename} / {sheet_name}: {mapping_mode}",
                    percent=12 + int(processed_sheet_count / max(total_sheet_count, 1) * 60),
                )

                if plan.sheet_kind == "note":
                    skipped_rows += len(sheet_rows)
                    logs.append(f"{parsed_file.filename} / {sheet_name}: 识别为说明页，已跳过 {len(sheet_rows)} 行")
                    continue

                if plan.sheet_kind == "relation":
                    relation_row_count = 0
                    for row_index, row in sheet_rows:
                        standardized_relation: dict[str, Any] = {}
                        for raw_key, raw_value in row.items():
                            if raw_key == "_sheet":
                                continue
                            mapped_field, _confidence = plan.mappings.get(raw_key, _match_relation_field(raw_key))
                            if mapped_field != "unknown" and mapped_field in RELATION_FIELD_ALIASES and not standardized_relation.get(mapped_field):
                                standardized_relation[mapped_field] = _clean_text(raw_value)

                        if not _row_has_relation_signal(standardized_relation):
                            skipped_rows += 1
                            continue

                        explicit_relation_rows.append(
                            {
                                **standardized_relation,
                                "relation_type": _normalize_relation_type(standardized_relation.get("relation_type")),
                                "filename": parsed_file.filename,
                                "sheet": sheet_name,
                                "rowIndex": row_index,
                            }
                        )
                        relation_row_count += 1
                    logs.append(f"{parsed_file.filename} / {sheet_name}: 识别为关系表，提取 {relation_row_count} 条关系候选")
                    continue

                for row_index, row in sheet_rows:
                    standardized: dict[str, Any] = {}
                    mapping_preview: list[dict[str, Any]] = []
                    for raw_key, raw_value in row.items():
                        if raw_key == "_sheet":
                            continue
                        mapped_field, confidence = plan.mappings.get(raw_key, _match_field(raw_key))
                        if mapped_field != "unknown":
                            field_stats[(raw_key, mapped_field)] += 1
                        mapping_preview.append(
                            {
                                "sourceField": raw_key,
                                "targetField": mapped_field,
                                "confidence": confidence,
                            }
                        )
                        if mapped_field != "unknown" and not standardized.get(mapped_field):
                            standardized[mapped_field] = _clean_text(raw_value)
                        if mapped_field == "ci_type" and not standardized.get("_raw_ci_type_value"):
                            standardized["_raw_ci_type_value"] = _clean_text(raw_value)

                    if not _row_has_resource_signal(standardized):
                        skipped_rows += 1
                        continue

                    normalized_ip, ip_changed = _normalize_ip(standardized.get("private_ip", ""))
                    if ip_changed:
                        cleaning_changes["IP地址标准化"] += 1
                    if normalized_ip:
                        standardized["private_ip"] = normalized_ip

                    normalized_status = _normalize_status(standardized.get("status", ""))
                    if normalized_status and normalized_status != _clean_text(standardized.get("status", "")):
                        cleaning_changes["状态标准化"] += 1
                    standardized["status"] = normalized_status

                    normalized_port, port_changed, port_ambiguous = _normalize_service_port(standardized.get("service_port", ""))
                    if port_changed:
                        cleaning_changes["端口标准化"] += 1
                    if normalized_port:
                        standardized["service_port"] = normalized_port
                    elif port_ambiguous:
                        standardized["service_port"] = ""
                        warnings.append(
                            f"{parsed_file.filename} / {sheet_name} 第 {row_index} 行端口值存在多个候选，已标记为待确认。"
                        )

                    raw_type = _clean_text(standardized.get("ci_type"))
                    normalized_type = _normalize_ci_type(raw_type, alias_index)
                    if normalized_type and normalized_type != raw_type:
                        cleaning_changes["类型标准化"] += 1
                    if not normalized_type and plan.default_ci_type:
                        normalized_type = plan.default_ci_type
                    standardized["ci_type"] = normalized_type
                    if normalized_type == "networkdevice" and not _clean_text(standardized.get("dev_class")):
                        raw_ci_type_value = _clean_text(standardized.get("_raw_ci_type_value"))
                        if raw_ci_type_value and raw_ci_type_value.lower() != "networkdevice":
                            standardized["dev_class"] = raw_ci_type_value

                    if not standardized["ci_type"]:
                        warnings.append(f"{parsed_file.filename} / {sheet_name} 第 {row_index} 行未识别到资源类型，请在确认步骤手动选择。")

                    type_template = type_template_map.get(standardized["ci_type"] or "")
                    preview_attributes = _build_preview_attributes(standardized, type_template)
                    display_name = _resolve_record_display_name(preview_attributes, type_template)
                    if not display_name:
                        warnings.append(f"{parsed_file.filename} / {sheet_name} 第 {row_index} 行缺少资源名称/唯一标识，请在确认步骤手动补齐。")

                    cmdb_attributes = _build_cmdb_attributes(
                        ci_type=standardized["ci_type"] or "unknown",
                        canonical_attributes=preview_attributes,
                        type_template=type_template,
                    )
                    existing_ci = None
                    if existing_client and remaining_existing_prechecks > 0:
                        existing_ci = _find_existing_ci(
                            existing_client,
                            standardized["ci_type"] or "unknown",
                            cmdb_attributes,
                            fallback_name=display_name,
                            unique_key=_clean_text((type_template or {}).get("unique_key")),
                        )
                        remaining_existing_prechecks -= 1
                    elif existing_client and not precheck_limit_hit:
                        precheck_limit_hit = True
                        logs.append(
                            "预览资源较多，已跳过剩余存量校验；提交导入时会再次精确检查是否已存在。"
                        )
                        _emit_progress(
                            progress_callback,
                            stage="cmdb_precheck",
                            message="资源量较大，剩余存量校验已延后到正式导入阶段执行。",
                            percent=74,
                        )
                    if existing_ci:
                        existing_detected_count += 1

                    record_issues = _build_record_issues(
                        ci_type=standardized["ci_type"] or "unknown",
                        attributes=standardized,
                        mapping_preview=mapping_preview,
                        existing_ci=existing_ci,
                        type_template=type_template,
                    )

                    preview_key = _build_preview_key(parsed_file, sheet_name, row_index)
                    attributes = {
                        key: _clean_text(value)
                        for key, value in preview_attributes.items()
                        if key
                    }

                    raw_resources.append(
                        {
                            "previewKey": preview_key,
                            "name": display_name,
                            "ciType": standardized["ci_type"] or "unknown",
                            "status": standardized.get("status", ""),
                            "attributes": attributes,
                            "analysisAttributes": standardized,
                            "mapping": mapping_preview,
                            "sourceRows": [
                                {
                                    "filename": parsed_file.filename,
                                    "sheet": sheet_name,
                                    "rowIndex": row_index,
                                }
                            ],
                            "selected": True,
                            "generated": False,
                            "category": "resource",
                            "importAction": "update" if existing_ci else "create",
                            "existingCi": existing_ci,
                            "issues": record_issues,
                            "attentionFields": [
                                _clean_text(item.get("field"))
                                for item in record_issues
                                if _clean_text(item.get("field"))
                            ],
                        }
                    )

                    confirmation_issues = _collect_confirmation_issues(
                        standardized["ci_type"] or "unknown",
                        standardized,
                    )
                    if confirmation_issues:
                        warnings.append(
                            f"{parsed_file.filename} / {sheet_name} 第 {row_index} 行仍需人工确认：{', '.join(confirmation_issues)}。"
                        )

        relations: dict[tuple[str, str, str], dict[str, Any]] = {}
        _emit_progress(
            progress_callback,
            stage="relation_inference",
            message="正在推断资源关系与拓扑连接",
            percent=82,
        )
        _infer_parent_field_relations(raw_resources, relations, type_template_map)
        warnings.extend(
            _infer_explicit_relation_rows(
                explicit_relation_rows,
                raw_resources,
                relations,
                type_template_map,
            )
        )
        _infer_existing_resource_relations(raw_resources, relations, type_template_map)
        allowed_relation_rules = _build_allowed_relation_rules(
            existing_client,
            type_template_map,
            {str(item.get("ciType") or "") for item in raw_resources if item.get("ciType")},
        )
        relations = _prune_redundant_root_relations(relations, raw_resources)
        relations, skipped_relation_messages = _filter_supported_relations(relations, raw_resources, allowed_relation_rules)
        logs.extend(skipped_relation_messages)
        preview_pending_choice_values = _collect_pending_choice_values(
            type_templates=type_template_map,
            ordered_records=raw_resources,
        )
        for item in raw_resources:
            type_template = type_template_map.get(_clean_text(item.get("ciType")))
            record_issues = _build_record_issues(
                ci_type=_clean_text(item.get("ciType")) or "unknown",
                attributes=item.get("analysisAttributes") or {},
                mapping_preview=item.get("mapping") or [],
                existing_ci=item.get("existingCi"),
                type_template=type_template,
                pending_choice_values=preview_pending_choice_values,
            )
            item["issues"] = record_issues
            item["attentionFields"] = [
                _clean_text(issue.get("field"))
                for issue in record_issues
                if _clean_text(issue.get("field"))
            ]
        resource_type_map = {
            str(item.get("previewKey")): _clean_text(item.get("ciType"))
            for item in raw_resources
            if item.get("previewKey")
        }
        resource_name_map = {
            str(item.get("previewKey")): _clean_text(item.get("name"))
            for item in raw_resources
            if item.get("previewKey")
        }

        grouped_resources: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in raw_resources:
            grouped_resources[item["ciType"]].append(item)

        _emit_progress(
            progress_callback,
            stage="structure_analysis",
            message="正在生成待确认的数据结构和模型归属建议",
            percent=91,
        )
        resource_groups = [
            {
                "ciType": ci_type,
                "label": _resolve_type_label(ci_type, model_templates),
                "count": len(items),
                "records": sorted(items, key=lambda item: (item["name"] == "", item["name"], item["previewKey"])),
            }
            for ci_type, items in sorted(grouped_resources.items(), key=lambda item: (-len(item[1]), item[0]))
        ]
        structure_analysis = _build_structure_analysis(resource_groups, metadata)

        unknown_count = sum(1 for item in raw_resources if item["ciType"] == "unknown")
        attention_record_count = sum(
            1 for item in raw_resources if (item.get("issues") or [])
        )
        quality_penalty = unknown_count * 7 + len(warnings) * 2
        quality_score = max(48, min(100, 96 - quality_penalty))
        mapping_summary = [
            {
                "sourceField": source_field,
                "targetField": target_field,
                "count": count,
                "confidence": "high" if target_field != "unknown" else "low",
            }
            for (source_field, target_field), count in sorted(field_stats.items(), key=lambda item: (-item[1], item[0][0]))
        ]
        cleaning_summary = [
            {"label": label, "count": count}
            for label, count in cleaning_changes.items()
        ]
        if skipped_rows:
            cleaning_summary.append({"label": "已过滤非资产行", "count": skipped_rows})
        if existing_detected_count:
            cleaning_summary.append({"label": "检测到 CMDB 已存在资源", "count": existing_detected_count})
        if explicit_relation_rows:
            cleaning_summary.append({"label": "识别到显式关系行", "count": len(explicit_relation_rows)})

        _emit_progress(
            progress_callback,
            stage="finalizing",
            message="解析完成，正在整理预览结果",
            percent=98,
        )
        return {
            "summary": {
                "fileCount": len(parsed_files),
                "rawRowCount": raw_row_total,
                "resourceCount": len(raw_resources),
                "relationCount": len(relations),
                "qualityScore": quality_score,
                "autoCleaned": sum(cleaning_changes.values()),
                "needsConfirmation": max(attention_record_count, unknown_count) + len(warnings),
            },
            "mappingSummary": mapping_summary,
            "cleaningSummary": cleaning_summary,
            "resourceGroups": resource_groups,
            "relations": [
                {
                    **relation,
                    "sourceType": resource_type_map.get(str(relation.get("sourceKey") or ""), ""),
                    "targetType": resource_type_map.get(str(relation.get("targetKey") or ""), ""),
                    "sourceName": resource_name_map.get(str(relation.get("sourceKey") or ""), ""),
                    "targetName": resource_name_map.get(str(relation.get("targetKey") or ""), ""),
                }
                for relation in relations.values()
            ],
            "ciTypeMetadata": {
                str(item.get("name")): item
                for item in model_templates
                if item.get("name")
            },
            "structureAnalysis": structure_analysis,
            "logs": logs,
            "warnings": warnings,
        }
    finally:
        if existing_client:
            existing_client.close()
        if managed_llm_client and managed_llm_client is not llm_client:
            await managed_llm_client.aclose()


def _resolve_type_label(ci_type: str, model_templates: list[dict[str, Any]]) -> str:
    for template in model_templates:
        if template.get("name") == ci_type:
            return str(template.get("alias") or ci_type)
    return ci_type


def _normalize_group_snapshot(group: dict[str, Any]) -> dict[str, Any]:
    ci_types: list[dict[str, Any]] = []
    for item in (group.get("ci_types") or group.get("ciTypes") or []):
        if not isinstance(item, dict):
            continue
        name = _clean_text(item.get("name"))
        if not name:
            continue
        ci_types.append(
            {
                "id": item.get("id"),
                "name": name,
                "alias": _clean_text(item.get("alias")) or name,
            }
        )
    return {
        "id": group.get("id"),
        "name": _clean_text(group.get("name")),
        "ciTypes": ci_types,
    }


def _build_default_ci_type_groups(model_templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in model_templates:
        name = _clean_text(item.get("name"))
        if not name:
            continue
        group_name = DEFAULT_GROUP_HINTS.get(name, "未分组")
        grouped[group_name].append(
            {
                "id": item.get("id"),
                "name": name,
                "alias": _clean_text(item.get("alias")) or name,
            }
        )
    return [
        {"id": None, "name": group_name, "ciTypes": sorted(ci_types, key=lambda ci: ci["name"])}
        for group_name, ci_types in sorted(grouped.items(), key=lambda item: item[0])
    ]


def _find_groups_for_model(ci_type_groups: list[dict[str, Any]], ci_type: str) -> list[dict[str, Any]]:
    target = _clean_text(ci_type)
    if not target:
        return []
    matched: list[dict[str, Any]] = []
    for group in ci_type_groups:
        for item in group.get("ciTypes") or []:
            if _clean_text(item.get("name")) == target:
                matched.append(group)
                break
    return matched


def _collect_raw_type_hints(records: list[dict[str, Any]]) -> list[str]:
    hints: list[str] = []
    for record in records:
        analysis_attributes = record.get("analysisAttributes") or {}
        raw_hint = _clean_text(analysis_attributes.get("_raw_ci_type_value"))
        if raw_hint and raw_hint not in hints:
            hints.append(raw_hint)
    return hints


def _is_generic_server_hint(raw_hints: list[str]) -> bool:
    for hint in raw_hints:
        lowered = _clean_text(hint).lower()
        if any(token in lowered for token in ("server", "服务器", "主机")):
            return True
    return False


def _build_structure_analysis(
    resource_groups: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    ci_type_groups = [
        _normalize_group_snapshot(item)
        for item in (metadata.get("ciTypeGroups") or [])
        if isinstance(item, dict)
    ]
    if not ci_type_groups:
        ci_type_groups = _build_default_ci_type_groups(metadata.get("ciTypes") or DEFAULT_MODEL_TEMPLATES)

    ci_type_meta = {
        _clean_text(item.get("name")): item
        for item in (metadata.get("ciTypes") or [])
        if isinstance(item, dict) and _clean_text(item.get("name"))
    }

    items: list[dict[str, Any]] = []
    for group in resource_groups:
        resource_ci_type = _clean_text(group.get("ciType"))
        records = group.get("records") or []
        raw_type_hints = _collect_raw_type_hints(records)
        exact_groups = _find_groups_for_model(ci_type_groups, resource_ci_type)
        suggested_group_name = DEFAULT_GROUP_HINTS.get(resource_ci_type, "")
        status = "matched"
        reason = ""
        selected_group_name = ""
        selected_model_name = resource_ci_type
        create_group_approved = False
        create_model_approved = False
        needs_confirmation = False
        group_options = [
            {
                "id": item.get("id"),
                "name": _clean_text(item.get("name")),
                "existing": True,
            }
            for item in exact_groups
            if _clean_text(item.get("name"))
        ]
        model_options: list[dict[str, Any]] = []

        if resource_ci_type == "unknown":
            status = "unknown"
            reason = "当前资源尚未识别出可用模型，请先确认模型归属。"
            needs_confirmation = True
        elif exact_groups:
            selected_group_name = _clean_text(exact_groups[0].get("name"))
            for model in (exact_groups[0].get("ciTypes") or []):
                if _clean_text(model.get("name")) == resource_ci_type:
                    model_options = [
                        {
                            "id": model.get("id"),
                            "name": _clean_text(model.get("name")),
                            "alias": _clean_text(model.get("alias")),
                            "groupName": selected_group_name,
                            "existing": True,
                        }
                    ]
                    break
            reason = f"已在现有分组 {selected_group_name} 中找到模型 {resource_ci_type}。"
            if (
                resource_ci_type in {"PhysicalMachine", "vserver"}
                and _is_generic_server_hint(raw_type_hints)
                and {"PhysicalMachine", "vserver"}.issubset(
                    {_clean_text(item.get("name")) for item in (exact_groups[0].get("ciTypes") or [])}
                )
            ):
                status = "ambiguous_model"
                needs_confirmation = True
                model_options = [
                    {
                        "id": model.get("id"),
                        "name": _clean_text(model.get("name")),
                        "alias": _clean_text(model.get("alias")),
                        "groupName": selected_group_name,
                        "existing": True,
                    }
                    for model in (exact_groups[0].get("ciTypes") or [])
                    if _clean_text(model.get("name")) in {"PhysicalMachine", "vserver"}
                ]
                reason = (
                    "源数据只表达了“服务器/主机”这一类通用语义，"
                    "当前系统同时存在 PhysicalMachine 和 vserver，需要人工确认最终模型。"
                )
        else:
            hinted_group = next(
                (
                    item for item in ci_type_groups
                    if _clean_text(item.get("name")) == suggested_group_name
                ),
                None,
            )
            if hinted_group:
                status = "missing_model"
                selected_group_name = _clean_text(hinted_group.get("name"))
                needs_confirmation = True
                reason = f"建议归入现有分组 {selected_group_name}，但未找到可直接复用的模型 {resource_ci_type}。"
                group_options = [
                    {
                        "id": hinted_group.get("id"),
                        "name": selected_group_name,
                        "existing": True,
                    }
                ]
            else:
                status = "missing_group"
                selected_group_name = suggested_group_name or _clean_text(group.get("label"))
                needs_confirmation = True
                reason = (
                    f"建议为当前资源创建分组 {selected_group_name}。"
                    if selected_group_name
                    else "当前资源未匹配到合适分组，需要人工确认是否新建分组。"
                )

        if not selected_model_name:
            selected_model_name = resource_ci_type or _clean_text(group.get("label"))
        if status == "missing_model":
            model_meta = ci_type_meta.get(resource_ci_type) or {}
            selected_model_name = resource_ci_type or _clean_text(model_meta.get("alias")) or _clean_text(group.get("label"))
        if status == "missing_group":
            create_group_approved = False
        if status == "missing_model":
            create_model_approved = False

        items.append(
            {
                "key": resource_ci_type or _clean_text(group.get("label")) or f"group-{len(items) + 1}",
                "resourceCiType": resource_ci_type,
                "resourceLabel": _clean_text(group.get("label")) or resource_ci_type or "待确认模型",
                "recordCount": int(group.get("count") or len(records)),
                "status": status,
                "reason": reason,
                "rawTypeHints": raw_type_hints,
                "suggestedGroupName": selected_group_name,
                "suggestedModelName": selected_model_name,
                "selectedGroupName": selected_group_name,
                "selectedModelName": selected_model_name,
                "createGroupApproved": create_group_approved,
                "createModelApproved": create_model_approved,
                "needsConfirmation": needs_confirmation,
                "groupOptions": group_options,
                "modelOptions": model_options,
            }
        )

    return {"items": items}


def _extract_choice_definitions(attribute: dict[str, Any]) -> list[dict[str, str]]:
    choices: list[dict[str, str]] = []
    for choice in (attribute.get("choice_value") or []):
        if not isinstance(choice, (list, tuple)) or not choice:
            continue
        raw_value = _clean_text(choice[0])
        raw_meta = choice[1] if len(choice) > 1 and isinstance(choice[1], dict) else {}
        raw_label = _clean_text(raw_meta.get("label")) or raw_value
        if raw_value:
            choices.append({"value": raw_value, "label": raw_label})
    return choices


def _extract_choice_reference_definition(attribute: dict[str, Any]) -> tuple[Any, list[Any]]:
    choice_other = attribute.get("choice_other")
    if not isinstance(choice_other, dict):
        return None, []

    attr_id = choice_other.get("attr_id")
    if attr_id in (None, ""):
        attr_id = choice_other.get("id")

    raw_type_ids = choice_other.get("type_ids")
    if raw_type_ids in (None, ""):
        raw_type_ids = choice_other.get("type_id")

    normalized_type_ids: list[Any] = []
    if isinstance(raw_type_ids, list):
        normalized_type_ids = [item for item in raw_type_ids if item not in (None, "")]
    elif raw_type_ids not in (None, ""):
        normalized_type_ids = [raw_type_ids]

    return attr_id, normalized_type_ids


def _attribute_names_from_ids(
    attributes: list[dict[str, Any]] | None,
    attr_ids: list[Any] | None,
) -> list[str]:
    if not attributes or not attr_ids:
        return []
    wanted = {int(item) for item in attr_ids if str(item).strip().isdigit()}
    names: list[str] = []
    for attr in attributes:
        attr_id = attr.get("id")
        try:
            normalized_id = int(attr_id)
        except Exception:
            continue
        if normalized_id not in wanted:
            continue
        name = _clean_text(attr.get("name"))
        if name and name not in names:
            names.append(name)
    return names


def _merge_attribute_definitions(
    attributes: list[dict[str, Any]],
    preference_attributes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}
    preferred_order = {
        _clean_text(item.get("name")): index
        for index, item in enumerate(preference_attributes)
        if _clean_text(item.get("name"))
    }

    for index, attr in enumerate(attributes):
        name = _clean_text(attr.get("name"))
        if not name:
            continue
        choice_reference_attr_id, choice_reference_type_ids = _extract_choice_reference_definition(attr)
        definitions[name] = {
            "id": attr.get("id"),
            "name": name,
            "alias": _clean_text(attr.get("alias")) or name,
            "required": bool(attr.get("is_required")),
            "is_choice": bool(attr.get("is_choice")),
            "is_list": bool(attr.get("is_list")),
            "default_show": bool(attr.get("default_show")) or name in preferred_order,
            "value_type": _clean_text(attr.get("value_type")),
            "order": preferred_order.get(name, int(attr.get("order") or index)),
            "choices": _extract_choice_definitions(attr),
            "choice_reference_attr_id": choice_reference_attr_id,
            "choice_reference_type_ids": choice_reference_type_ids,
        }

    for index, attr in enumerate(preference_attributes):
        name = _clean_text(attr.get("name"))
        if not name:
            continue
        choice_reference_attr_id, choice_reference_type_ids = _extract_choice_reference_definition(attr)
        definitions.setdefault(
            name,
            {
                "id": attr.get("id"),
                "name": name,
                "alias": _clean_text(attr.get("alias")) or name,
                "required": False,
                "is_choice": bool(attr.get("is_choice")),
                "is_list": bool(attr.get("is_list")),
                "default_show": True,
                "value_type": _clean_text(attr.get("value_type")),
                "order": preferred_order.get(name, index),
                "choices": _extract_choice_definitions(attr),
                "choice_reference_attr_id": choice_reference_attr_id,
                "choice_reference_type_ids": choice_reference_type_ids,
            },
        )
        definitions[name]["default_show"] = True
        definitions[name]["order"] = preferred_order.get(name, definitions[name].get("order", index))
        if not definitions[name].get("choices"):
            definitions[name]["choices"] = _extract_choice_definitions(attr)
        if not definitions[name].get("choice_reference_attr_id") and choice_reference_attr_id not in (None, ""):
            definitions[name]["choice_reference_attr_id"] = choice_reference_attr_id
        if not definitions[name].get("choice_reference_type_ids") and choice_reference_type_ids:
            definitions[name]["choice_reference_type_ids"] = choice_reference_type_ids

    return sorted(
        definitions.values(),
        key=lambda item: (int(item.get("order", 0)), str(item.get("alias") or item.get("name") or "")),
    )


def load_resource_import_metadata() -> dict[str, Any]:
    metadata = {
        "supportedFormats": DEFAULT_SUPPORTED_FORMATS,
        "ciTypes": DEFAULT_MODEL_TEMPLATES,
        "ciTypeGroups": _build_default_ci_type_groups(DEFAULT_MODEL_TEMPLATES),
        "attributeLibrary": [],
        "relationTypes": DEFAULT_RELATION_TYPES,
        "connected": False,
        "message": "使用默认 CMDB 模板",
    }
    client: VeopsCmdbClient | None = None
    try:
        client = VeopsCmdbClient.from_skill_env()
        client.login()
        ci_types = client.get_ci_types()
        ci_type_groups = client.get_ci_type_groups()
        relation_types = client.get_relation_types()
        attribute_library = client.get_attribute_library()
        attributes_map: dict[str, list[str]] = {}
        attribute_definitions_map: dict[str, list[dict[str, Any]]] = {}
        parent_type_map: dict[str, list[dict[str, Any]]] = {}
        for item in ci_types:
            type_id = item.get("id")
            name = str(item.get("name") or "")
            if not type_id or not name:
                continue
            try:
                attributes = client.get_ci_type_attributes(type_id)
                preference_attributes = client.get_ci_type_preference_attributes(type_id)
                attribute_definitions_map[name] = _merge_attribute_definitions(attributes, preference_attributes)
                attributes_map[name] = [str(attr.get("name")) for attr in attribute_definitions_map[name] if attr.get("name")]
                child_attr_names_by_id = _attribute_names_from_ids(attributes, [item.get("id") for item in attributes])
                parent_type_map[name] = [
                    {
                        "name": _clean_text(parent.get("name")),
                        "alias": _clean_text(parent.get("alias")) or _clean_text(parent.get("name")),
                        "relationType": _clean_text(parent.get("relation_type")),
                        "showKey": _clean_text(parent.get("show_key")) or "name",
                        "parentAttrNames": _attribute_names_from_ids(
                            parent.get("attributes") or [],
                            parent.get("parent_attr_ids") or [],
                        ),
                        "childAttrNames": [
                            child_name
                            for child_name in _attribute_names_from_ids(
                                attributes,
                                parent.get("child_attr_ids") or [],
                            )
                            if child_name in child_attr_names_by_id
                        ],
                    }
                    for parent in client.get_ci_type_parent_relations(type_id)
                    if _clean_text(parent.get("name"))
                ]
            except Exception:
                attribute_definitions_map[name] = []
                attributes_map[name] = DEFAULT_ATTRIBUTE_FIELDS.get(name, ["name"])
                parent_type_map[name] = []
        metadata.update(
            {
                "ciTypes": [
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "alias": item.get("alias"),
                        "unique_key": item.get("unique_key"),
                        "attributes": attributes_map.get(str(item.get("name") or ""), ["name"]),
                        "attributeDefinitions": attribute_definitions_map.get(str(item.get("name") or ""), []),
                        "parentTypes": parent_type_map.get(str(item.get("name") or ""), []),
                    }
                    for item in ci_types
                ],
                "ciTypeGroups": [
                    _normalize_group_snapshot(item)
                    for item in ci_type_groups
                    if isinstance(item, dict) and _clean_text(item.get("name"))
                ] or _build_default_ci_type_groups(ci_types),
                "attributeLibrary": [
                    {
                        "id": item.get("id"),
                        "name": _clean_text(item.get("name")),
                        "alias": _clean_text(item.get("alias")) or _clean_text(item.get("name")),
                        "value_type": _clean_text(item.get("value_type")),
                        "is_choice": bool(item.get("is_choice")),
                        "is_list": bool(item.get("is_list")),
                    }
                    for item in attribute_library
                    if _clean_text(item.get("name"))
                ],
                "relationTypes": [item.get("name") for item in relation_types if item.get("name")] or DEFAULT_RELATION_TYPES,
                "connected": True,
                "message": "已连接 CMDB，模板来自实时模型元数据",
            }
        )
    except Exception as exc:  # noqa: BLE001
        metadata["message"] = f"CMDB 元数据不可用，已降级为默认模板：{exc}"
    finally:
        if client:
            client.close()
    return metadata


def import_preview_to_cmdb(payload: dict[str, Any]) -> dict[str, Any]:
    client = VeopsCmdbClient.from_skill_env()
    report = {
        "status": "success",
        "created": 0,
        "relationsCreated": 0,
        "skipped": 0,
        "failed": 0,
        "structureResults": [],
        "resourceResults": [],
        "relationResults": [],
        "rollbackResults": [],
    }
    ci_id_map: dict[str, Any] = {}
    created_ci_ids: list[Any] = []
    updated_ci_snapshots: list[dict[str, Any]] = []
    created_relation_ids: list[Any] = []
    try:
        client.login()
        report["structureResults"] = _prepare_import_structure(client, payload)
        client.get_relation_types()
        type_templates = {
            item["name"]: item
            for item in load_resource_import_metadata().get("ciTypes", [])
            if item.get("name")
        }
        resource_type_map = {
            str(record.get("previewKey")): _clean_text(record.get("ciType"))
            for group in (payload.get("resourceGroups") or [])
            for record in (group.get("records") or [])
            if record.get("previewKey")
        }
        allowed_relation_rules = _build_allowed_relation_rules(
            client,
            type_templates,
            {ci_type for ci_type in resource_type_map.values() if ci_type},
        )
        allowed_relation_rules, relation_structure_results = _ensure_selected_model_relations(
            client,
            payload,
            type_templates=type_templates,
            resource_type_map=resource_type_map,
            allowed_relation_rules=allowed_relation_rules,
        )
        report["structureResults"].extend(relation_structure_results)
        resource_groups = payload.get("resourceGroups") or []
        ordered_records = _ordered_selected_records(resource_groups, payload.get("relations") or [])
        pending_choice_values = _collect_pending_choice_values(
            type_templates=type_templates,
            ordered_records=ordered_records,
        )
        preflight_results = _preflight_import_resources(
            client,
            type_templates=type_templates,
            ordered_records=ordered_records,
        )
        if preflight_results:
            report["failed"] += len(preflight_results)
            report["resourceResults"].extend(preflight_results)
            report["status"] = "failed"
            report["error"] = "原子导入预检失败，未写入任何资源"
            return report

        for group in resource_groups:
            for record in group.get("records", []) or []:
                if not record.get("selected", True):
                    report["skipped"] += 1

        for record in ordered_records:
            import_action = _clean_text(record.get("importAction")) or "create"
            existing_ci = record.get("existingCi") or {}
            ci_type = str(record.get("ciType") or "").strip()
            type_template = type_templates.get(ci_type, {})
            attributes = {
                key: value
                for key, value in (record.get("attributes") or {}).items()
                if _clean_text(value)
            }
            display_name = _clean_text(record.get("name")) or _resolve_record_display_name(attributes, type_template)
            if display_name and not _resolve_record_display_name(attributes, type_template):
                fallback_field = _resolve_cmdb_attribute_name(type_template, "name")
                if fallback_field and _find_attribute_definition(type_template, fallback_field):
                    attributes[fallback_field] = display_name

            cmdb_attributes = _build_cmdb_attributes(
                ci_type=ci_type,
                canonical_attributes=attributes,
                type_template=type_template,
                pending_choice_values=pending_choice_values,
            )
            unique_key = _clean_text(type_template.get("unique_key"))
            current_existing_ci = _find_existing_ci(
                client,
                ci_type,
                cmdb_attributes,
                fallback_name=display_name,
                unique_key=unique_key,
            ) or existing_ci

            if current_existing_ci and import_action == "skip":
                ci_id_map[str(record.get("previewKey"))] = current_existing_ci.get("ciId")
                report["skipped"] += 1
                report["resourceResults"].append(
                    {
                        "previewKey": record.get("previewKey"),
                        "ciId": current_existing_ci.get("ciId"),
                        "status": "skipped",
                        "message": "CMDB 中已存在，已按选择跳过更新",
                    }
                )
                continue

            if current_existing_ci:
                existing_ci_id = current_existing_ci.get("ciId")
                if existing_ci_id is not None:
                    snapshot = client.get_ci_by_id(existing_ci_id)
                    if snapshot:
                        updated_ci_snapshots.append(
                            {
                                "ciId": existing_ci_id,
                                "ciType": ci_type,
                                "attributes": _snapshot_ci_attributes(snapshot, type_template=type_template),
                            }
                        )
                ci_id, _response = client.update_ci(
                    current_existing_ci.get("ciId"),
                    ci_type,
                    cmdb_attributes,
                )
            else:
                immediate_attributes, deferred_attributes = _split_deferred_self_referential_choice_attributes(
                    ci_type=ci_type,
                    type_template=type_template,
                    source_attributes=attributes,
                    cmdb_attributes=cmdb_attributes,
                )
                ci_id, _response = client.create_ci(
                    ci_type,
                    immediate_attributes,
                    exist_policy="reject",
                    unique_key=unique_key,
                )
                if ci_id is not None:
                    created_ci_ids.append(ci_id)
                    if deferred_attributes:
                        client.update_ci(ci_id, ci_type, deferred_attributes)
            if ci_id is None:
                raise RuntimeError(f"{record.get('name')} 创建后未能解析 CI ID")
            ci_id_map[str(record.get("previewKey"))] = ci_id
            report["created"] += 1
            report["resourceResults"].append(
                {
                    "previewKey": record.get("previewKey"),
                    "ciId": ci_id,
                    "status": "success",
                    "message": "更新成功" if current_existing_ci else "导入成功",
                }
            )

        for relation in payload.get("relations") or []:
            if not relation.get("selected", True):
                report["skipped"] += 1
                continue
            source_type = resource_type_map.get(str(relation.get("sourceKey")), "")
            target_type = resource_type_map.get(str(relation.get("targetKey")), "")
            relation_type = _clean_text(relation.get("relationType")) or "contain"
            if allowed_relation_rules and (source_type, relation_type, target_type) not in allowed_relation_rules:
                report["skipped"] += 1
                report["relationResults"].append(
                    {
                        "sourceKey": relation.get("sourceKey"),
                        "targetKey": relation.get("targetKey"),
                        "status": "skipped",
                        "message": f"CMDB 未配置关系：{source_type} -> {relation_type} -> {target_type}",
                    }
                )
                continue
            source_ci_id = ci_id_map.get(str(relation.get("sourceKey")))
            target_ci_id = ci_id_map.get(str(relation.get("targetKey")))
            if not source_ci_id or not target_ci_id:
                report["relationResults"].append(
                    {
                        "sourceKey": relation.get("sourceKey"),
                        "targetKey": relation.get("targetKey"),
                        "status": "skipped",
                        "message": "关联资源未全部成功导入，已跳过关系创建",
                    }
                )
                continue
            try:
                relation_id, _response = client.create_relation(source_ci_id, target_ci_id, relation_type)
                if relation_id is not None:
                    created_relation_ids.append(relation_id)
                report["relationsCreated"] += 1
                report["relationResults"].append(
                    {
                        "sourceKey": relation.get("sourceKey"),
                        "targetKey": relation.get("targetKey"),
                        "status": "success",
                        "message": "关系创建成功",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                report["failed"] += 1
                report["relationResults"].append(
                    {
                        "sourceKey": relation.get("sourceKey"),
                        "targetKey": relation.get("targetKey"),
                        "status": "failed",
                        "message": str(exc),
                    }
                )
        if report["failed"]:
            report["status"] = "partial" if (report["created"] or report["relationsCreated"]) else "failed"
    except Exception as exc:  # noqa: BLE001
        rollback_errors: list[str] = []
        for relation_id in reversed(created_relation_ids):
            try:
                client.delete_relation(relation_id)
                report["rollbackResults"].append(
                    {"kind": "relation", "id": relation_id, "status": "rolled_back", "message": "已回滚本次创建的关系"}
                )
            except Exception as rollback_exc:  # noqa: BLE001
                rollback_errors.append(f"回滚关系 {relation_id} 失败: {rollback_exc}")
        for ci_id in reversed(created_ci_ids):
            try:
                client.delete_ci(ci_id)
                report["rollbackResults"].append(
                    {"kind": "ci", "id": ci_id, "status": "rolled_back", "message": "已回滚本次创建的资源"}
                )
            except Exception as rollback_exc:  # noqa: BLE001
                rollback_errors.append(f"回滚资源 {ci_id} 失败: {rollback_exc}")
        for snapshot in reversed(updated_ci_snapshots):
            try:
                client.update_ci(snapshot.get("ciId"), snapshot.get("ciType") or "", snapshot.get("attributes") or {})
                report["rollbackResults"].append(
                    {"kind": "ci-update", "id": snapshot.get("ciId"), "status": "rolled_back", "message": "已回滚本次更新的资源"}
                )
            except Exception as rollback_exc:  # noqa: BLE001
                rollback_errors.append(f"回滚资源更新 {snapshot.get('ciId')} 失败: {rollback_exc}")
        report["status"] = "failed"
        report["error"] = str(exc)
        if rollback_errors:
            report["error"] += "；回滚存在异常：" + "；".join(rollback_errors)
        elif created_ci_ids or created_relation_ids or updated_ci_snapshots:
            report["error"] += "；已自动回滚本次已写入的数据"
    finally:
        client.close()
    return report
