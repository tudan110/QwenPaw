#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
import json
import os
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

try:
    from dotenv import load_dotenv

    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False


def _load_skill_env() -> None:
    if not HAS_DOTENV:
        return
    skill_dir = Path(__file__).resolve().parents[1]
    env_file = skill_dir / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=True)


_load_skill_env()


@dataclass(slots=True)
class OrderWorkflowConfig:
    base_url: str
    authorization: str
    cookie: str = ""
    serial_no: str = ""
    timeout_seconds: int = 20
    verify_ssl: bool = True
    enable_curl_fallback: bool = False
    extra_headers: dict[str, str] | None = None

    @classmethod
    def from_env(cls) -> "OrderWorkflowConfig":
        base_url = (
            os.getenv("ORDER_API_BASE_URL", "").strip()
            or os.getenv("INOE_API_BASE_URL", "").strip()
            or "http://192.168.130.51:30081"
        )
        authorization = (
            os.getenv("ORDER_AUTHORIZATION", "").strip()
            or os.getenv("INOE_API_TOKEN", "").strip()
        )
        cookie = os.getenv("ORDER_COOKIE", "").strip()
        serial_no = os.getenv("ORDER_SERIAL_NO", "").strip()
        timeout_seconds = int(os.getenv("ORDER_TIMEOUT_SECONDS", "20").strip() or "20")
        verify_ssl = os.getenv("ORDER_VERIFY_SSL", "true").strip().lower() not in {
            "0",
            "false",
            "no",
        }
        enable_curl_fallback = os.getenv(
            "ORDER_ENABLE_CURL_FALLBACK",
            "false",
        ).strip().lower() in {"1", "true", "yes"}

        extra_headers: dict[str, str] | None = None
        raw_extra_headers = os.getenv("ORDER_EXTRA_HEADERS", "").strip()
        if raw_extra_headers:
            parsed = json.loads(raw_extra_headers)
            if isinstance(parsed, dict):
                extra_headers = {
                    str(key): str(value)
                    for key, value in parsed.items()
                    if value is not None
                }

        return cls(
            base_url=base_url.rstrip("/"),
            authorization=authorization,
            cookie=cookie,
            serial_no=serial_no,
            timeout_seconds=timeout_seconds,
            verify_ssl=verify_ssl,
            enable_curl_fallback=enable_curl_fallback,
            extra_headers=extra_headers,
        )


