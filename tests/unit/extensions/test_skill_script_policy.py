"""Exercise bundled scripts with real seed integrity and identity gates."""

import hashlib
import importlib.util
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_report_export_flow import flow  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def scripts(flow, monkeypatch, tmp_path):  # noqa: F811
    source = ROOT / "src/qwenpaw/extensions/security/managed_integrity.py"
    spec = importlib.util.spec_from_file_location("managed_test", source)
    integrity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(integrity)
    monkeypatch.setattr(flow.policy, "inspect_skill", integrity.inspect_skill)
    monkeypatch.setenv("QWENPAW_ALLOWED_SCRIPT_HASHES", "{}")
    seed = tmp_path / "seed"
    seed.mkdir()
    monkeypatch.setenv("QWENPAW_SKILL_SEED_PATH", str(seed))
    workspace = tmp_path / "workspaces/resource"
    workspace.mkdir(parents=True)
    monkeypatch.setattr(
        flow.policy, "get_current_workspace_dir", lambda: workspace
    )
    manifest = {"managed_files": {}, "managed_skills": {}}

    def declare(path):
        relative = str(path.relative_to(tmp_path))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest["managed_files"][relative] = {"sha256": digest}
        skill = str(Path(*Path(relative).parts[:4]))
        manifest["managed_skills"].setdefault(skill, {"files": {}})["files"][
            relative
        ] = digest
        (seed / "seed-manifest.json").write_text(json.dumps(manifest))

    def create(name, *, actual=False):
        contracts = sys.modules["qwenpaw.extensions.security.skill_scripts"]
        skill = contracts.SCRIPT_SKILLS[name]
        target = workspace / "skills" / skill
        if actual:
            matches = list(
                (ROOT / "deploy-all/qwenpaw/working/workspaces").glob(
                    f"*/skills/{skill}"
                )
            )
            shutil.copytree(
                matches[0],
                target,
                ignore=shutil.ignore_patterns("__pycache__", ".cache"),
            )
        else:
            (target / "scripts").mkdir(parents=True, exist_ok=True)
            (target / "scripts" / name).write_text("print('fixture')\n")
            (target / "SKILL.md").write_text("fixture skill\n")
        for path in target.rglob("*"):
            if path.is_file():
                declare(path)
        if name == "kb_search.py":
            dependency = (
                tmp_path
                / "workspaces/knowledge/skills/knowledge-base/SKILL.md"
            )
            dependency.parent.mkdir(parents=True, exist_ok=True)
            dependency.write_text("trusted shared engine")
            declare(dependency)
        return target / "scripts" / name

    return SimpleNamespace(
        create=create,
        workspace=workspace,
        policy=flow.policy,
        manifest=manifest,
        declare=declare,
    )


@pytest.mark.parametrize(
    "name,args",
    [
        ("kb_search.py", ["慢 SQL", "--output", "json"]),
        ("kb_query.py", ["慢 SQL"]),
        ("find_page.py", ["告警", "--top-k", "3"]),
        ("find_op.py", ["导出工单"]),
        ("private_line_business_monitor.py", ["cutover", "--code", "L001"]),
        ("web_monitor.py", ["list-monitors", "--limit", "5"]),
        ("web_monitor.py", ["run", "--run-id", "1"]),
        (
            "score_root_cause.py",
            [
                "--claim",
                "根因",
                "--object-match",
                "1",
                "--mechanism",
                "1",
                "--time-match",
                "0.5",
                "--independent",
                "0",
            ],
        ),
        ("query_alarm_class_count.py", ["--alarm_class", "application"]),
        ("resource_import_bridge.py", ["metadata"]),
        ("fde_tools.py", ["list-agents", "--json"]),
    ],
)
async def test_reviewed_reads_do_not_require_admin(scripts, name, args):
    script = scripts.create(name)
    assert (
        await scripts.policy.check_tool(
            "execute_shell_command",
            {
                "command": shlex.join(["python3", str(script), *args]),
            },
        )
        is False
    )
    script.write_text("print('tampered')\n")
    with pytest.raises(PermissionError, match="INTEGRITY"):
        scripts.policy.check_shell(shlex.join(["python3", str(script), *args]))


