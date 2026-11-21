# -*- coding: utf-8 -*-
"""The offline alarm skills retain the same bounded-query semantics."""

import hashlib
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

ROOT = Path(__file__).resolve().parents[4]
WORKSPACES = ROOT / "deploy-all/qwenpaw/working/workspaces"


@pytest.mark.parametrize("workspace", ["query", "fault", "gateway"])
@pytest.mark.parametrize("status,kind", [
    (None, "windowed_uncleared"), ("0", "windowed_cleared"),
])
def test_skill_reports_actual_scope_and_window_total(
    monkeypatch, workspace, status, kind,
):
    path = WORKSPACES / workspace / "skills/real-alarm/scripts/get_alarms.py"
    spec = importlib.util.spec_from_file_location(
        f"alarm_scope_{workspace}", path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("USE_MOCK_DATA", "false")
    monkeypatch.setenv("PORTAL_REAL_ALARM_TIMEZONE_OFFSET", "5.5")
    response = Mock(status_code=200)
    response.json.return_value = {"code": 200, "total": 5954, "rows": []}
    module.requests = Mock(exceptions=requests.exceptions)
    module.requests.get.return_value = response
    result = module.execute(
        token="fixture", api_base_url="http://gateway.test",
        begin_time="2026-07-21 10:00:00", end_time="2026-07-22 10:00:00",
        alarm_status=status,
    )
    params = module.requests.get.call_args.kwargs["params"]
    assert result["total"] == 5954
    assert result["sourceStatus"] == "live"
    assert result["queryScope"]["kind"] == kind
    assert result["queryScope"]["startTime"] == params["beginTime"]
    assert result["queryScope"]["endTime"] == params["endTime"]
    assert result["queryScope"]["timezone"] == "UTC+05:30"
    assert result["queryScope"]["complete"] is False
    assert path.read_bytes() == (
        WORKSPACES / "query/skills/real-alarm/scripts/get_alarms.py"
    ).read_bytes()


@pytest.fixture
def alarm_cli(monkeypatch):
    path = WORKSPACES / "gateway/skills/real-alarm/scripts/get_alarms.py"
    spec = importlib.util.spec_from_file_location("alarm_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("USE_MOCK_DATA", "false")
    monkeypatch.setenv("PORTAL_REAL_ALARM_TIMEZONE_OFFSET", "8")
    monkeypatch.setenv("QWENPAW_PORTAL_REAL_ALARM_QUERY_WINDOW_HOURS", "72")
    monkeypatch.setattr(module, "get_token", lambda: "fixture")
    monkeypatch.setattr(module, "get_api_base_url", lambda: "http://gateway.test")

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 21, 14, 0, 0, tzinfo=tz)

    monkeypatch.setattr(module, "datetime", FixedClock)
    response = Mock(status_code=200)
    response.json.return_value = {"code": 200, "total": 42, "rows": []}
    module.requests = Mock(exceptions=requests.exceptions)
    module.requests.get.return_value = response
    return module


@pytest.mark.parametrize("flags,expected_start", [
    (["--last_24_hours"], "2026-11-20 14:00:00"),
    ([], "2026-11-18 14:00:00"),
])
def test_cli_resolves_relative_alarm_window(
    monkeypatch, capsys, alarm_cli, flags, expected_start,
):
    monkeypatch.setattr(sys, "argv", [
        "get_alarms.py", "--page_num", "1", "--page_size", "1", *flags,
    ])
    with pytest.raises(SystemExit) as exc:
        alarm_cli.main()
    assert exc.value.code == 0
    result = json.loads(capsys.readouterr().out)
    alarm_cli.requests.get.assert_called_once()
    params = alarm_cli.requests.get.call_args.kwargs["params"]
    assert params["beginTime"] == result["queryScope"]["startTime"] == expected_start
    assert params["endTime"] == result["queryScope"]["endTime"] == "2026-11-21 14:00:00"
    assert result["queryScope"]["timezone"] == "UTC+08:00"
    assert result["total"] == 42


@pytest.mark.parametrize("boundary", ["--begin_time", "--end_time"])
def test_cli_rejects_mixing_relative_and_absolute_windows(
    monkeypatch, alarm_cli, boundary,
):
    monkeypatch.setattr(sys, "argv", [
        "get_alarms.py", "--last_24_hours", boundary, "2026-11-21 14:00:00",
    ])
    with pytest.raises(SystemExit) as exc:
        alarm_cli.main()
    assert exc.value.code == 2
    alarm_cli.requests.get.assert_not_called()


def test_generated_seed_keeps_scope_metadata_and_identical_copies(tmp_path):
    builder_path = ROOT / "deploy-all/qwenpaw/scripts/build_universal_seed.py"
    spec = importlib.util.spec_from_file_location("c5_seed", builder_path)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    output = tmp_path / "seed"
    builder.build_seed(builder.argparse.Namespace(
        source=WORKSPACES.parent,
        builtin_root=ROOT / "src/qwenpaw/agents/skills",
        output=output, runtime_working_dir="/app/working", manifest=None,
    ))
    canonical = (
        WORKSPACES / "query/skills/real-alarm/scripts/get_alarms.py"
    ).read_bytes()
    manifest = json.loads((output / "seed-manifest.json").read_text(encoding="utf-8"))
    for workspace in ("query", "fault", "gateway", "order", "resource"):
        relative = Path(f"workspaces/{workspace}/skills/real-alarm/scripts/get_alarms.py")
        contents = (output / relative).read_bytes()
        assert contents == canonical
        assert b'"queryScope": query_scope' in contents
        assert b'"--last_24_hours"' in contents
        assert manifest["managed_files"][str(relative)]["sha256"] == (
            hashlib.sha256(contents).hexdigest()
        )
