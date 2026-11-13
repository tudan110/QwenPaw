"""Production read abilities are explicit and do not enable writes or shells."""

import hashlib
import importlib.util
import json
import shlex
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.drivers.contracts import DriverCard
from qwenpaw.drivers.handlers.mcp import MCPDriverHandler
from qwenpaw.extensions.api.access_session import AccessIdentity, CURRENT_IDENTITY
from qwenpaw.extensions.security import execution_policy
from qwenpaw.extensions.security.business_reads import MCP_READ_TOOLS

ROOT = Path(__file__).resolve().parents[4]


async def test_production_shell_executes_the_checked_arguments_literally(
    tmp_path, monkeypatch
):
    from qwenpaw.agents.tools import shell

    script = tmp_path / "get_devices.py"
    script.write_text("print('fixture')")
    monkeypatch.setenv(
        "QWENPAW_ALLOWED_SCRIPT_HASHES",
        json.dumps({str(script): hashlib.sha256(script.read_bytes()).hexdigest()}),
    )
    command = f'python3 {script} "a?b=x&c=*"'
    execution_policy.check_shell(command)
    process = AsyncMock()
    process.communicate.return_value = (b"fixture", b"")
    process.returncode = 0
    create = AsyncMock(return_value=process)
    monkeypatch.setattr(shell.asyncio, "create_subprocess_shell", create)
    await shell.execute_shell_command(command, cwd=tmp_path)
    assert create.await_args.args[0] == shlex.join(shlex.split(command))
    assert shlex.split(create.await_args.args[0])[-1] == "a?b=x&c=*"


@pytest.fixture(autouse=True)
def ordinary_user(monkeypatch):
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "1")
    monkeypatch.delenv("QWENPAW_READONLY_TOOL_NAMES", raising=False)
    token = CURRENT_IDENTITY.set(
        AccessIdentity(user={"userId": 2}, inoe_token="fixture")
    )
    yield
    CURRENT_IDENTITY.reset(token)


@pytest.mark.parametrize("name", sorted(MCP_READ_TOOLS))
async def test_reviewed_mcp_queries_work_for_ordinary_users(name):
    assert await execution_policy.check_tool(name, {}) is False


@pytest.mark.parametrize(
    "name",
    [
        "order__createWorkOrder",
        "cmdb-query__cmdbLogin",
        "cmdb-query__deleteCi",
        "evil__getDeleteEverything",
    ],
)
async def test_read_declarations_do_not_grant_other_operations(name):
    with pytest.raises(PermissionError):
        await execution_policy.check_tool(name, {})


async def test_actual_mcp_driver_calls_read_tool_without_disabling_guards():
    handler = MCPDriverHandler(
        DriverCard(name="resource", protocol="mcp", endpoint={}), MagicMock()
    )
    handler._client = AsyncMock()
    handler._client.call_tool.return_value = {"rows": ["fixture"]}
    result = await handler._execute(
        None, None, tool_name="queryMonitoringTopology", arguments={}
    )
    assert result == {"rows": ["fixture"]}
    handler._client.call_tool.assert_awaited_once_with("queryMonitoringTopology", {})


@pytest.mark.parametrize(
    "name, arguments",
    [
        ("get_devices.py", "--page_num 1 --page_size 1"),
        ("analyze_devices.py", "--mode summary --output markdown"),
        ("monitoring_overview.py", "topology --output markdown"),
        ("resource_insight.py", "summary --output markdown"),
        ("cmdb_read.py", "list-models"),
        ("cmdb_read.py", 'fetch "/api/v0.1/ci/s?q=_type:mysql&page=1&count=100"'),
        ("order_workflow.py", "stats --output markdown"),
    ],
)
def test_official_queries_with_matching_managed_seed(
    tmp_path, monkeypatch, name, arguments
):
    working = tmp_path / "working"
    relative = f"workspaces/query/skills/fixture/scripts/{name}"
    script = working / relative
    script.parent.mkdir(parents=True)
    script.write_text("print('fixture')\n")
    checksum = hashlib.sha256(script.read_bytes()).hexdigest()
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "seed-manifest.json").write_text(
        json.dumps(
            {
                "managed_files": {relative: {"sha256": checksum}},
                "managed_skills": {
                    "workspaces/query/skills/fixture": {"files": {relative: checksum}}
                },
            }
        )
    )
    monkeypatch.setattr(execution_policy, "WORKING_DIR", working)
    monkeypatch.setenv("QWENPAW_SKILL_SEED_PATH", str(seed))
    monkeypatch.setenv("QWENPAW_ALLOWED_SCRIPT_HASHES", "{}")
    execution_policy.check_shell(f"python3 {script} {arguments}")
    with pytest.raises(PermissionError):
        execution_policy.check_shell(f"python3 {script} {arguments}; id")
    script.write_text("print('modified')\n")
    with pytest.raises(PermissionError):
        execution_policy.check_shell(f"python3 {script} {arguments}")


