import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

path = Path(__file__).parents[4] / "scripts/trusted-agent/run_acceptance.py"
spec = importlib.util.spec_from_file_location("trusted_acceptance", path)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_runner_refuses_management_mutations(tmp_path):
    cases = tmp_path / "cases.jsonl"
    cases.write_text(json.dumps({"id": "bad", "path": "/api/config", "method": "POST"}))
    with pytest.raises(ValueError):
        runner.load_cases(cases)


async def test_http_200_with_wrong_business_result_is_not_task_success(
    tmp_path, monkeypatch
):
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"answer": "wrong"})
    )
    monkeypatch.setattr(
        runner.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    args = SimpleNamespace(
        base_url="https://test",
        duration=0.01,
        timeout=1,
        concurrency=1,
        output=tmp_path / "result.json",
    )
    result = await runner.run(
        args,
        [
            {
                "id": "q1",
                "path": "/api/portal/knowledge-base/query",
                "expected_json": {"answer": "right"},
            }
        ],
    )
    assert result["requests"] > 0
    assert result["http_ok"] == result["requests"]
    assert result["task_judged"] == result["requests"]
    assert result["task_passed"] == 0
