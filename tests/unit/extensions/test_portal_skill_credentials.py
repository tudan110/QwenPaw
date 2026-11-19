"""Portal bridge credentials without importing its unrelated HTTP routes."""

# flake8: noqa: F811

import ast
import os
from pathlib import Path

import pytest

from test_collaboration_access_flow import flow  # noqa: F401


@pytest.fixture
def bridge_env(flow):  # noqa: F811
    path = (
        Path(__file__).resolve().parents[3]
        / "src/qwenpaw/extensions/api/portal_backend.py"
    )
    tree = ast.parse(path.read_text())
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_skill_subprocess_env"
    )
    namespace = {"__package__": "qwenpaw.extensions.api", "os": os}
    exec(
        compile(
            ast.Module(body=[function], type_ignores=[]), str(path), "exec"
        ),
        namespace,
    )
    return namespace["_skill_subprocess_env"]


def test_portal_bridges_forward_request_identity_not_shared_token(
    flow, bridge_env, monkeypatch
):  # noqa: F811
    monkeypatch.setenv("INOE_API_TOKEN", "shared-fixture")
    identity = flow.access.AccessIdentity(
        user={"userId": 7}, inoe_token="caller-fixture"
    )
    reset = flow.access.CURRENT_IDENTITY.set(identity)
    try:
        env = bridge_env()
        assert env["INOE_API_TOKEN"] == "caller-fixture"
        assert env["QWENPAW_REQUEST_INOE_TOKEN"] == "caller-fixture"
        assert env["PYTHONIOENCODING"] == "utf-8"
        assert env["PYTHONUTF8"] == "1"
        assert os.environ["INOE_API_TOKEN"] == "shared-fixture"
    finally:
        flow.access.CURRENT_IDENTITY.reset(reset)


def test_portal_bridge_missing_business_token_cannot_fall_back(
    flow, bridge_env, monkeypatch
):  # noqa: F811
    monkeypatch.setenv("INOE_API_TOKEN", "shared-fixture")
    identity = flow.access.AccessIdentity(user={"userId": 7}, inoe_token="")
    reset = flow.access.CURRENT_IDENTITY.set(identity)
    try:
        env = bridge_env()
        assert env["INOE_API_TOKEN"] == ""
        assert env["QWENPAW_REQUEST_INOE_TOKEN"] == ""
    finally:
        flow.access.CURRENT_IDENTITY.reset(reset)


def test_portal_bridge_collaboration_lease_remains_scoped(
    flow, bridge_env
):  # noqa: F811
    with flow.lease.scheduled_collaboration("fixture-job", 120):
        env = bridge_env()
        assert (
            env[flow.lease.ENV_KEY]
            == flow.lease.CURRENT_COLLABORATION_TOKEN.get()
        )
        assert env["QWENPAW_REQUEST_INOE_TOKEN"] == ""
