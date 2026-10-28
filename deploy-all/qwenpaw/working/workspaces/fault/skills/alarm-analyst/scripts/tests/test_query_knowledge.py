import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

SCRIPT = Path(__file__).resolve().parents[1] / "query_knowledge.py"
SPEC = importlib.util.spec_from_file_location("alarm_query_knowledge", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
knowledge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(knowledge)
LAST_API_BASE_URL = knowledge._last_api_base_url

API_BASE = "http://127.0.0.1:8088/api/portal"


@pytest.fixture(autouse=True)
def isolate_config(monkeypatch):
    for name in (
        "ALARM_ANALYST_KNOWLEDGE_API_BASE_URL",
        "ALARM_ANALYST_KNOWLEDGE_API_TOKEN",
        "ALARM_ANALYST_KNOWLEDGE_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(knowledge, "_last_api_base_url", lambda: API_BASE)


@pytest.fixture
def payload():
    return {
        "query_id": "query-1",
        "summary": "找到相关资料",
        "relevant_evidence": [
            {
                "evidence_id": "12",
                "confidence_score": 0.6,
                "confidence_level": "medium",
                "chunk_text": "先核对数据库实例及锁等待链。",
                "citation": {
                    "source_label": "PaaS层故障根因分析.md",
                    "section_path": "数据库锁等待",
                    "locator": "section:数据库",
                },
            }
        ],
        "flags": {"insufficient_evidence": False},
        "evidence_boundary_statement": "只作排查参考。",
    }


def mock_post(monkeypatch, payload, status=200):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload
    response.__enter__.return_value = response
    post = MagicMock(return_value=response)
    monkeypatch.setattr(knowledge.requests, "post", post)
    return post, response


def test_query_preserves_original_evidence_and_sends_one_read_only_request(
    monkeypatch, payload
):
    post, _ = mock_post(monkeypatch, payload)

    result = knowledge.query_knowledge(" MySQL 锁等待 ")

    assert result["status"] == "retrieved"
    assert result["attempted"] is True
    assert result["result"] == payload
    assert result["query"] == "MySQL 锁等待"
    post.assert_called_once_with(
        f"{API_BASE}/knowledge-base/query",
        json={"query": "MySQL 锁等待", "filters": {}},
        headers={"Accept": "application/json", "X-Agent-Id": "fault"},
        timeout=60.0,
        allow_redirects=False,
    )


def test_empty_result_is_not_a_transport_failure(monkeypatch, payload):
    payload["relevant_evidence"] = []
    payload["flags"]["insufficient_evidence"] = True
    mock_post(monkeypatch, payload)

    result = knowledge.query_knowledge("未覆盖的故障")

    assert result["status"] == "no_match"
    assert result["result"]["flags"]["insufficient_evidence"] is True
    assert "error" not in result


def test_insufficient_evidence_keeps_candidates_without_claiming_reliability(
    monkeypatch, payload
):
    payload["flags"]["insufficient_evidence"] = True
    mock_post(monkeypatch, payload)
    result = knowledge.query_knowledge("MySQL 锁等待")
    assert result["status"] == "insufficient_evidence"
    assert result["result"] == payload


def test_low_relevance_is_not_upgraded_to_reliable_match(monkeypatch, payload):
    payload["relevant_evidence"][0]["confidence_level"] = "low"
    payload["relevant_evidence"][0]["confidence_score"] = 0.25
    mock_post(monkeypatch, payload)
    result = knowledge.query_knowledge("MySQL 锁等待")
    assert result["status"] == "retrieved"
    assert (
        result["result"]["relevant_evidence"][0]["confidence_level"] == "low"
    )


@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 500])
def test_http_errors_and_redirects_are_not_misses_or_retried(
    monkeypatch, status
):
    post, response = mock_post(monkeypatch, {}, status=status)
    result = knowledge.query_knowledge("MySQL 锁等待")
    assert result["status"] == "error"
    assert str(status) in result["error"]
    assert "result" not in result
    post.assert_called_once()
    response.json.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        requests.Timeout("private-url"),
        requests.ConnectionError("private-url"),
        requests.exceptions.SSLError("private-url"),
    ],
)
def test_network_failure_is_explicit_and_never_exposes_request_details(
    monkeypatch, error
):
    post = MagicMock(side_effect=error)
    monkeypatch.setattr(knowledge.requests, "post", post)
    result = knowledge.query_knowledge("MySQL 锁等待")
    assert result["status"] == "error"
    assert result["attempted"] is True
    assert "result" not in result
    assert "private-url" not in json.dumps(result)
    post.assert_called_once()


