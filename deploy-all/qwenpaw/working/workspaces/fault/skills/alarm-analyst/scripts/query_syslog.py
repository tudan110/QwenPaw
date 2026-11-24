#!/usr/bin/env python3
"""Single-request, read-only HTTP fallback for alarm-analyst Syslog evidence."""

import argparse
import ipaddress
import json
import os
import sys
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_WINDOW = timedelta(hours=1)
MAX_ROWS = 20
TIMEOUT = 15
MAX_BODY_BYTES = 2 * 1024 * 1024
SYSLOG_PATH = "/alarm/event/message/syslog-log"
LOG_FIELDS = (
    "logId", "alarmTime", "hostIp", "deviceName", "sourceType",
    "sourceTypeLabel", "severity", "logType", "logContent", "rawMessage",
    "activeAlarmCount", "hasRelatedAlarm", "relatedAlarmIds",
)
ALARM_FIELDS = (
    "alarmId", "alarmTitle", "perceivedSeverity", "state", "eventTime",
    "locationInfo",
)


class QueryError(Exception):
    def __init__(self, kind, code=None):
        super().__init__(kind)
        self.kind = kind
        self.code = code


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never send the platform credential to a redirected endpoint.
        return None


def list_params(args):
    try:
        ipaddress.ip_address(args.device_ip)
        start = datetime.strptime(args.start_time, TIME_FORMAT)
        end = datetime.strptime(args.end_time, TIME_FORMAT)
    except ValueError:
        raise QueryError("invalid_query") from None
    if not (
        start.strftime(TIME_FORMAT) == args.start_time
        and end.strftime(TIME_FORMAT) == args.end_time
        and timedelta(0) < end - start <= MAX_WINDOW
        and 1 <= args.page_size <= MAX_ROWS
    ):
        raise QueryError("invalid_query")
    return {
        "deviceIp": args.device_ip,
        "startTime": args.start_time,
        "endTime": args.end_time,
        "pageNum": 1,
        "pageSize": args.page_size,
    }


def resource_url(operation):
    try:
        base = urlsplit(os.environ.get("INOE_API_BASE_URL", "").strip())
        if (
            base.scheme not in {"http", "https"}
            or not base.hostname
            or base.username is not None
            or base.query
            or base.fragment
        ):
            raise ValueError
        base.port  # Validate the optional port before opening the request.
    except ValueError:
        raise QueryError("invalid_or_missing_gateway") from None
    path = base.path.rstrip("/")
    if not path.endswith("/resource"):
        path += "/resource"
    return urlunsplit(base._replace(path=f"{path}{SYSLOG_PATH}/{operation}"))


def request(operation, params):
    url = resource_url(operation)
    token = os.environ.get("INOE_API_TOKEN", "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token or not token.isascii() or any(c.isspace() for c in token):
        raise QueryError("invalid_or_missing_bearer")
    req = Request(
        f"{url}?{urlencode(params)}",
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with build_opener(NoRedirect()).open(req, timeout=TIMEOUT) as reply:
            raw = reply.read(MAX_BODY_BYTES + 1)
    except HTTPError as exc:
        with exc:
            raise QueryError("http_error", exc.code) from None
    except (URLError, OSError) as exc:
        reason = exc.reason if isinstance(exc, URLError) else exc
        kind = "timeout" if isinstance(reason, TimeoutError) else "transport_error"
        raise QueryError(kind) from None
    if len(raw) > MAX_BODY_BYTES:
        raise QueryError("response_too_large")
    try:
        body = json.loads(raw)
    except (ValueError, RecursionError):
        raise QueryError("invalid_response") from None
    if not isinstance(body, dict) or type(body.get("code")) is not int:
        raise QueryError("invalid_response")
    if body["code"] != 200:
        raise QueryError("business_error", body["code"])
    return body


def project(record, fields):
    # Keep bounded evidence; omit unstructured parsedFields and response metadata.
    if not isinstance(record, dict):
        raise QueryError("invalid_response")
    result = {}
    for name in fields:
        val = record.get(name)
        if isinstance(val, str):
            # Preserve opaque identifiers for exact lookup.
            result[name] = val if name.endswith("Id") else (
                val if len(val) <= 1000 else val[:1000] + "…"
            )
        elif val is None or type(val) in {bool, int, float}:
            if name in record:
                result[name] = val
        elif name == "relatedAlarmIds" and isinstance(val, list):
            result[name] = [item for item in val[:5] if isinstance(item, str)]
    return result


def execute(args):
    if args.operation == "list":
        params = list_params(args)
        body = request("list", params)
        rows, total = body.get("rows"), body.get("total")
        if (
            not isinstance(rows, list)
            or type(total) is not int
            or not len(rows) <= total
            or len(rows) > params["pageSize"]
            or (total > 0 and not rows)
        ):
            raise QueryError("invalid_response")
        return {
            "status": "ok" if rows else "empty",
            "conditions": {**params, "timeZone": "Asia/Shanghai"},
            "total": total,
            "rows": [project(row, LOG_FIELDS) for row in rows],
        }
    if not args.log_id.strip() or len(args.log_id) > 512 or any(
        ord(char) < 32 for char in args.log_id
    ):
        raise QueryError("invalid_log_id")
    body = request("detail", {"logId": args.log_id})
    if "data" not in body:
        raise QueryError("invalid_response")
    data = body["data"]
    if data is None:
        return {"status": "empty", "data": None}
    record = project(data, LOG_FIELDS)
    if record.get("logId") != args.log_id:
        raise QueryError("log_id_mismatch")
    alarms = data.get("relatedAlarms")
    if alarms is not None:
        if not isinstance(alarms, list):
            raise QueryError("invalid_response")
        record["relatedAlarms"] = [
            project(alarm, ALARM_FIELDS) for alarm in alarms[:5]
        ]
        record["relatedAlarmsReturned"] = len(alarms)
    return {"status": "ok", "data": record}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    list_command = commands.add_parser("list")
    list_command.add_argument("--device-ip", required=True)
    list_command.add_argument("--start-time", required=True)
    list_command.add_argument("--end-time", required=True)
    list_command.add_argument("--page-size", type=int, default=MAX_ROWS)
    detail_command = commands.add_parser("detail")
    detail_command.add_argument("--log-id", required=True)
    args = parser.parse_args(argv)
    try:
        result = execute(args)
        exit_code = 0
    except QueryError as exc:
        result = {"status": "error", "reason": exc.kind}
        if exc.code is not None:
            result["code"] = exc.code
        exit_code = 1
    print(json.dumps({"source": "syslog_http", **result}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
