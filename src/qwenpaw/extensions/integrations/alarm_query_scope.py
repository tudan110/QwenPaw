# -*- coding: utf-8 -*-
"""Scope metadata for the gateway's mandatory time-window alarm queries."""

from datetime import datetime, timezone
from typing import Any


def build_alarm_query_scope(
    start_time: str,
    end_time: str,
    tz: timezone,
    *,
    is_clear: Any = None,
) -> dict[str, Any]:
    offset = datetime.now(tz).strftime("%z")
    return {
        "kind": (
            "windowed_history"
            if is_clear is None
            else "windowed_uncleared"
            if str(is_clear) == "0"
            else "windowed_cleared"
        ),
        "startTime": start_time,
        "endTime": end_time,
        "timezone": f"UTC{offset[:3]}:{offset[3:]}",
        "complete": False,
        "limitation": (
            "仅覆盖查询时间范围，不代表全量活动告警；"
            "空结果不能证明系统健康。"
        ),
    }