@pytest.mark.parametrize(
    "name,args",
    [
        ("resource_import_bridge.py", ["import"]),
        (
            "send_analysis_report.py",
            ["--alarm-id", "1", "--alarm-title", "fixture"],
        ),
        ("web_monitor.py", ["trigger", "--monitor-id", "1"]),
        ("web_monitor.py", ["delete-runs", "--run-ids", "run-1", "run-2"]),
        ("emit_action.py", ["workflow.category.add"]),
        ("emit_operate.py", ["--click", "删除", "--risk", "query"]),
        ("fde_tools.py", ["create-agent", "--id", "fixture"]),
    ],
)
async def test_writes_need_online_admin_even_when_tool_declared_readonly(
    scripts,
    monkeypatch,
    name,
    args,
):
    script = scripts.create(name)
    params = {"command": shlex.join(["python3", str(script), *args])}
    monkeypatch.setenv("QWENPAW_READONLY_TOOL_NAMES", "execute_shell_command")
    with pytest.raises(PermissionError, match="管理员"):
        await scripts.policy.check_tool("execute_shell_command", params)
    identity = SimpleNamespace(
        is_admin=True,
        access_token="",
        inoe_token="fixture",
        user={"userId": "1"},
    )
    token = scripts.policy.CURRENT_IDENTITY.set(identity)
    validate = AsyncMock(return_value={"userId": "1"})
    monkeypatch.setattr(scripts.policy, "_validate_inoe_token", validate)
    monkeypatch.setattr(
        scripts.policy.sso_settings_store,
        "get_userinfo_url",
        lambda: "fixture",
        raising=False,
    )
    try:
        assert (
            await scripts.policy.check_tool("execute_shell_command", params)
            is True
        )
        validate.assert_awaited_once()
        validate.side_effect = PermissionError("expired")
        with pytest.raises(PermissionError, match="expired"):
            await scripts.policy.check_tool("execute_shell_command", params)
    finally:
        scripts.policy.CURRENT_IDENTITY.reset(token)


@pytest.mark.parametrize(
    "name,args",
    [
        ("find_page.py", ["告警", "--top", "2"]),
        ("find_op.py", ["导出", "--catalog", "fake.json"]),
        (
            "emit_action.py",
            ["workflow.category.add", "--catalog", "fake.json"],
        ),
        (
            "query_alarm_class_count.py",
            ["--api_base_url", "https://evil.invalid"],
        ),
        ("web_monitor.py", ["selector-helper", "--url", "http://127.0.0.1"]),
        ("web_monitor.py", ["delete-runs", "--run-ids", "../run"]),
        ("web_monitor.py", ["delete-runs", "--run-ids"]),
        ("web_monitor.py", ["delete-runs", "--run-ids", *["run"] * 101]),
        ("fde_tools.py", ["probe", "--skill-dir", "staged/evil"]),
        ("fde_tools.py", ["discard", "--name", "fixture"]),
        ("fde_tools.py", ["show-staged", "--name", "../evil"]),
    ],
)
def test_unknown_or_unsafe_arguments_cannot_acquire_approval(
    scripts, name, args
):
    script = scripts.create(name)
    with pytest.raises(PermissionError):
        scripts.policy.check_shell(shlex.join(["python3", str(script), *args]))


def test_cmdb_preview_validates_nested_paths_and_binds_json(scripts, tmp_path):
    script = scripts.create("resource_import_bridge.py")
    upload = scripts.workspace / "inventory.csv"
    upload.write_text("name,ip\nrouter,192.0.2.1\n")
    context = scripts.workspace / "context.json"
    context.write_text(json.dumps({"files": [{"path": str(upload)}]}))
    params = {
        "command": shlex.join(
            ["python3", str(script), "preview", "--context-file", str(context)]
        )
    }
    assert scripts.policy.check_shell(params["command"]) is False
    binding = scripts.policy.approval_binding("execute_shell_command", params)
    upload.write_text("name,ip\nchanged,192.0.2.2\n")
    assert binding != scripts.policy.approval_binding(
        "execute_shell_command", params
    )
    context.write_text(
        json.dumps({"files": [{"path": str(tmp_path / "secrets/key.pem")}]})
    )
    with pytest.raises(PermissionError):
        scripts.policy.check_shell(params["command"])
    context.write_text(
        json.dumps({"progressFile": str(scripts.workspace / "SKILL.md")})
    )
    with pytest.raises(PermissionError, match="artifacts"):
        scripts.policy.check_shell(params["command"])


@pytest.mark.parametrize("from_skill_dir", [False, True])
def test_fde_recursive_reads_reject_symlinks(
    scripts, tmp_path, from_skill_dir
):
    script = scripts.create("fde_tools.py")
    staged = scripts.workspace / "staged/fixture"
    staged.mkdir(parents=True)
    (staged / "hidden").symlink_to(tmp_path / "secrets")
    with pytest.raises(PermissionError, match="符号链接"):
        scripts.policy.check_shell(
            f"python3 {script} show-staged --name fixture",
            cwd=script.parent.parent if from_skill_dir else scripts.workspace,
        )