def test_mixed_workflow_rejects_write_even_with_approved_script(tmp_path, monkeypatch):
    script = tmp_path / "order_workflow.py"
    script.write_text("print('fixture')")
    monkeypatch.setenv(
        "QWENPAW_ALLOWED_SCRIPT_HASHES",
        json.dumps({str(script): hashlib.sha256(script.read_bytes()).hexdigest()}),
    )
    with pytest.raises(PermissionError):
        execution_policy.check_shell(
            f"python3 {script} create --payload-file /tmp/request.json"
        )


def test_relative_interpreter_cannot_change_identity_with_command_cwd(
    tmp_path, monkeypatch
):
    import sys

    interpreter = tmp_path / "python"
    interpreter.symlink_to(sys.executable)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(PermissionError):
        execution_policy.check_shell("./python get_devices.py")


def test_inspection_read_requires_no_notifications_and_trusted_shared_helpers(
    tmp_path, monkeypatch
):
    root = tmp_path / "working/workspaces"
    script = (
        root
        / "inspection/skills/inspection-analyst/scripts/inspect_resource_metrics.py"
    )
    metric = root / "fault/skills/alarm-analyst/scripts/get_metric_definitions.py"
    cmdb = root / "inspection/skills/zgops-cmdb/scripts/cmdb_read.py"
    hashes = {}
    for target in (script, metric, cmdb):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("print('fixture')")
        hashes[str(target)] = hashlib.sha256(target.read_bytes()).hexdigest()
    monkeypatch.setenv("QWENPAW_ALLOWED_SCRIPT_HASHES", json.dumps(hashes))
    command = f"python3 {script} --metric-type mysql --res-id 1"
    with pytest.raises(PermissionError):
        execution_policy.check_shell(command)
    execution_policy.check_shell(command + " --no-notify")
    metric.write_text("print('modified')")
    with pytest.raises(PermissionError):
        execution_policy.check_shell(command + " --no-notify")


@pytest.fixture(params=["gateway", "query", "resource", "fault", "inspection"])
def cmdb_read(request, monkeypatch):
    directory = (
        ROOT
        / f"deploy-all/qwenpaw/working/workspaces/{request.param}/skills/zgops-cmdb/scripts"
    )
    monkeypatch.syspath_prepend(str(directory))
    for name in ("zgops_http", "cmdb_output"):
        monkeypatch.delitem(__import__("sys").modules, name, raising=False)
    spec = importlib.util.spec_from_file_location(
        "cmdb_read_fixture", directory / "cmdb_read.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cmdb_read_dispatcher_only_accepts_fixed_read_routes(cmdb_read):
    assert cmdb_read.read_path("list-models", []) == "/api/v0.1/ci_types?per_page=200"
    assert cmdb_read.read_path(
        "fetch", ["/api/v0.1/ci/s?q=_type:mysql&page=1"]
    ).startswith("/api/")
    for command, arguments in [
        ("login", []),
        ("delete", ["1"]),
        ("fetch", ["https://outside.example/api/v0.1/ci_types"]),
        ("fetch", ["//outside.example/api/v0.1/ci_types"]),
        ("fetch", ["/api/v0.1/ci/1/delete"]),
        ("fetch", ["/api/v0.1/ci_types/%2e%2e/auth"]),
        ("model-attributes", ["1/../../auth"]),
    ]:
        with pytest.raises(ValueError):
            cmdb_read.read_path(command, arguments)


def test_cmdb_read_entry_uses_configured_gateway_and_bearer(
    cmdb_read, monkeypatch, capsys
):
    import requests
    import sys

    session = requests.Session()
    response = requests.Response()
    response.status_code = 200
    response._content = b'{"ci_types": [{"id": 1, "name": "fixture"}]}'
    fetch = MagicMock(return_value=response)
    monkeypatch.setattr(cmdb_read, "create_session", lambda: session)
    monkeypatch.setattr(cmdb_read, "fetch_with_auth_fallback", fetch)
    monkeypatch.setenv("INOE_API_BASE_URL", "http://fixture-gateway:8080")
    monkeypatch.setenv("INOE_API_TOKEN", "fixture-user-token")
    monkeypatch.setattr(sys, "argv", ["cmdb_read.py", "list-models"])
    assert cmdb_read.main() == 0
    assert session.headers["Authorization"] == "Bearer fixture-user-token"
    fetch.assert_called_once_with(
        session,
        base_url="http://fixture-gateway:8080/cmdb",
        path="/api/v0.1/ci_types?per_page=200",
    )
    assert "fixture" in capsys.readouterr().out
