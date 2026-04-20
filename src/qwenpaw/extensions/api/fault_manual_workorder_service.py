from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .fault_manual_workorder_models import (
    ManualWorkorderCloseNotificationRequest,
    ManualWorkorderDispatchRequest,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_manual_dispatch_payload(
    request: ManualWorkorderDispatchRequest,
    *,
    callback_url: str,
) -> dict[str, Any]:
    alarm_payload = request.alarm.model_dump(mode="json")
    analysis_payload = request.analysis.model_dump(mode="json")
    ticket_payload = request.ticket.model_dump(mode="json")

    title = ticket_payload.get("title") or alarm_payload.get("title") or "人工故障处置工单"
    return {
        "chatId": request.chat_id,
        "resId": request.res_id,
        "metricType": request.metric_type,
        "alarm": alarm_payload,
        "analysis": analysis_payload,
        "ticket": {
            **ticket_payload,
            "title": title,
        },
        "context": {
            "source": ticket_payload.get("source") or "portal-fault-disposal",
            "externalSystem": ticket_payload.get("external_system") or "manual-workorder",
            "callback_url": callback_url,
        },
    }


def build_manual_workorder_record(
    request: ManualWorkorderDispatchRequest,
    *,
    callback_url: str,
) -> dict[str, Any]:
    now = utc_now_iso()
    dispatch_payload = build_manual_dispatch_payload(request, callback_url=callback_url)
    return {
        "chatId": request.chat_id,
        "resId": request.res_id,
        "metricType": request.metric_type,
        "status": "pending_manual",
        "alarm": request.alarm.model_dump(mode="json"),
        "analysis": request.analysis.model_dump(mode="json"),
        "ticket": request.ticket.model_dump(mode="json"),
        "dispatchPayload": dispatch_payload,
        "callbackUrl": callback_url,
        "createdAt": now,
        "updatedAt": now,
    }


def merge_manual_workorder_notification(
    record: dict[str, Any],
    notification: ManualWorkorderCloseNotificationRequest,
    *,
    verification: dict[str, Any],
) -> dict[str, Any]:
    now = utc_now_iso()
    workorder_payload = notification.workorder.model_dump(mode="json")
    processing_payload = notification.processing.model_dump(mode="json")
    verification_status = str(verification.get("status") or "unknown")
    merged = dict(record)
    merged["status"] = f"manual_{verification_status}"
    merged["workorder"] = {
        **(record.get("workorder") or {}),
        **workorder_payload,
    }
    merged["processing"] = processing_payload
    merged["verification"] = verification
    merged["updatedAt"] = now
    return merged


def build_manual_dispatch_history_message(record: dict[str, Any]) -> dict[str, Any]:
    dispatch_payload = record.get("dispatchPayload") or {}
    alarm = dispatch_payload.get("alarm") or {}
    title = alarm.get("title") or "人工故障处置工单"
    visible_content = alarm.get("visible_content") or alarm.get("visibleContent") or ""
    summary = dispatch_payload.get("analysis", {}).get("summary") or "AI 当前转人工处理"
    callback_url = dispatch_payload.get("context", {}).get("callback_url") or record.get("callbackUrl") or ""
    content_lines = [
        "## 人工故障工单已生成派单请求",
        f"- 会话 ID：`{record.get('chatId', '')}`",
        f"- 资源 ID（CI ID）：`{record.get('resId', '')}`",
        f"- 告警标题：`{title}`",
    ]
    if visible_content:
        content_lines.append(f"- 告警摘要：{visible_content}")
    content_lines.extend(
        [
            f"- 派单原因：{summary}",
            f"- 回调地址：`{callback_url}`",
            "- 当前状态：已转人工处理，等待工单系统回调处理结果",
        ]
    )
    return {
        "type": "agent",
        "content": "\n".join(content_lines),
        "manualWorkorder": record,
    }


def build_manual_close_history_message(
    record: dict[str, Any],
    *,
    verification: dict[str, Any],
) -> dict[str, Any]:
    processing = record.get("processing") or {}
    workorder = record.get("workorder") or {}
    verification_summary = verification.get("summary") or "已完成恢复性检测"
    abnormal_metrics = verification.get("abnormalMetrics") or []
    content_lines = [
        "## 人工处理完成通知",
        f"- 会话 ID：`{record.get('chatId', '')}`",
        f"- 资源 ID（CI ID）：`{record.get('resId', '')}`",
    ]
    if workorder.get("workorder_no"):
        content_lines.append(f"- 工单号：`{workorder['workorder_no']}`")
    if processing.get("summary"):
        content_lines.append(f"- 处理摘要：{processing['summary']}")
    if processing.get("details"):
        content_lines.append(f"- 处理详情：{processing['details']}")
    content_lines.append(f"- 恢复验证结论：{verification_summary}")
    if abnormal_metrics:
        metric_descriptions = "；".join(
            f"{item.get('metricCode')}={item.get('latestValue') or item.get('avgValue') or '-'}"
            for item in abnormal_metrics
        )
        content_lines.append(f"- 当前仍异常指标：{metric_descriptions}")
    else:
        content_lines.append("- 当前关键指标未见明显异常")

    return {
        "type": "agent",
        "content": "\n".join(content_lines),
        "manualWorkorder": record,
        "recoveryVerification": verification,
    }


def evaluate_metric_recovery(metric_result: dict[str, Any]) -> dict[str, Any]:
    definitions = metric_result.get("definitions") or {}
    metric_data_results = metric_result.get("metricDataResults") or []
    selected_metrics = metric_result.get("selectedMetrics") or []

    if not metric_data_results:
        return {
            "status": "unknown",
            "summary": "缺少指标值结果，无法评估是否恢复正常",
            "usedMock": False,
            "checkedMetrics": selected_metrics,
            "abnormalMetrics": [],
            "metricDataResults": metric_data_results,
            "source": definitions.get("source") or "unknown",
        }

    used_mock = any(item.get("source") == "mock" for item in metric_data_results)
    abnormal_metrics: list[dict[str, Any]] = []
    for item in metric_data_results:
        metric_code = str(item.get("metricCode") or "").lower()
        numeric_text = item.get("latestValue") or item.get("avgValue") or ""
        try:
            numeric_value = float(str(numeric_text))
        except (TypeError, ValueError):
            numeric_value = None

        if numeric_value is None:
            continue
        if any(keyword in metric_code for keyword in ("lock", "deadlock", "wait", "slow")) and numeric_value > 0:
            abnormal_metrics.append(item)

    if used_mock:
        status = "unknown"
        summary = "指标查询已回退到 mock 数据，暂时无法据此确认是否恢复正常"
    elif abnormal_metrics:
        status = "unrecovered"
        summary = "最新关键指标仍显示锁等待/慢 SQL 类异常，暂不能判定已经恢复"
    else:
        status = "recovered"
        summary = "最新关键指标未见锁等待/慢 SQL 类异常，可初步判定已恢复"

    return {
        "status": status,
        "summary": summary,
        "usedMock": used_mock,
        "checkedMetrics": selected_metrics,
        "abnormalMetrics": abnormal_metrics,
        "metricDataResults": metric_data_results,
        "source": definitions.get("source") or "unknown",
    }