@pytest.mark.parametrize(
    "invalid",
    [
        [],
        {},
        {"query_id": "q", "relevant_evidence": [], "flags": {}},
        {
            "query_id": "q",
            "relevant_evidence": ["invalid"],
            "flags": {"insufficient_evidence": False},
        },
        {
            "query_id": "q",
            "relevant_evidence": [{"evidence_id": "1"}],
            "flags": {"insufficient_evidence": False},
        },
    ],
)
def test_malformed_contract_is_not_an_empty_match(monkeypatch, invalid):
    mock_post(monkeypatch, invalid)
    result = knowledge.query_knowledge("MySQL 锁等待")
    assert result["status"] == "error"
    assert "响应" in result["error"]


def test_non_json_response_is_explicit(monkeypatch):
    _, response = mock_post(monkeypatch, None)
    response.json.side_effect = ValueError("invalid JSON")
    assert knowledge.query_knowledge("锁等待")["status"] == "error"


def test_requests_json_decode_error_is_not_a_network_failure(monkeypatch):
    _, response = mock_post(monkeypatch, None)
    response.json.side_effect = requests.exceptions.JSONDecodeError(
        "Expecting value", "<html>error</html>", 0
    )
    result = knowledge.query_knowledge("锁等待")
    assert result["status"] == "error"
    assert "JSON" in result["error"]
    assert "<html>" not in result["error"]


@pytest.mark.parametrize(
    "address,base",
    [
        (("127.0.0.1", 18088), "http://127.0.0.1:18088/api/portal"),
        (("0.0.0.0", 8088), "http://127.0.0.1:8088/api/portal"),
        (("::", 8088), "http://[::1]:8088/api/portal"),
        (("::1", 8088), "http://[::1]:8088/api/portal"),
    ],
)
def test_application_endpoint_is_reused(monkeypatch, tmp_path, address, base):
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(
        json.dumps({"last_api": {"host": address[0], "port": address[1]}})
    )
    assert LAST_API_BASE_URL() == base


def test_missing_application_endpoint_is_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text("{}")
    with pytest.raises(
        ValueError, match="ALARM_ANALYST_KNOWLEDGE_API_BASE_URL"
    ):
        LAST_API_BASE_URL()


