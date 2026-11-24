import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

import pytest

SPEC = importlib.util.spec_from_file_location(
    "alarm_query_syslog", Path(__file__).resolve().parents[1] / "query_syslog.py"
)
assert SPEC is not None and SPEC.loader is not None
syslog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(syslog)

LIST = [
    "list", "--device-ip", "192.0.2.9", "--start-time", "2026-11-23 09:50:00",
    "--end-time", "2026-11-23 10:10:00",
]


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setenv("INOE_API_BASE_URL", "https://gateway.example/resource/")
    monkeypatch.setenv("INOE_API_TOKEN", "test-bearer")
    opener = Mock()
    monkeypatch.setattr(syslog, "build_opener", lambda *args: opener)
    return opener.open


def run(gateway, capsys, args, response):
    gateway.return_value = io.BytesIO(json.dumps(response).encode())
    code = syslog.main(args)
    return code, json.loads(capsys.readouterr().out)


def test_list_preserves_query_and_distinguishes_empty(gateway, capsys):
    code, result = run(gateway, capsys, LIST, {"code": 200, "rows": [], "total": 0})
    assert code == 0 and result["status"] == "empty" and result["total"] == 0
    request = gateway.call_args.args[0]
    url = urlsplit(request.full_url)
    assert url.path == "/resource/alarm/event/message/syslog-log/list"
    assert request.get_method() == "GET"
    assert request.get_header("Authorization") == "Bearer test-bearer"
    assert parse_qs(url.query) == {
        "deviceIp": ["192.0.2.9"], "startTime": ["2026-11-23 09:50:00"],
        "endTime": ["2026-11-23 10:10:00"], "pageNum": ["1"], "pageSize": ["20"],
    }
    assert gateway.call_count == 1


def test_list_keeps_total_distinct_from_evidence(gateway, capsys, monkeypatch):
    monkeypatch.setenv("INOE_API_BASE_URL", "https://gateway.example")
    body = {
        "code": 200, "total": 21,
        "rows": [{"logId": "log+1", "hostIp": "192.0.2.9", "rawMessage": "x" * 2000}],
    }
    code, result = run(gateway, capsys, LIST, body)
    assert code == 0 and result["status"] == "ok" and result["total"] == 21
    assert result["rows"][0]["logId"] == "log+1"
    assert len(result["rows"][0]["rawMessage"]) < 2000
    assert urlsplit(gateway.call_args.args[0].full_url).path.startswith("/resource/")


@pytest.mark.parametrize("returned_id", ["log+1/2", "unrelated"])
def test_detail_encodes_opaque_id_and_verifies_match(gateway, capsys, returned_id):
    body = {"code": 200, "data": {
        "logId": returned_id, "relatedAlarms": [{"alarmId": "a-1"}],
    }}
    code, result = run(gateway, capsys, ["detail", "--log-id=log+1/2"], body)
    url = urlsplit(gateway.call_args.args[0].full_url)
    assert parse_qs(url.query) == {"logId": ["log+1/2"]}
    if returned_id == "log+1/2":
        assert code == 0 and result["data"]["relatedAlarms"] == [{"alarmId": "a-1"}]
    else:
        assert code == 1 and result["reason"] == "log_id_mismatch"


@pytest.mark.parametrize("status", [302, 401, 500])
def test_http_error_is_not_retried_or_echoed(gateway, capsys, status):
    details = io.BytesIO(b"test-bearer")
    gateway.side_effect = HTTPError("https://gateway.example", status, "", {}, details)
    assert syslog.main(LIST) == 1
    assert json.loads(capsys.readouterr().out) == {
        "source": "syslog_http", "status": "error", "reason": "http_error", "code": status,
    }
    assert gateway.call_count == 1 and details.closed


def test_invalid_window_and_missing_token_do_not_send_requests(gateway, capsys, monkeypatch):
    assert syslog.main([*LIST[:-1], "2026-11-23 12:00:00"]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "invalid_query"
    monkeypatch.delenv("INOE_API_TOKEN")
    assert syslog.main(LIST) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "invalid_or_missing_bearer"
    gateway.assert_not_called()
