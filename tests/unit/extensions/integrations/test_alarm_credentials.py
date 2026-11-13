# -*- coding: utf-8 -*-
"""Exercise real skill execute() entrypoints, not just the CLI wrapper."""

import importlib.util
import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(params=["query", "fault", "gateway"])
def alarm(request, monkeypatch):
    path = ROOT / (
        "deploy-all/qwenpaw/working/workspaces/"
        f"{request.param}/skills/real-alarm/scripts/get_alarms.py"
    )
    spec = importlib.util.spec_from_file_location(
        f"phase_a_alarm_{request.param}", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("USE_MOCK_DATA", "false")
    monkeypatch.setenv("INOE_API_BASE_URL", "http://gateway:8080")
    monkeypatch.setenv("INOE_API_TOKEN", "environment-token")
    response = Mock(status_code=200)
    response.json.return_value = {
        "code": 200,
        "total": 1,
        "rows": [{"alarmId": "fixture"}],
    }
    module.requests = Mock()
    module.requests.get.return_value = response
    # Keep exception classes real for the actual error paths.
    import requests

    module.requests.exceptions = requests.exceptions
    return module


def test_default_internal_call_reads_authorized_environment(alarm):
    result = alarm.execute()
    assert result["code"] == 200
    assert result["rows"][0]["alarmId"] == "fixture"
    assert alarm.requests.get.call_args.kwargs["headers"]["Authorization"] == (
        "Bearer environment-token"
    )


def test_explicit_parameter_wins_and_bearer_is_not_duplicated(alarm):
    assert alarm.execute(token="Bearer explicit-token")["code"] == 200
    assert alarm.requests.get.call_args.kwargs["headers"]["Authorization"] == (
        "Bearer explicit-token"
    )


def test_invalid_explicit_token_is_not_replaced_by_environment(alarm):
    alarm.requests.get.return_value.json.return_value = {
        "code": 401,
        "msg": "expired token",
    }
    result = alarm.execute(token="invalid-token")
    assert result["code"] == 401
    assert result["diagnostic"]["stage"] == "inoe_gateway"
    assert result["diagnostic"]["http_status"] == 200
    assert result["diagnostic"]["business_code"] == 401
    alarm.requests.get.assert_called_once()
    assert alarm.requests.get.call_args.kwargs["headers"]["Authorization"] == (
        "Bearer invalid-token"
    )


@pytest.mark.parametrize("explicit", [None, ""])
def test_missing_token_is_distinct_from_zero_alarms(
    alarm, monkeypatch, explicit
):
    monkeypatch.delenv("INOE_API_TOKEN")
    result = alarm.execute(token=explicit)
    assert result["code"] == 401
    assert result["diagnostic"]["error_code"] == "INOE_TOKEN_MISSING"
    assert result["diagnostic"]["stage"] == "script_credentials"
    assert result["diagnostic"]["occurred_at"]
    alarm.requests.get.assert_not_called()


def test_explicit_empty_token_does_not_fall_back(alarm):
    assert alarm.execute(token="")["code"] == 401
    alarm.requests.get.assert_not_called()


def test_inprocess_request_context_wins_over_shared_environment(alarm):
    from qwenpaw.extensions.api.inoe_settings_store import (
        CURRENT_REQUEST_TOKEN,
    )

    reset = CURRENT_REQUEST_TOKEN.set("request-token")
    try:
        assert alarm.execute()["code"] == 200
        assert alarm.requests.get.call_args.kwargs["headers"][
            "Authorization"
        ] == ("Bearer request-token")
    finally:
        CURRENT_REQUEST_TOKEN.reset(reset)


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_curl_fallback_keeps_credentials_out_of_process_arguments(
    alarm, monkeypatch, method
):
    def run(args, **kwargs):
        assert "environment-token" not in " ".join(args)
        assert "--config" in args
        assert "Bearer environment-token" in kwargs["input"]
        body_path = Path(args[args.index("-o") + 1])
        body_path.write_text('{"code":200,"total":1,"rows":[{}]}')
        return SimpleNamespace(returncode=0, stdout="200", stderr="")

    monkeypatch.setattr(alarm.subprocess, "run", run)
    kwargs = {
        "url": "http://gateway:8080/fixture",
        "headers": {"Authorization": "Bearer environment-token"},
    }
    if method == "GET":
        result = alarm._curl_get_json(**kwargs, params={})
    else:
        result = alarm._curl_post_json(**kwargs, data={})
    assert result["code"] == 200


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_real_curl_config_authenticates_without_network_fallback_guessing(
    alarm, method
):
    if not shutil.which("curl"):
        pytest.skip("curl is not installed")
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(self.headers.get("Authorization"))
            body = json.dumps({"code": 200, "total": 1, "rows": [{}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        do_POST = do_GET

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        kwargs = {
            "url": f"http://127.0.0.1:{server.server_port}/fixture",
            "headers": {"Authorization": "Bearer fixture-only-token"},
        }
        if method == "GET":
            result = alarm._curl_get_json(**kwargs, params={})
        else:
            result = alarm._curl_post_json(**kwargs, data={})
        assert result["code"] == 200
        assert received == ["Bearer fixture-only-token"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_fault_aggregate_retains_internal_gateway_error_stage(
    alarm, monkeypatch
):
    path = ROOT / (
        "deploy-all/qwenpaw/working/workspaces/fault/skills/"
        "alarm-analyst/scripts/analyze_alarm_context.py"
    )
    spec = importlib.util.spec_from_file_location(
        "phase_a_fault_context", path
    )
    context = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(context)
    monkeypatch.setattr(
        context, "_load_real_alarm_execute", lambda: alarm.execute
    )
    alarm.requests.get.return_value.json.return_value = {
        "code": 401,
        "msg": "expired",
    }
    result = context._query_alarms_for_res_id(
        res_id="fixture",
        manage_ip="127.0.0.1",
        begin_time="2026-11-12 10:00:00",
        end_time="2026-11-12 11:00:00",
    )
    assert result["code"] == 401
    assert result["diagnostic"]["stage"] == "inoe_gateway"
    merged = context._merge_related_alarm_results([result])
    assert merged["perResId"][0]["diagnostic"]["http_status"] == 200
    execution = context._build_alarm_query_execution(
        expected_res_ids=["fixture"], results=[result]
    )
    assert execution["failedIds"] == ["fixture"]
    assert execution["errors"][0]["diagnostic"]["error_code"] == (
        "INOE_AUTH_FAILED"
    )