@pytest.mark.parametrize(
    "primary,legacy",
    [("primary", "legacy"), (None, "legacy"), ("", "legacy")],
)
def test_working_directory_precedence(monkeypatch, tmp_path, primary, legacy):
    monkeypatch.setattr(knowledge.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("QWENPAW_WORKING_DIR", raising=False)
    monkeypatch.setenv("COPAW_WORKING_DIR", str(tmp_path / legacy))
    if primary is not None:
        monkeypatch.setenv(
            "QWENPAW_WORKING_DIR",
            str(tmp_path / primary) if primary else "",
        )
    for folder, port in (
        ("primary", 18001),
        ("legacy", 18002),
        (".qwenpaw", 18003),
    ):
        target = tmp_path / folder
        target.mkdir()
        (target / "config.json").write_text(
            json.dumps({"last_api": {"host": "127.0.0.1", "port": port}})
        )
    expected = 18001 if primary else 18002 if primary is None else 18003
    assert LAST_API_BASE_URL() == f"http://127.0.0.1:{expected}/api/portal"


@pytest.mark.parametrize("legacy_exists", [False, True])
def test_default_and_copaw_home_compatibility(
    monkeypatch, tmp_path, legacy_exists
):
    monkeypatch.delenv("QWENPAW_WORKING_DIR", raising=False)
    monkeypatch.delenv("COPAW_WORKING_DIR", raising=False)
    monkeypatch.setattr(knowledge.Path, "home", lambda: tmp_path)
    for folder, port in ((".qwenpaw", 18001), (".copaw", 18002)):
        if folder == ".copaw" and not legacy_exists:
            continue
        target = tmp_path / folder
        target.mkdir()
        (target / "config.json").write_text(
            json.dumps({"last_api": {"host": "127.0.0.1", "port": port}})
        )
    port = 18002 if legacy_exists else 18001
    assert LAST_API_BASE_URL() == f"http://127.0.0.1:{port}/api/portal"


def test_legacy_endpoint_fields_remain_supported(monkeypatch, tmp_path):
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(
        json.dumps({"last_api_host": "0.0.0.0", "last_api_port": "18088"})
    )
    assert LAST_API_BASE_URL() == "http://127.0.0.1:18088/api/portal"


def test_persisted_endpoint_query_is_read_only(monkeypatch, tmp_path, payload):
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(tmp_path))
    monkeypatch.setattr(knowledge, "_last_api_base_url", LAST_API_BASE_URL)
    config = tmp_path / "config.json"
    original = json.dumps({"last_api": {"host": "0.0.0.0", "port": 18088}})
    config.write_text(original)
    post, _ = mock_post(monkeypatch, payload)

    result = knowledge.query_knowledge("物理机 CPU超限")

    assert result["status"] == "retrieved"
    assert result["attempted"] is True
    assert result["result"] == payload
    assert post.call_args.args[0] == (
        "http://127.0.0.1:18088/api/portal/knowledge-base/query"
    )
    post.assert_called_once()
    assert config.read_text() == original
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.json"]


@pytest.mark.parametrize(
    "config",
    [
        [],
        {"last_api": ["invalid"]},
        {"last_api": {"host": ["invalid"], "port": 8088}},
        {"last_api": {"host": "localhost", "port": True}},
        {"last_api": {"host": "localhost", "port": 0}},
        {"last_api": {"host": "localhost", "port": 65536}},
        {"last_api": {"host": "localhost", "port": "8088.5"}},
    ],
)
def test_bad_application_config_does_not_send_request(
    monkeypatch, tmp_path, config
):
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(tmp_path))
    monkeypatch.setattr(knowledge, "_last_api_base_url", LAST_API_BASE_URL)
    (tmp_path / "config.json").write_text(json.dumps(config))
    post = MagicMock()
    monkeypatch.setattr(knowledge.requests, "post", post)

    result = knowledge.query_knowledge("CPU超限")

    assert result["status"] == "error"
    assert result["attempted"] is False
    post.assert_not_called()


@pytest.mark.parametrize("failure", ["missing", "invalid_json", "permission"])
def test_endpoint_read_failures_are_explicit(monkeypatch, tmp_path, failure):
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(tmp_path))
    monkeypatch.setattr(knowledge, "_last_api_base_url", LAST_API_BASE_URL)
    if failure == "invalid_json":
        (tmp_path / "config.json").write_text("{")
    elif failure == "permission":

        def denied(*args, **kwargs):
            raise PermissionError("configuration read denied")

        monkeypatch.setattr(knowledge.Path, "read_text", denied)
    post = MagicMock()
    monkeypatch.setattr(knowledge.requests, "post", post)

    result = knowledge.query_knowledge("CPU超限")

    assert result["status"] == "error"
    assert result["attempted"] is False
    assert result["error"]
    post.assert_not_called()


def test_standalone_endpoint_discovery_does_not_bootstrap_application(
    tmp_path,
):
    fake_package = tmp_path / "qwenpaw"
    fake_package.mkdir()
    (fake_package / "__init__.py").write_text(
        'raise RuntimeError("application bootstrap must not run")\n'
    )
    (tmp_path / "config.json").write_text(
        json.dumps({"last_api": {"host": "127.0.0.1", "port": 18088}})
    )
    source = (
        "import importlib.util,sys\n"
        f"spec=importlib.util.spec_from_file_location('helper',{str(SCRIPT)!r})\n"
        "module=importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "print(module._last_api_base_url())\n"
        "assert 'qwenpaw' not in sys.modules\n"
    )
    env = {
        **os.environ,
        "QWENPAW_WORKING_DIR": str(tmp_path),
        "PYTHONPATH": str(tmp_path),
    }
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "http://127.0.0.1:18088/api/portal"
    assert result.stderr == ""
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "config.json",
        "qwenpaw",
    ]


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout_never_sends_request(monkeypatch, timeout):
    post = MagicMock()
    monkeypatch.setattr(knowledge.requests, "post", post)
    result = knowledge.query_knowledge("锁等待", timeout_seconds=timeout)
    assert result["status"] == "error"
    assert result["attempted"] is False
    post.assert_not_called()


