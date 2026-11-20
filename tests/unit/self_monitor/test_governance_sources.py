from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers import tools
from qwenpaw.extensions.api import self_monitor_api
from qwenpaw.extensions.api.access_policy import requires_admin
from qwenpaw.self_monitor.alerts import AlertRule


def _client(router, prefix=""):
    app = FastAPI()
    app.include_router(router, prefix=prefix)
    return TestClient(app)


def test_inventory_exposes_only_applicable_direct_dependency_metadata(monkeypatch):
    monkeypatch.setattr(tools.metadata, "requires", lambda _: [
        "present>=2", "missing", 'dev-only; extra == "dev"',
        "reference @ https://user:secret@example.invalid/file.whl",
    ])

    def version(name):
        if name == "present":
            return "2.1"
        raise tools.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(tools.metadata, "version", version)
    path = "/api/tools/component-dependencies"
    assert requires_admin("GET", path)
    response = _client(tools.router, "/api").get(path)
    assert response.status_code == 200
    assert response.json() == {"available": True, "items": [
        {"name": "missing", "declared": "", "installed": None},
        {"name": "present", "declared": ">=2", "installed": "2.1"},
        {"name": "reference", "declared": "", "installed": None},
    ]}
    assert "secret" not in response.text


def test_runtime_rule_endpoint_uses_loaded_rules_and_respects_disabled_state(monkeypatch):
    rule = AlertRule("test-rule", "Test", "l3", "warn", "counter_delta", "sample", {"status": "429"}, ">=", 8, 120, 30)
    monkeypatch.setattr(self_monitor_api, "SELF_MONITOR_ENABLED", True)
    monkeypatch.setattr(self_monitor_api, "get_self_monitor", lambda: SimpleNamespace(alert_engine=SimpleNamespace(rules=[rule])))
    path = "/api/portal/self-monitor/alert-rules"
    assert requires_admin("GET", path)
    client = _client(self_monitor_api.router)
    response = client.get(path).json()
    assert response["enabled"] is True
    assert response["items"] == [{
        "id": "test-rule", "name": "Test", "severity": "warn", "kind": "counter_delta", "metric": "sample", "labels": {"status": "429"},
        "op": ">=", "threshold": 8, "windowS": 120, "forS": 30,
    }]
    monkeypatch.setattr(self_monitor_api, "SELF_MONITOR_ENABLED", False)
    assert client.get(path).json() == {"enabled": False, "evaluationIntervalS": None, "items": []}