@pytest.mark.parametrize("name", ["foo_bar", "foo--bar", "foo-"])
@pytest.mark.parametrize("action", ["scaffold", "show-staged", "discard"])
def test_fde_rejects_normalized_name_aliases(scripts, name, action):
    script = scripts.create("fde_tools.py")
    args = ["python3", str(script), action, "--name", name]
    if action == "scaffold":
        args += ["--target-workspace", "resource"]
    if action == "discard":
        args += ["--yes"]
    with pytest.raises(PermissionError, match="名称"):
        scripts.policy.check_shell(shlex.join(args))


def test_fde_discard_binds_actual_directory_contents(scripts):
    script = scripts.create("fde_tools.py")
    target = scripts.workspace / "staged/foo-bar"
    target.mkdir(parents=True)
    content = target / "SKILL.md"
    content.write_text("original")
    params = {
        "command": shlex.join(
            ["python3", str(script), "discard", "--name", "foo-bar", "--yes"]
        )
    }
    assert scripts.policy.check_shell(params["command"]) is True
    binding = scripts.policy.approval_binding("execute_shell_command", params)
    content.write_text("changed")
    assert binding != scripts.policy.approval_binding(
        "execute_shell_command", params
    )


@pytest.mark.parametrize("extension", [".csv", ".tsv", ".json", ".txt", ".md"])
def test_cmdb_preview_keeps_supported_text_uploads(scripts, extension):
    script = scripts.create("resource_import_bridge.py")
    upload = scripts.workspace / f"inventory{extension}"
    upload.write_text("fixture")
    context = scripts.workspace / "context.json"
    context.write_text(json.dumps({"files": [{"path": str(upload)}]}))
    assert (
        scripts.policy.check_shell(
            shlex.join(
                [
                    "python3",
                    str(script),
                    "preview",
                    "--context-file",
                    str(context),
                ]
            )
        )
        is False
    )


@pytest.mark.parametrize(
    "name,args,expected",
    [
        (
            "private_line_business_monitor.py",
            ["summary", "--output", "json"],
            "{",
        ),
        (
            "score_root_cause.py",
            [
                "--claim",
                "fixture",
                "--object-match",
                "1",
                "--mechanism",
                "1",
                "--time-match",
                "1",
                "--independent",
                "1",
            ],
            "fixture",
        ),
    ],
)
def test_real_static_bundled_scripts_run_under_production_policy(
    scripts, name, args, expected
):
    script = scripts.create(name, actual=True)
    command = [sys.executable, str(script), *args]
    assert scripts.policy.check_shell(shlex.join(command)) is False
    result = subprocess.run(
        command,
        cwd=scripts.workspace,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout


@pytest.mark.parametrize("executable", ["qwenpaw", "copaw"])
async def test_cli_policy_requires_admin_and_binds_file_content(
    scripts, monkeypatch, executable
):
    context = scripts.workspace / "chat.json"
    context.write_text('{"session_id":"s1","user_id":"u1"}')
    params = {
        "command": shlex.join(
            [
                executable,
                "chats",
                "create",
                "--agent-id",
                scripts.workspace.name,
                "--file",
                str(context),
            ]
        )
    }
    with pytest.raises(PermissionError, match="管理员"):
        await scripts.policy.check_tool("execute_shell_command", params)
    identity = SimpleNamespace(
        is_admin=True,
        access_token="",
        inoe_token="fixture",
        user={"userId": "1"},
    )
    reset = scripts.policy.CURRENT_IDENTITY.set(identity)
    monkeypatch.setattr(
        scripts.policy,
        "_validate_inoe_token",
        AsyncMock(return_value={"userId": "1"}),
    )
    monkeypatch.setattr(
        scripts.policy.sso_settings_store,
        "get_userinfo_url",
        lambda: "fixture",
        raising=False,
    )
    try:
        assert (
            await scripts.policy.check_tool("execute_shell_command", params)
            is True
        )
        binding = scripts.policy.approval_binding(
            "execute_shell_command", params
        )
        assert str(context) in binding["files"]
        context.write_text('{"session_id":"s2","user_id":"u1"}')
        assert binding != scripts.policy.approval_binding(
            "execute_shell_command", params
        )
    finally:
        scripts.policy.CURRENT_IDENTITY.reset(reset)