class OrderWorkflowClient:
    DEFAULT_BATCH_SIZE = 100

    def __init__(self, config: OrderWorkflowConfig | None = None) -> None:
        self.config = config or OrderWorkflowConfig.from_env()

    def get_workorder_stats(self) -> dict[str, Any]:
        return self._request(
            "GET",
            "/flowable/workflow/workOrder/getWorkOrder",
        )

    def create_disposal_workorder(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized_payload = self._normalize_create_payload(payload)
        return self._request(
            "POST",
            "/flowable/workflow/workOrder/faultManualWorkorders",
            json_body=normalized_payload,
        )

    def list_todo_workorders(
        self,
        *,
        page_num: int = 1,
        page_size: int = 10,
        begin_time: str = "",
        end_time: str = "",
        fetch_all: bool = False,
    ) -> dict[str, Any]:
        return self._list_workorders(
            "/flowable/workflow/process/todoList",
            page_num=page_num,
            page_size=page_size,
            begin_time=begin_time,
            end_time=end_time,
            fetch_all=fetch_all,
        )

    def list_finished_workorders(
        self,
        *,
        page_num: int = 1,
        page_size: int = 10,
        begin_time: str = "",
        end_time: str = "",
        fetch_all: bool = False,
    ) -> dict[str, Any]:
        return self._list_workorders(
            "/flowable/workflow/process/finishedList",
            page_num=page_num,
            page_size=page_size,
            begin_time=begin_time,
            end_time=end_time,
            fetch_all=fetch_all,
        )

    def get_workorder_detail(self, *, proc_ins_id: str, task_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            "/flowable/workflow/process/detail",
            params={
                "procInsId": proc_ins_id,
                "taskId": task_id,
            },
        )

    @staticmethod
    def _build_list_params(
        *,
        page_num: int,
        page_size: int,
        begin_time: str = "",
        end_time: str = "",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "pageNum": page_num,
            "pageSize": page_size,
        }
        if begin_time:
            params["params.beginTime"] = begin_time
        if end_time:
            params["params.endTime"] = end_time
        return params

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.config.base_url:
            raise RuntimeError("ORDER_API_BASE_URL is required")
        if not self.config.authorization:
            raise RuntimeError("ORDER_AUTHORIZATION is required")

        url = f"{self.config.base_url}{path}"
        headers = self._build_headers()

        try:
            response = requests.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                headers=headers,
                timeout=self.config.timeout_seconds,
                verify=self.config.verify_ssl,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            if not self.config.enable_curl_fallback:
                raise RuntimeError(self._format_request_error(exc)) from exc
            return self._curl_request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json_body=json_body,
            )
        except ValueError as exc:
            raise RuntimeError(f"Invalid JSON response from {url}") from exc

    def _list_workorders(
        self,
        path: str,
        *,
        page_num: int,
        page_size: int,
        begin_time: str = "",
        end_time: str = "",
        fetch_all: bool = False,
    ) -> dict[str, Any]:
        effective_page_size = page_size if page_size > 0 else self.DEFAULT_BATCH_SIZE
        first_payload = self._request(
            "GET",
            path,
            params=self._build_list_params(
                page_num=page_num,
                page_size=effective_page_size,
                begin_time=begin_time,
                end_time=end_time,
            ),
        )
        if not fetch_all:
            return first_payload

        rows = list(first_payload.get("rows") or [])
        total = int(first_payload.get("total") or len(rows))
        if total <= len(rows):
            first_payload["rows"] = rows
            first_payload["fetchedAll"] = True
            return first_payload

        next_page = page_num + 1
        while len(rows) < total:
            payload = self._request(
                "GET",
                path,
                params=self._build_list_params(
                    page_num=next_page,
                    page_size=effective_page_size,
                    begin_time=begin_time,
                    end_time=end_time,
                ),
            )
            batch = list(payload.get("rows") or [])
            if not batch:
                break
            rows.extend(batch)
            next_page += 1

        first_payload["rows"] = rows[:total]
        first_payload["pageNum"] = page_num
        first_payload["pageSize"] = effective_page_size
        first_payload["fetchedAll"] = len(first_payload["rows"]) >= total
        return first_payload

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": self.config.authorization,
            "SerialNo": self.config.serial_no or self._generate_serial_no(),
        }
        if self.config.cookie:
            headers["Cookie"] = self.config.cookie
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)
        return headers

    @staticmethod
    def _generate_serial_no() -> str:
        return uuid.uuid4().hex

    @classmethod
    def _normalize_create_payload(cls, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RuntimeError("create payload must be a JSON object")

        chat_id = cls._pick_text(payload, "chatId", "sessionId", "conversationId") or str(uuid.uuid4())
        alarm = payload.get("alarm")
        analysis = payload.get("analysis")
        ticket = payload.get("ticket")
        alarm_payload = alarm if isinstance(alarm, dict) else {}
        analysis_payload = analysis if isinstance(analysis, dict) else {}
        ticket_payload = ticket if isinstance(ticket, dict) else {}

        manage_ip = cls._pick_text(
            payload,
            "manageIp",
            "deviceIp",
            "ip",
            "hostIp",
            nested=("alarm", "manageIp"),
        )
        device_name = cls._pick_text(
            payload,
            "deviceName",
            "resourceName",
            "assetName",
            "instanceName",
            "name",
            nested=("alarm", "deviceName"),
        )
        asset_id = cls._pick_text(
            payload,
            "assetId",
            "resource",
            "resourceId",
            "resId",
            nested=("alarm", "assetId"),
        )
        visible_content = cls._pick_text(
            payload,
            "visibleContent",
            "issue",
            "description",
            "alarmContent",
            nested=("alarm", "visibleContent"),
        )
        suggestions_text = cls._pick_text(
            payload,
            "suggestions",
            "advice",
            "comment",
            nested=("analysis", "summary"),
        ) or cls._join_suggestions(analysis_payload.get("suggestions"))
        title = cls._pick_text(
            payload,
            "title",
            nested=("alarm", "title"),
            nested_alt=("ticket", "title"),
        )
        metric_type = cls._pick_text(
            payload,
            "metricType",
            "resourceType",
            "ciType",
        )

        extracted_ip = cls._extract_ip(visible_content) or cls._extract_ip(suggestions_text)
        if not manage_ip and extracted_ip:
            manage_ip = extracted_ip
        if not asset_id and device_name:
            asset_id = device_name
        if not device_name and asset_id and asset_id != manage_ip:
            device_name = asset_id

        core_text = " ".join(
            item
            for item in [title, visible_content, suggestions_text, device_name, asset_id, manage_ip]
            if item
        ).strip()
        if not core_text:
            raise RuntimeError(
                "创建工单至少需要提供问题描述/处置意见，以及设备IP、设备名称、资源中的至少一个。"
            )

        resolved_title = cls._derive_title(
            title=title,
            visible_content=visible_content,
            suggestions=suggestions_text,
            device_name=device_name,
            manage_ip=manage_ip,
            asset_id=asset_id,
        )
        resolved_visible_content = (
            visible_content
            or cls._derive_visible_content(
                title=resolved_title,
                device_name=device_name,
                manage_ip=manage_ip,
                asset_id=asset_id,
                suggestions=suggestions_text,
            )
        )
        resolved_metric_type = metric_type or cls._infer_metric_type(core_text)
        resolved_level = cls._normalize_level(
            cls._pick_text(
                payload,
                "level",
                "priority",
                nested=("alarm", "level"),
                nested_alt=("ticket", "priority"),
            ),
            fallback_text=core_text,
        )
        resolved_status = cls._normalize_status(
            cls._pick_text(payload, "status", nested=("alarm", "status"))
        )
        event_time = cls._pick_text(
            payload,
            "eventTime",
            "alarmTime",
            "occurTime",
            nested=("alarm", "eventTime"),
        ) or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        alarm_id = cls._pick_text(payload, "alarmId", nested=("alarm", "alarmId")) or cls._generate_alarm_id()
        res_id = cls._pick_text(payload, "resId", "resourceId") or asset_id or manage_ip or device_name or alarm_id

        resolved_suggestions = suggestions_text or f"请人工处理：{resolved_title}"
        return {
            "chatId": chat_id,
            "resId": res_id,
            "metricType": resolved_metric_type,
            "alarm": {
                "alarmId": alarm_id,
                "title": resolved_title,
                "visibleContent": resolved_visible_content,
                "deviceName": device_name or asset_id or "-",
                "manageIp": manage_ip or "",
                "assetId": asset_id or res_id,
                "level": resolved_level,
                "status": resolved_status,
                "eventTime": event_time,
            },
            "analysis": {
                "summary": analysis_payload.get("summary") or resolved_suggestions,
                "rootCause": analysis_payload.get("rootCause") or "",
                "suggestions": cls._split_suggestions(
                    analysis_payload.get("suggestions") or resolved_suggestions
                ),
            },
            "ticket": {
                "title": ticket_payload.get("title") or cls._derive_ticket_title(resolved_title),
                "priority": ticket_payload.get("priority") or cls._level_to_priority(resolved_level),
                "category": ticket_payload.get("category") or cls._infer_category(resolved_metric_type),
                "source": ticket_payload.get("source") or "portal-order-agent",
                "externalSystem": ticket_payload.get("externalSystem") or "manual-workorder",
            },
        }

    @staticmethod
    def _pick_text(
        payload: dict[str, Any],
        *keys: str,
        nested: tuple[str, str] | None = None,
        nested_alt: tuple[str, str] | None = None,
    ) -> str:
        candidates: list[Any] = []
        for key in keys:
            candidates.append(payload.get(key))
        for path in [nested, nested_alt]:
            if not path:
                continue
            parent = payload.get(path[0])
            if isinstance(parent, dict):
                candidates.append(parent.get(path[1]))
        for item in candidates:
            if isinstance(item, list):
                item = OrderWorkflowClient._join_suggestions(item)
            if item is None:
                continue
            text = str(item).strip()
            if text:
                return text
        return ""

    @staticmethod
    def _join_suggestions(value: Any) -> str:
        if isinstance(value, list):
            parts = [str(item).strip() for item in value if str(item).strip()]
            return "；".join(parts)
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _split_suggestions(value: Any) -> list[str]:
        text = OrderWorkflowClient._join_suggestions(value)
        if not text:
            return []
        parts = [item.strip() for item in re.split(r"[；;。\n]+", text) if item.strip()]
        return parts or [text]

    @staticmethod
    def _extract_ip(text: str) -> str:
        if not text:
            return ""
        matched = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)
        return matched.group(0) if matched else ""

    @staticmethod
    def _derive_title(
        *,
        title: str,
        visible_content: str,
        suggestions: str,
        device_name: str,
        manage_ip: str,
        asset_id: str,
    ) -> str:
        if title:
            return title
        base = visible_content or suggestions
        if not base:
            base = device_name or asset_id or manage_ip or "人工处置"
        compact = re.sub(r"\s+", " ", base).strip("，,；;。 ")
        if len(compact) > 24:
            compact = compact[:24].rstrip()
        return compact or "人工处置"

    @staticmethod
    def _derive_ticket_title(title: str) -> str:
        if title.endswith("工单"):
            return title
        if title.endswith("人工处置"):
            return title
        return f"{title}人工处置"

    @staticmethod
    def _derive_visible_content(
        *,
        title: str,
        device_name: str,
        manage_ip: str,
        asset_id: str,
        suggestions: str,
    ) -> str:
        device_part = device_name or asset_id
        if device_part and manage_ip:
            return f"{title}（{device_part} {manage_ip}）"
        if device_part:
            return f"{title}（{device_part}）"
        if manage_ip:
            return f"{title}（{manage_ip}）"
        if suggestions:
            return suggestions
        return title

    @staticmethod
    def _infer_metric_type(text: str) -> str:
        lowered = text.lower()
        if "mysql" in lowered:
            return "mysql"
        if "oracle" in lowered:
            return "oracle"
        if "redis" in lowered:
            return "redis"
        if "nginx" in lowered:
            return "nginx"
        if "k8s" in lowered or "kubernetes" in lowered or "pod" in lowered:
            return "kubernetes"
        if "数据库" in text or "db" in lowered:
            return "database"
        if "交换机" in text or "路由器" in text or "网络" in text:
            return "network"
        if "服务器" in text or "主机" in text or "host" in lowered:
            return "server"
        return "generic"

    @staticmethod
    def _normalize_level(raw_value: str, *, fallback_text: str) -> str:
        text = (raw_value or fallback_text or "").strip().lower()
        if any(token in text for token in ["critical", "严重", "高危", "紧急", "p1", "sev1", "一级"]):
            return "critical"
        if any(token in text for token in ["major", "重要", "较高", "高", "p2", "sev2", "二级"]):
            return "major"
        if any(token in text for token in ["minor", "一般", "中", "p3", "sev3", "三级"]):
            return "minor"
        if any(token in text for token in ["异常", "告警", "故障", "error", "alert", "incident"]):
            return "major"
        return "major"

    @staticmethod
    def _normalize_status(raw_value: str) -> str:
        text = (raw_value or "").strip().lower()
        if text in {"clear", "closed", "resolved", "1"}:
            return "clear"
        return "active"

    @staticmethod
    def _level_to_priority(level: str) -> str:
        return {
            "critical": "P1",
            "major": "P2",
            "minor": "P3",
            "warning": "P4",
        }.get(level, "P2")

    @staticmethod
    def _infer_category(metric_type: str) -> str:
        normalized = (metric_type or "generic").strip().lower().replace(" ", "-")
        return f"{normalized}-manual"

    @staticmethod
    def _generate_alarm_id() -> str:
        return f"alarm-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _format_request_error(exc: requests.exceptions.RequestException) -> str:
        response = getattr(exc, "response", None)
        if response is None:
            return f"{type(exc).__name__}: {exc}"
        text = response.text.strip()
        if text:
            return f"HTTP {response.status_code}: {text}"
        return f"HTTP {response.status_code}: {response.reason}"

    def _curl_request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, Any] | None,
        json_body: dict[str, Any] | None,
    ) -> dict[str, Any]:
        query_url = url
        if params:
            query_url = f"{url}?{urlencode(params, doseq=True)}"

        args = [
            "curl",
            "-sS",
            "-X",
            method.upper(),
            "--connect-timeout",
            str(int(self.config.timeout_seconds)),
            "--max-time",
            str(int(self.config.timeout_seconds)),
            query_url,
        ]
        for key, value in headers.items():
            args.extend(["-H", f"{key}: {value}"])

        tmp_path = ""
        if json_body is not None:
            tmp = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
            )
            json.dump(json_body, tmp, ensure_ascii=False)
            tmp.flush()
            tmp.close()
            tmp_path = tmp.name
            args.extend(
                [
                    "-H",
                    "Content-Type: application/json;charset=utf-8",
                    "--data-binary",
                    f"@{tmp_path}",
                ]
            )

        try:
            completed = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.strip() or "curl request failed")
            return json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON response from {query_url}") from exc
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
