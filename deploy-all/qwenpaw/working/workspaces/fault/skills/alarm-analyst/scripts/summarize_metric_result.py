"""Summarize records supplied by the existing controlled history-recall tool.

This module does not open files, databases, network connections or processes.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

TOOL_NAME = "inspection__getMetricData"


def _resource_id(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("资源标识须为非空字符串或整数")
    result = str(value).strip()
    if not result:
        raise ValueError("资源标识不能为空")
    return result


def _summarize_item(item: dict[str, Any]) -> dict[str, Any]:
    samples = item.get("originalDatas")
    if not isinstance(samples, list) or not all(
        isinstance(sample, dict) for sample in samples
    ):
        raise ValueError("指标完整结果缺少有效的 originalDatas 样本列表")
    times: list[tuple[datetime, str]] = []
    metric_names: set[str] = set()
    for sample in samples:
        metric_names.update(sample.keys() - {"formatTime", "gatherTime"})
        value = sample.get("formatTime")
        if value is None or value == "":
            continue
        if not isinstance(value, str) or not any(
            separator in value for separator in (" ", "T")
        ):
            raise ValueError("formatTime 不是有效的采样日期时间")
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError("formatTime 无法解析，不能确认采样覆盖") from exc
        times.append((parsed, value.strip()))
    aware = {stamp.utcoffset() is not None for stamp, _ in times}
    if len(aware) > 1:
        raise ValueError("采样时间混合有时区与无时区值，不能直接比较")
    ordered = sorted(times, key=lambda pair: pair[0])
    limitations = []
    if len(times) < len(samples):
        limitations.append("部分样本缺少时间，边界仅覆盖有时间的样本")
    if not samples:
        limitations.append("未返回样本，不代表资源正常")
    elif not times:
        limitations.append("未取得有效采样时间，起止未知")
    if len({stamp for stamp, _ in times}) < len(times):
        limitations.append(
            "存在重复时间，样本数保留原始条数，不据此推断连续性"
        )
    process_data = item.get("processData")
    if process_data is not None and not isinstance(process_data, dict):
        raise ValueError("接口统计 processData 格式异常")
    statistics = {
        metric + suffix: process_data[metric + suffix]
        for metric in sorted(metric_names)
        for suffix in ("Min", "Max", "Avg", "_unit")
        if process_data is not None and metric + suffix in process_data
    }
    if not statistics:
        limitations.append("接口未提供对应指标统计，不补算或填零")
    return {
        "resId": _resource_id(item.get("resId")),
        "subResName": item.get("subResName"),
        "sampleCount": len(samples),
        "timestampCount": len(times),
        "uniqueTimestampCount": len({stamp for stamp, _ in times}),
        "actualStart": ordered[0][1] if ordered else None,
        "actualEnd": ordered[-1][1] if ordered else None,
        "timeBasis": (
            "接口时间带时区，按实际时刻比较"
            if aware == {True}
            else "接口未提供时区，不推定为UTC或本地时区"
        ),
        "apiStatistics": statistics,
        "statisticsSource": "原接口统计，未筛选重算",
        "limitations": limitations,
    }


def summarize_records(
    records: list[dict[str, Any]], *, res_id: str | int
) -> dict[str, Any]:
    """Validate one recalled metric result and summarize matching resources."""
    expected_id = _resource_id(res_id)
    if not isinstance(records, list) or not all(
        isinstance(row, dict) for row in records
    ):
        raise ValueError("回读记录须为工具返回的记录列表")
    results = [
        row
        for row in records
        if row.get("kind") == "tool_result" and row.get("name") == TOOL_NAME
    ]
    if len(results) != 1:
        raise ValueError("需要唯一的指标工具结果；缺失或多份结果不能猜选")
    content = results[0].get("content")
    if not isinstance(content, str):
        raise ValueError("完整指标结果缺少JSON正文")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("完整指标结果不是有效JSON，不能使用截断片段") from exc
    if not isinstance(payload, dict):
        raise ValueError("指标响应不是JSON对象")
    code = payload.get("code")
    if isinstance(code, bool) or code not in (0, "0", 200, "200"):
        raise ValueError("指标接口未成功，不将错误响应当作空样本")
    data = payload.get("data")
    if not isinstance(data, list) or not all(
        isinstance(item, dict) for item in data
    ):
        raise ValueError("指标完整结果缺少有效的数据列表")
    matches = [
        item for item in data if _resource_id(item.get("resId")) == expected_id
    ]
    if not matches:
        raise ValueError("完整结果未包含本轮指定资源，不借用其他资源数据")
    return {
        "sourceTool": TOOL_NAME,
        "resources": [_summarize_item(item) for item in matches],
    }