@pytest.mark.parametrize(
    "base",
    [
        "file:///tmp/knowledge",
        "http://user:secret@example.com/api/portal",
        "https://example.com/api/portal?token=secret",
        "http://",
    ],
)
def test_invalid_url_never_sends_request(monkeypatch, base):
    post = MagicMock()
    monkeypatch.setattr(knowledge.requests, "post", post)
    result = knowledge.query_knowledge("锁等待", api_base_url=base)
    assert result["status"] == "error"
    assert result["attempted"] is False
    assert "secret" not in result["error"]
    post.assert_not_called()


def test_explicit_config_precedes_env_and_default(monkeypatch, payload):
    monkeypatch.setenv(
        "ALARM_ANALYST_KNOWLEDGE_API_BASE_URL",
        "https://env.example.com/api/portal",
    )
    monkeypatch.setenv("ALARM_ANALYST_KNOWLEDGE_API_TOKEN", "test-token")
    monkeypatch.setenv("ALARM_ANALYST_KNOWLEDGE_TIMEOUT_SECONDS", "25")
    monkeypatch.setenv("INOE_API_TOKEN", "must-not-forward")
    post, _ = mock_post(monkeypatch, payload)
    knowledge.query_knowledge(
        "锁等待",
        api_base_url="https://explicit.example.com/prefix/api/portal/",
        timeout_seconds=10,
    )
    assert post.call_args.args[0].startswith("https://explicit.example.com/")
    assert post.call_args.kwargs["timeout"] == 10
    assert post.call_args.kwargs["headers"]["Authorization"] == (
        "Bearer test-token"
    )
    assert "must-not-forward" not in str(post.call_args)


def test_env_url_and_timeout_are_used(monkeypatch, payload):
    monkeypatch.setenv(
        "ALARM_ANALYST_KNOWLEDGE_API_BASE_URL",
        "https://env.example.com/api/portal",
    )
    monkeypatch.setenv("ALARM_ANALYST_KNOWLEDGE_TIMEOUT_SECONDS", "25")
    post, _ = mock_post(monkeypatch, payload)
    knowledge.query_knowledge("锁等待")
    assert post.call_args.args[0] == (
        "https://env.example.com/api/portal/knowledge-base/query"
    )
    assert post.call_args.kwargs["timeout"] == 25


def test_missing_address_is_not_claimed_as_executed(monkeypatch):
    def missing():
        raise ValueError("未取得应用地址")

    monkeypatch.setattr(knowledge, "_last_api_base_url", missing)
    post = MagicMock()
    monkeypatch.setattr(knowledge.requests, "post", post)
    result = knowledge.query_knowledge("锁等待")
    assert result["status"] == "error"
    assert result["attempted"] is False
    post.assert_not_called()


def test_empty_query_is_not_sent(monkeypatch):
    post = MagicMock()
    monkeypatch.setattr(knowledge.requests, "post", post)
    result = knowledge.query_knowledge(" ")
    assert result["status"] == "error"
    assert result["attempted"] is False
    post.assert_not_called()


@pytest.mark.parametrize("status,expected_code", [(200, 0), (503, 1)])
def test_cli_json_and_exit_code(
    monkeypatch, capsys, payload, status, expected_code
):
    mock_post(monkeypatch, payload, status)
    assert knowledge.main(["--query", "数据库锁等待"]) == expected_code
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["query"] == "数据库锁等待"
    assert bool(output.err) == (expected_code == 1)
