#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源巡检指标采集脚本。

使用方式:
    python scripts/inspect_resource_metrics.py --res-id 3094 --metric-type mysql --output markdown

说明:
    - 默认读取当前 skill 目录下的 .env
    - 复用 fault/alarm-analyst 的指标接口访问与 HTTP fallback 能力
    - 先查询全部指标定义，再提取全部 metric codes
    - 再以一次批量请求把全部 metric codes 传给 /resource/pm/getMetricData
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests

try:
    from dotenv import load_dotenv

    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False


ALLOWED_OUTPUTS = {"json", "markdown"}
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 20
DEFAULT_NOTIFY_TIMEOUT_SECONDS = 8


def _load_skill_env() -> None:
    if not HAS_DOTENV:
        return

    skill_dir = Path(__file__).resolve().parents[1]
    skill_env_file = skill_dir / ".env"
    if skill_env_file.exists():
        load_dotenv(skill_env_file, override=True)


_load_skill_env()


def _skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _workspaces_root() -> Path:
    return _skill_root().parents[2]


def _alarm_metric_script_path() -> Path:
    return (
        _workspaces_root()
        / "fault"
        / "skills"
        / "alarm-analyst"
        / "scripts"
        / "get_metric_definitions.py"
    )


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ALARM_METRIC_HELPERS = _load_module(
    "inspection_alarm_metric_helpers",
    _alarm_metric_script_path(),
)


def _safe_str(value: Any) -> str:
    return _ALARM_METRIC_HELPERS._safe_str(value)  # noqa: SLF001


def _get_page_size(page_size: int | None) -> int:
    if page_size is not None:
        return page_size
    raw = (os.getenv("INSPECTION_METRIC_PAGE_SIZE") or "").strip()
    if not raw:
        return DEFAULT_PAGE_SIZE
    return int(raw)


def _get_timeout(timeout_seconds: int | None) -> int:
    if timeout_seconds is not None:
        return timeout_seconds
    raw = (os.getenv("INSPECTION_METRIC_TIMEOUT_SECONDS") or "").strip()
    if raw:
        return int(raw)
    return int(getattr(_ALARM_METRIC_HELPERS, "DEFAULT_TIMEOUT_SECONDS", 120))


def _get_notify_env(name: str) -> str:
    return _safe_str(
        os.getenv(f"INSPECTION_NOTIFY_{name}")
        or os.getenv(f"ORDER_CREATE_NOTIFY_{name}")
    )


def _get_notify_timeout() -> int:
    raw = _get_notify_env("TIMEOUT_SECONDS")
    return int(raw) if raw else DEFAULT_NOTIFY_TIMEOUT_SECONDS


def _get_notify_mention_all() -> bool:
    return (_get_notify_env("MENTION_ALL") or "false").lower() in {"1", "true", "yes"}


def _build_metric_data_batch_request(
    *,
    res_id: str | int,
    metric_codes: list[str],
    query_type: str,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mulRes": [{"resId": str(res_id)}],
        "queryKeys": metric_codes,
        "queryType": str(query_type),
    }
    if str(query_type) != "0":
        if not _safe_str(start_time) or not _safe_str(end_time):
            raise ValueError("当 queryType 不等于 0 时，必须同时提供 startTime 和 endTime")
        payload["startTime"] = _safe_str(start_time)
        payload["endTime"] = _safe_str(end_time)
    return payload


