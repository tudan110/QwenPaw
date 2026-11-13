# -*- coding: utf-8 -*-
"""The offline alarm skills retain the same bounded-query semantics."""

import importlib.util
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
    for workspace in ("query", "fault", "gateway", "order", "resource"):
        generated = output / (
            f"workspaces/{workspace}/skills/real-alarm/scripts/get_alarms.py"
        )
        assert generated.read_bytes() == canonical
        assert b'"queryScope": query_scope' in generated.read_bytes()
