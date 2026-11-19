"""Credential-safe cache persistence using the real import implementation."""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


@pytest.fixture
def cache(monkeypatch, tmp_path):
    source = (
        Path(__file__).resolve().parents[4]
        / "src/qwenpaw/extensions/integrations/zgops_cmdb/resource_import.py"
    )
    name = "_resource_import_metadata_cache_test"
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("INOE_API_BASE_URL", "https://gateway.example")
    monkeypatch.setenv("INOE_API_TOKEN", "test-private-bearer-token")
    monkeypatch.setattr(module, "_METADATA_CACHE_TTL_SECONDS", 300)
    return module


def test_cache_roundtrip_never_persists_connection_credentials(cache):
    signature = cache._resource_import_metadata_env_signature()
    metadata = {"connected": True, "ciTypes": [{"name": "networkdevice"}]}
    cache._write_resource_import_metadata_cache(signature, metadata)

    persisted = cache._resource_import_metadata_cache_path().read_text()
    assert "test-private-bearer-token" not in persisted
    assert "https://gateway.example" not in persisted
    assert cache._is_resource_import_metadata_signature(signature)
    assert cache._read_resource_import_metadata_cache(signature) == metadata


def test_cache_does_not_cross_users_or_backends(cache, monkeypatch):
    original = cache._resource_import_metadata_env_signature()
    cache._write_resource_import_metadata_cache(original, {"ciTypes": []})
    assert cache._resource_import_metadata_env_signature() == original

    monkeypatch.setenv("INOE_API_TOKEN", "other-private-token")
    other_user = cache._resource_import_metadata_env_signature()
    assert other_user != original
    assert cache._read_resource_import_metadata_cache(other_user) is None

    monkeypatch.setenv("INOE_API_TOKEN", "test-private-bearer-token")
    monkeypatch.setenv("INOE_API_BASE_URL", "https://other-gateway.example")
    other_backend = cache._resource_import_metadata_env_signature()
    assert other_backend not in {original, other_user}
    assert cache._read_resource_import_metadata_cache(other_backend) is None


@pytest.mark.parametrize("expired", [False, True])
def test_legacy_cache_credentials_are_removed_without_reuse(cache, expired):
    path = cache._resource_import_metadata_cache_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "envSignature": "https://gateway.example|old-private-token",
                "metadata": {"ciTypes": [{"name": "old-user-data"}]},
            },
        ),
    )
    if expired:
        os.utime(path, (1, 1))

    assert (
        cache._read_resource_import_metadata_cache(
            cache._resource_import_metadata_env_signature(),
        )
        is None
    )
    assert not path.exists()


def test_cache_writer_refuses_legacy_raw_token_signature(cache):
    cache._write_resource_import_metadata_cache(
        "https://gateway.example|private-token",
        {"ciTypes": []},
    )
    assert not cache._resource_import_metadata_cache_path().exists()