def fetch_all_metric_definitions(
    *,
    metric_type: str,
    page_size: int | None = None,
    api_base_url: str | None = None,
    token: str | None = None,
    timeout_seconds: int | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> dict[str, Any]:
    normalized_metric_type = _safe_str(metric_type)
    if not normalized_metric_type:
        raise ValueError("metric_type 不能为空")

    resolved_page_size = _get_page_size(page_size)
    if resolved_page_size < 1:
        raise ValueError("page_size 必须大于等于 1")
    if max_pages < 1:
        raise ValueError("max_pages 必须大于等于 1")

    all_metrics: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    page_sources: list[str] = []
    fallback_reasons: list[str] = []
    first_url = ""
    first_request: dict[str, Any] = {}
    pages_fetched = 0

    for page_num in range(1, max_pages + 1):
        page_result = _ALARM_METRIC_HELPERS.fetch_metric_definitions(
            metric_type=normalized_metric_type,
            page_num=page_num,
            page_size=resolved_page_size,
            api_base_url=api_base_url,
            token=token,
            timeout_seconds=timeout_seconds,
            limit=resolved_page_size,
        )
        pages_fetched += 1
        if not first_url:
            first_url = _safe_str(page_result.get("url"))
        if not first_request:
            first_request = page_result.get("request") or {}

        page_source = _safe_str(page_result.get("source")) or "unknown"
        page_sources.append(page_source)
        fallback_reason = _safe_str(page_result.get("fallbackReason"))
        if fallback_reason:
            fallback_reasons.append(fallback_reason)

        page_metrics = page_result.get("metrics") or []
        if not page_metrics:
            break

        for metric in page_metrics:
            code = _safe_str(metric.get("code"))
            dedupe_key = code or json.dumps(metric, ensure_ascii=False, sort_keys=True)
            if dedupe_key in seen_codes:
                continue
            seen_codes.add(dedupe_key)
            all_metrics.append(metric)

        if page_source != "live" or len(page_metrics) < resolved_page_size:
            break

    combined_source = "live" if page_sources and all(source == "live" for source in page_sources) else "mock"
    return {
        "code": 200,
        "msg": "查询成功" if combined_source == "live" else "指标定义查询已部分或全部回退到 mock 数据",
        "metricType": normalized_metric_type,
        "source": combined_source,
        "fallbackReason": "；".join(dict.fromkeys(fallback_reasons)) if fallback_reasons else None,
        "url": first_url,
        "request": first_request,
        "pageSize": resolved_page_size,
        "pagesFetched": pages_fetched,
        "metricsTotal": len(all_metrics),
        "metrics": all_metrics,
    }


def _build_mock_metric_data_batch_payload(
    *,
    res_id: str | int,
    metric_codes: list[str],
) -> dict[str, Any]:
    original_point = {"formatTime": "2026-04-24 10:00:00", "gatherTime": 1777005600}
    process_data: dict[str, str] = {}
    for index, metric_code in enumerate(metric_codes, start=1):
        sample_value = str(index)
        process_data[f"{metric_code}Min"] = sample_value
        process_data[f"{metric_code}Avg"] = sample_value
        process_data[f"{metric_code}Max"] = sample_value
        original_point[metric_code] = sample_value

    return {
        "code": 200,
        "msg": "mock",
        "data": [
            {
                "resId": str(res_id),
                "subResName": "",
                "processData": process_data,
                "originalDatas": [original_point],
            }
        ],
    }


def _extract_metric_data_results(
    payload: dict[str, Any],
    *,
    metric_definitions: list[dict[str, Any]],
    source: str,
) -> list[dict[str, Any]]:
    definitions_by_code = {
        _safe_str(metric.get("code")): metric
        for metric in metric_definitions
        if _safe_str(metric.get("code"))
    }
    data_rows = payload.get("data") or []
    row = data_rows[0] if data_rows and isinstance(data_rows[0], dict) else {}
    process_data = row.get("processData") or {}
    original_datas = row.get("originalDatas") or []
    latest_point = original_datas[-1] if original_datas and isinstance(original_datas[-1], dict) else {}

    results: list[dict[str, Any]] = []
    for metric_code, metric in definitions_by_code.items():
        unit = (
            _safe_str(process_data.get("unit"))
            or _safe_str(metric.get("unit"))
            or _safe_str(_ALARM_METRIC_HELPERS._infer_mock_unit(metric_code))  # noqa: SLF001
        )
        results.append(
            {
                "metricCode": metric_code,
                "metricName": _safe_str(metric.get("name")) or metric_code,
                "latestValue": _safe_str(latest_point.get(metric_code)),
                "sampleTime": _safe_str(latest_point.get("formatTime")),
                "minValue": _safe_str(process_data.get(f"{metric_code}Min")),
                "avgValue": _safe_str(process_data.get(f"{metric_code}Avg")),
                "maxValue": _safe_str(process_data.get(f"{metric_code}Max")),
                "unit": unit,
                "source": source,
            }
        )
    return results


def _notification_metric_preview(metric_results: list[dict[str, Any]], limit: int = 5) -> str:
    previews: list[str] = []
    for item in metric_results[:limit]:
        name = _safe_str(item.get("metricName") or item.get("metricCode")) or "指标"
        value = _safe_str(item.get("latestValue") or item.get("avgValue")) or "-"
        unit = _safe_str(item.get("unit"))
        if unit and value != "-":
            value = f"{value}{unit}"
        previews.append(f"{name}={value}")
    return "；".join(previews) or "-"


def _build_notification_context(result: dict[str, Any]) -> dict[str, str]:
    definitions = result.get("definitions") or {}
    metric_batch = result.get("metricDataBatch") or {}
    metric_results = metric_batch.get("metricResults") or []
    return {
        "inspection_object": _safe_str(result.get("inspectionObject")) or "-",
        "resource_name": _safe_str(result.get("resourceName")) or "-",
        "res_id": _safe_str(result.get("resId")) or "-",
        "metric_type": _safe_str(result.get("metricType")) or "-",
        "metrics_total": str(int(definitions.get("metricsTotal") or 0)),
        "definition_source": _safe_str(definitions.get("source")) or "-",
        "data_source": _safe_str(metric_batch.get("source")) or "-",
        "metric_preview": _notification_metric_preview(metric_results),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _build_app_notify_payload(context: dict[str, str]) -> dict[str, Any]:
    content_lines = [
        "【AI巡检结果】",
        f"巡检对象：{context['inspection_object']}",
        f"资源：{context['resource_name']} / CI ID: {context['res_id']}",
        f"资源类型：{context['metric_type']}",
        f"指标总数：{context['metrics_total']}",
        f"指标定义来源：{context['definition_source']}",
        f"指标数据来源：{context['data_source']}",
        f"指标预览：{context['metric_preview']}",
        f"巡检时间：{context['created_at']}",
        "此结果由 AI 自动巡检生成，请及时关注。",
    ]
    text_msg: dict[str, Any] = {
        "content": "\n".join(content_lines),
    }
    if _get_notify_mention_all():
        text_msg.update(
            {
                "isMentioned": True,
                "mentionType": 1,
            }
        )
    return {
        "type": "text",
        "textMsg": text_msg,
    }


def _build_dingtalk_notify_payload(context: dict[str, str]) -> dict[str, Any]:
    content_lines = [
        "【AI巡检结果】",
        f"巡检对象：{context['inspection_object']}",
        f"资源：{context['resource_name']} / CI ID: {context['res_id']}",
        f"资源类型：{context['metric_type']}",
        f"指标总数：{context['metrics_total']}",
        f"指标定义来源：{context['definition_source']}",
        f"指标数据来源：{context['data_source']}",
        f"指标预览：{context['metric_preview']}",
        f"巡检时间：{context['created_at']}",
        "此结果由 AI 自动巡检生成，请及时关注。",
    ]
    keyword = _get_notify_env("DINGTALK_KEYWORD")
    if keyword:
        content_lines.insert(0, keyword)
    payload: dict[str, Any] = {
        "msgtype": "text",
        "text": {
            "content": "\n".join(content_lines),
        },
    }
    if _get_notify_mention_all():
        payload["at"] = {"isAtAll": True}
    return payload


def _build_feishu_notify_payload(context: dict[str, str]) -> dict[str, Any]:
    content_lines = [
        "【AI巡检结果】",
        f"巡检对象：{context['inspection_object']}",
        f"资源：{context['resource_name']} / CI ID: {context['res_id']}",
        f"资源类型：{context['metric_type']}",
        f"指标总数：{context['metrics_total']}",
        f"指标定义来源：{context['definition_source']}",
        f"指标数据来源：{context['data_source']}",
        f"指标预览：{context['metric_preview']}",
        f"巡检时间：{context['created_at']}",
        "此结果由 AI 自动巡检生成，请及时关注。",
    ]
    if _get_notify_mention_all():
        content_lines.insert(0, '<at user_id="all">所有人</at>')
    payload: dict[str, Any] = {
        "msg_type": "text",
        "content": {
            "text": "\n".join(content_lines),
        },
    }
    secret = _get_notify_env("FEISHU_SECRET")
    if secret:
        timestamp = str(int(time.time()))
        string_to_sign = f"{timestamp}\n{secret}"
        sign = base64.b64encode(
            hmac.new(
                string_to_sign.encode("utf-8"),
                b"",
                digestmod=hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        payload["timestamp"] = timestamp
        payload["sign"] = sign
    return payload


def _build_dingtalk_signed_webhook_url(webhook_url: str) -> str:
    secret = _get_notify_env("DINGTALK_SECRET")
    if not secret:
        return webhook_url
    timestamp = str(int(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    sign = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    encoded_sign = quote_plus(base64.b64encode(sign))
    separator = "&" if "?" in webhook_url else "?"
    return f"{webhook_url}{separator}timestamp={timestamp}&sign={encoded_sign}"


def _send_json_webhook(
    *,
    channel_name: str,
    webhook_url: str,
    payload: dict[str, Any],
    success_predicate: Any,
) -> dict[str, Any]:
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=_get_notify_timeout(),
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return {
            "channel": channel_name,
            "status": "failed",
            "reason": str(exc),
        }

    try:
        response_json = response.json()
    except ValueError as exc:
        return {
            "channel": channel_name,
            "status": "failed",
            "reason": f"invalid_json_response: {exc}",
        }

    if success_predicate(response_json):
        return {
            "channel": channel_name,
            "status": "sent",
            "reason": "",
        }
    return {
        "channel": channel_name,
        "status": "failed",
        "reason": response_json.get("errmsg")
        or response_json.get("message")
        or "webhook_rejected",
    }


def _notify_inspection_result(result: dict[str, Any]) -> dict[str, Any]:
    app_webhook_url = _get_notify_env("WEBHOOK_URL")
    dingtalk_webhook_url = _get_notify_env("DINGTALK_WEBHOOK_URL")
    feishu_webhook_url = _get_notify_env("FEISHU_WEBHOOK_URL")
    if not app_webhook_url and not dingtalk_webhook_url and not feishu_webhook_url:
        return {
            "enabled": False,
            "status": "skipped",
            "reason": "webhook_not_configured",
            "channels": [],
        }

    context = _build_notification_context(result)
    channels: list[dict[str, Any]] = []
    if app_webhook_url:
        channels.append(
            _send_json_webhook(
                channel_name="app",
                webhook_url=app_webhook_url,
                payload=_build_app_notify_payload(context),
                success_predicate=lambda data: bool(data.get("ok"))
                or str(data.get("code") or "") == "200",
            )
        )
    if dingtalk_webhook_url:
        channels.append(
            _send_json_webhook(
                channel_name="dingtalk",
                webhook_url=_build_dingtalk_signed_webhook_url(dingtalk_webhook_url),
                payload=_build_dingtalk_notify_payload(context),
                success_predicate=lambda data: str(data.get("errcode", "")) == "0",
            )
        )
    if feishu_webhook_url:
        channels.append(
            _send_json_webhook(
                channel_name="feishu",
                webhook_url=feishu_webhook_url,
                payload=_build_feishu_notify_payload(context),
                success_predicate=lambda data: str(data.get("StatusCode", "")) == "0"
                or str(data.get("code", "")) == "0",
            )
        )

    sent_count = sum(1 for item in channels if item.get("status") == "sent")
    if sent_count == len(channels) and channels:
        status = "sent"
        reason = ""
    elif sent_count > 0:
        status = "partial"
        reason = "partial_failure"
    else:
        status = "failed"
        reason = "; ".join(
            f"{item.get('channel')}:{item.get('reason') or 'unknown'}"
            for item in channels
        )
    return {
        "enabled": True,
        "status": status,
        "reason": reason,
        "channels": channels,
    }


def _format_notification_channels(notification: dict[str, Any], *, fallback: str) -> str:
    sent_channels = [
        _safe_str(item.get("channel"))
        for item in notification.get("channels") or []
        if _safe_str(item.get("status")).lower() == "sent"
    ]
    if not sent_channels:
        return fallback
    label_map = {
        "app": "应用",
        "dingtalk": "钉钉",
        "feishu": "飞书",
    }
    labels = [label_map.get(name, name) for name in sent_channels if name]
    return "、".join(labels) + "已发送"


def _format_notification_status(notification: dict[str, Any]) -> str:
    status = _safe_str(notification.get("status")).lower()
    reason = _safe_str(notification.get("reason"))
    if status == "sent":
        return "✅ 已成功推送"
    if status == "partial":
        return "⚠️ 部分推送成功"
    if status == "failed":
        return f"❌ 推送失败：{reason or '未知错误'}"
    if status == "skipped":
        if reason == "webhook_not_configured":
            return "— 未配置"
        return "— 已跳过"
    return "— 未配置"


def fetch_metric_data_batch(
    *,
    res_id: str | int,
    metric_definitions: list[dict[str, Any]],
    query_type: str = "0",
    start_time: str | None = None,
    end_time: str | None = None,
    api_base_url: str | None = None,
    token: str | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    normalized_res_id = _safe_str(res_id)
    if not normalized_res_id:
        raise ValueError("res_id 不能为空")

    metric_codes = [
        _safe_str(metric.get("code"))
        for metric in metric_definitions
        if _safe_str(metric.get("code"))
    ]
    if not metric_codes:
        raise ValueError("metric_definitions 不能为空，且必须包含至少一个指标编码")

    url = f"{_ALARM_METRIC_HELPERS._normalize_base_url(api_base_url)}/resource/pm/getMetricData"  # noqa: SLF001
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json",
        "Authorization": f"Bearer {_ALARM_METRIC_HELPERS._get_token(token)}",  # noqa: SLF001
    }
    request_payload = _build_metric_data_batch_request(
        res_id=normalized_res_id,
        metric_codes=metric_codes,
        query_type=query_type,
        start_time=start_time,
        end_time=end_time,
    )
    resolved_timeout = _get_timeout(timeout_seconds)

    source = "live"
    fallback_reason = None
    try:
        response_payload, _transport = _ALARM_METRIC_HELPERS._post_json_with_fallback(  # noqa: SLF001
            url=url,
            headers=headers,
            json_payload=request_payload,
            timeout_seconds=resolved_timeout,
        )
        data_rows = response_payload.get("data") or []
        if not data_rows:
            raise ValueError("指标数据接口未返回有效 data")
    except (requests.exceptions.RequestException, ValueError, json.JSONDecodeError) as error:
        source = "mock"
        fallback_reason = str(error)
        response_payload = _build_mock_metric_data_batch_payload(
            res_id=normalized_res_id,
            metric_codes=metric_codes,
        )

    return {
        "code": 200,
        "msg": "查询成功" if source == "live" else f"接口失败，已回退到 mock 数据：{fallback_reason}",
        "source": source,
        "fallbackReason": fallback_reason,
        "url": url,
        "request": request_payload,
        "resId": normalized_res_id,
        "metricResults": _extract_metric_data_results(
            response_payload,
            metric_definitions=metric_definitions,
            source=source,
        ),
        "raw": response_payload,
    }


def inspect_resource_metrics(
    *,
    metric_type: str,
    res_id: str | int,
    inspection_object: str = "",
    resource_name: str = "",
    page_size: int | None = None,
    api_base_url: str | None = None,
    token: str | None = None,
    timeout_seconds: int | None = None,
    query_type: str = "0",
    start_time: str | None = None,
    end_time: str | None = None,
    notify: bool = True,
) -> dict[str, Any]:
    definitions = fetch_all_metric_definitions(
        metric_type=metric_type,
        page_size=page_size,
        api_base_url=api_base_url,
        token=token,
        timeout_seconds=timeout_seconds,
    )
    metric_data_batch = fetch_metric_data_batch(
        res_id=res_id,
        metric_definitions=definitions.get("metrics") or [],
        query_type=query_type,
        start_time=start_time,
        end_time=end_time,
        api_base_url=api_base_url,
        token=token,
        timeout_seconds=timeout_seconds,
    )
    result = {
        "code": 200,
        "msg": "查询成功",
        "inspectionObject": _safe_str(inspection_object),
        "resourceName": _safe_str(resource_name),
        "metricType": _safe_str(metric_type),
        "resId": _safe_str(res_id),
        "definitions": definitions,
        "metricDataBatch": metric_data_batch,
    }
    result["notification"] = _notify_inspection_result(result) if notify else {
        "enabled": False,
        "status": "skipped",
        "reason": "notify_disabled",
        "channels": [],
    }
    return result


def _render_metric_data_table(metric_results: list[dict[str, Any]]) -> str:
    if not metric_results:
        return "- 未获取到指标值"

    lines = [
        "| 指标名 | 指标编码 | 最近值 | 采样时间 | Min/Avg/Max | 数据来源 |",
        "|---|---|---|---|---|---|",
    ]
    for item in metric_results:
        value = _safe_str(item.get("latestValue") or item.get("avgValue") or "-")
        unit = _safe_str(item.get("unit"))
        if unit and value != "-":
            value = f"{value} {unit}".strip()
        min_avg_max = "/".join(
            [
                _safe_str(item.get("minValue") or "-"),
                _safe_str(item.get("avgValue") or "-"),
                _safe_str(item.get("maxValue") or "-"),
            ]
        )
        lines.append(
            "| {name} | {code} | {value} | {sample_time} | {mam} | {source} |".format(
                name=_safe_str(item.get("metricName") or item.get("metricCode") or "-").replace("|", "\\|"),
                code=_safe_str(item.get("metricCode") or "-").replace("|", "\\|"),
                value=value.replace("|", "\\|"),
                sample_time=_safe_str(item.get("sampleTime") or "-").replace("|", "\\|"),
                mam=min_avg_max.replace("|", "\\|"),
                source=_safe_str(item.get("source") or "-").replace("|", "\\|"),
            )
        )
    return "\n".join(lines)


def render_markdown(result: dict[str, Any]) -> str:
    definitions = result.get("definitions") or {}
    metric_batch = result.get("metricDataBatch") or {}
    notification = result.get("notification") or {}
    lines = [
        "## 巡检结果",
        f"- 巡检对象：`{_safe_str(result.get('inspectionObject')) or '-'}`",
        f"- 资源名称：`{_safe_str(result.get('resourceName')) or '-'}`",
        f"- 资源 ID（CI ID）：`{_safe_str(result.get('resId')) or '-'}`",
        f"- 资源类型：`{_safe_str(result.get('metricType')) or '-'}`",
        f"- 指标总数：`{int(definitions.get('metricsTotal') or 0)}`",
        f"- 指标定义来源：`{_safe_str(definitions.get('source')) or '-'}`",
        f"- 指标数据来源：`{_safe_str(metric_batch.get('source')) or '-'}`",
        f"- 通知状态：`{_format_notification_status(notification)}`",
        f"- 通知渠道：`{_format_notification_channels(notification, fallback='未发送')}`",
        "",
        "## 指标数据",
        _render_metric_data_table(metric_batch.get("metricResults") or []),
    ]
    if definitions.get("fallbackReason"):
        lines.append("")
        lines.append(f"- 指标定义回退原因：{definitions['fallbackReason']}")
    if metric_batch.get("fallbackReason"):
        lines.append(f"- 指标数据回退原因：{metric_batch['fallbackReason']}")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="查询巡检对象的全部指标定义与指标数据")
    parser.add_argument("--metric-type", required=True, help="资源类型，对应 ciType，例如 mysql")
    parser.add_argument("--res-id", required=True, help="CMDB 返回的 CI ID")
    parser.add_argument("--inspection-object", default="", help="用户输入的巡检对象")
    parser.add_argument("--resource-name", default="", help="CMDB 确认的资源名称")
    parser.add_argument("--page-size", type=int, default=None, help="每页指标定义数量，默认从 .env 读取")
    parser.add_argument("--api-base-url", help="API 基础地址，默认从 .env 读取")
    parser.add_argument("--token", help="Bearer Token，默认从环境变量 INOE_API_TOKEN 读取")
    parser.add_argument("--timeout-seconds", type=int, default=None, help="超时时间，默认从 .env 读取")
    parser.add_argument("--query-type", default="0", help="指标查询类型，0 表示查询最近一次")
    parser.add_argument("--start-time", help="开始时间，queryType != 0 时必填")
    parser.add_argument("--end-time", help="结束时间，queryType != 0 时必填")
    parser.add_argument("--no-notify", action="store_true", help="仅查询巡检结果，不执行 webhook 推送")
    parser.add_argument("--output", choices=sorted(ALLOWED_OUTPUTS), default="json", help="输出格式")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = inspect_resource_metrics(
            metric_type=args.metric_type,
            res_id=args.res_id,
            inspection_object=args.inspection_object,
            resource_name=args.resource_name,
            page_size=args.page_size,
            api_base_url=args.api_base_url,
            token=args.token,
            timeout_seconds=args.timeout_seconds,
            query_type=args.query_type,
            start_time=args.start_time,
            end_time=args.end_time,
            notify=not args.no_notify,
        )
    except ValueError as error:
        print(f"错误: {error}", file=sys.stderr)
        sys.exit(1)

    if args.output == "markdown":
        print(render_markdown(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
