"""The sample observation script records results without leaking response data."""
from importlib.util import module_from_spec, spec_from_file_location
import io
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

_path = Path(__file__).resolve().parents[4] / "scripts/trusted-agent/measure_sample.py"
_spec = spec_from_file_location("measure_sample", _path)
measure_sample = module_from_spec(_spec)
_spec.loader.exec_module(measure_sample)


@pytest.mark.asyncio
async def test_expected_status_and_no_redirect_or_credential_in_raw_events(monkeypatch):
    monkeypatch.setenv("QWENPAW_EVAL_ACCESS_TOKEN", "local-fixture-token")
    calls = []

    def handle(request):
        calls.append(request.url)
        assert request.headers["x-qwenpaw-access-token"] == "local-fixture-token"
        if len(calls) == 1:
            return httpx.Response(302, headers={"Location": "https://other.invalid/"})
        return httpx.Response(200, text="private body not needed for HTTP timing")

    args = SimpleNamespace(
        url="https://sample.invalid/health", duration=.08, interval=.02,
        concurrency=1, timeout=1, expected_status=200, sample_version="sample-a",
    )
    stream = io.StringIO()
    report = await measure_sample.measure(args, stream, transport=httpx.MockTransport(handle))
    rows = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert len(rows) >= 2 and len(rows) == report["requests"]
    assert report["failures"] == 1 and report["successes"] == len(rows) - 1
    assert rows[0]["status"] == 302 and rows[0]["expected_status_met"] is False
    assert {url.host for url in calls} == {"sample.invalid"}
    assert "local-fixture-token" not in stream.getvalue()
    assert "private body" not in stream.getvalue()
