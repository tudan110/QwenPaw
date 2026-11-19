"""CMDB import children keep the caller's identity and fail closed."""

import importlib.util
import os
import sys
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def importer(monkeypatch, tmp_path):
    source = (
        Path(__file__).resolve().parents[4]
        / "src/qwenpaw/extensions/integrations/zgops_cmdb/resource_import.py"
    )
    name = "_resource_import_request_auth_test"
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    for prefix in ("QWENPAW", "COPAW"):
        for suffix in ("INOE", "ACCESS", "COLLABORATION"):
            monkeypatch.delenv(
                f"{prefix}_REQUEST_{suffix}_TOKEN", raising=False
            )
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("INOE_API_BASE_URL", "https://gateway.example")
    monkeypatch.setenv("INOE_API_TOKEN", "shared-admin-token")
    return module


@pytest.mark.parametrize("prefix", ["QWENPAW", "COPAW"])
def test_explicit_request_token_overrides_shared_credentials(
    importer,
    monkeypatch,
    prefix,
):
    monkeypatch.setenv(f"{prefix}_REQUEST_INOE_TOKEN", "Bearer caller-token")
    client = importer.ZgopsCmdbClient.from_skill_env()
    try:
        assert client.client.headers["Authorization"] == "Bearer caller-token"
        assert os.environ["INOE_API_TOKEN"] == "shared-admin-token"
    finally:
        client.close()


@pytest.mark.parametrize(
    "invalid",
    ["", " ", "Bearer", "Bearer ", "bad token", "bad\ntoken", "bad\ttoken"],
)
def test_invalid_request_token_cannot_fall_back_to_shared_account(
    importer,
    monkeypatch,
    invalid,
):
    monkeypatch.setenv("QWENPAW_REQUEST_INOE_TOKEN", invalid)
    monkeypatch.setenv("COPAW_REQUEST_INOE_TOKEN", "stale-legacy-token")
    with pytest.raises(PermissionError, match="禁止回退共享凭据"):
        importer.ZgopsCmdbClient.from_skill_env()


@pytest.mark.parametrize("prefix", ["QWENPAW", "COPAW"])
@pytest.mark.parametrize("kind", ["ACCESS", "COLLABORATION"])
def test_delegated_identity_without_inoe_token_fails_closed(
    importer,
    monkeypatch,
    prefix,
    kind,
):
    monkeypatch.setenv(
        f"{prefix}_REQUEST_{kind}_TOKEN", "delegated-local-token"
    )
    with pytest.raises(PermissionError, match="禁止回退共享凭据"):
        importer.ZgopsCmdbClient.from_skill_env()


@pytest.mark.parametrize("prefix", ["QWENPAW", "COPAW"])
def test_rejected_caller_token_is_never_retried_with_shared_account(
    importer,
    monkeypatch,
    prefix,
):
    monkeypatch.setenv(f"{prefix}_REQUEST_INOE_TOKEN", "expired-caller-token")
    requests = []

    def reject(request):
        requests.append(request)
        return httpx.Response(401, json={"error": "expired"})

    client = importer.ZgopsCmdbClient.from_skill_env()
    client.client.close()
    client.client = httpx.Client(
        transport=httpx.MockTransport(reject),
        headers={"Authorization": f"Bearer {client.token}"},
    )
    try:
        with pytest.raises(RuntimeError, match="expired"):
            client.get_ci_types()
    finally:
        client.close()
    assert len(requests) == 1
    assert (
        requests[0].headers["Authorization"] == "Bearer expired-caller-token"
    )


def test_metadata_cache_is_partitioned_by_request_identity(
    importer,
    monkeypatch,
):
    monkeypatch.setenv("QWENPAW_REQUEST_INOE_TOKEN", "caller-one")
    first = importer._resource_import_metadata_env_signature()
    importer._write_resource_import_metadata_cache(first, {"ciTypes": ["one"]})
    monkeypatch.setenv("QWENPAW_REQUEST_INOE_TOKEN", "caller-two")
    second = importer._resource_import_metadata_env_signature()
    assert first != second
    assert importer._read_resource_import_metadata_cache(second) is None


def test_standalone_background_mode_keeps_configured_credentials(importer):
    assert importer._parse_env()["INOE_API_TOKEN"] == "shared-admin-token"
