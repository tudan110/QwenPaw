"""Exercise reviewed CLI operations without importing the agent runtime."""

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def cli(monkeypatch, tmp_path):
    package = ModuleType("_skill_cli_contracts_test")
    package.__path__ = [str(ROOT / "src/qwenpaw/extensions/security")]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    module = importlib.import_module(f"{package.__name__}.skill_cli")
    workspace = tmp_path / "workspaces/default"
    workspace.mkdir(parents=True)

    def check_path(path):
        if Path(path).name in {".env", "config.json"}:
            raise PermissionError("secret file")

    def check(args):
        return module.check_cli_arguments(
            args, workspace, workspace, check_path
        )

    return check, workspace


@pytest.mark.parametrize(
    "args",
    [
        ["cron", "list"],
        *[
            ["cron", action, "job-1"]
            for action in ("get", "state", "pause", "resume", "delete", "run")
        ],
        ["cron", "update", "job-1", "--name", "Renamed"],
        ["chats", "list", "--channel", "console"],
        ["chats", "get", "chat-1"],
        ["chats", "delete", "chat-1"],
        ["chats", "update", "chat-1", "--name", "Renamed"],
        ["chats", "create", "--user-id", "alice", "--session-id", "s-1"],
        [
            "channels",
            "send",
            "--channel",
            "console",
            "--target-user",
            "alice",
            "--target-session",
            "s-1",
            "--text",
            "通知",
        ],
        [
            "cron",
            "create",
            "--type",
            "text",
            "--name",
            "Daily",
            "--channel",
            "console",
            "--target-user",
            "alice",
            "--target-session",
            "s-1",
            "--text",
            "通知",
            "--cron",
            "0 9 * * *",
        ],
        [
            "cron",
            "create",
            "--type",
            "agent",
            "--name",
            "Once",
            "--channel",
            "console",
            "--target-user",
            "alice",
            "--target-session",
            "s-1",
            "--text",
            "Check",
            "--schedule-type",
            "scheduled",
            "--run-at",
            "2026-12-01T09:00:00Z",
            "--timeout",
            "600",
            "--no-share-session",
        ],
    ],
)
def test_supported_operations_always_require_admin(cli, args):
    check, _ = cli
    assert check([*args, "--agent-id", "default"]) is True


@pytest.mark.parametrize(
    "args",
    [
        ["cron", "list"],
        ["cron", "list", "--agent-id", "other"],
        ["--host", "evil.example", "cron", "list"],
        ["channels", "list", "--agent-id", "default"],
        ["channels", "add", "--agent-id", "default"],
        ["chats", "get", "../other", "--agent-id", "default"],
        ["cron", "get", "a%2fb", "--agent-id", "default"],
        ["cron", "get", "a?token=x", "--agent-id", "default"],
        ["cron", "list", "--base-url", "http://evil", "--agent-id", "default"],
        ["cron", "list", "--agent", "default"],
        ["cron", "list", "--agent-id", "default", "--agent-id", "default"],
        ["cron", "list", "--agent-id", "default", "--help"],
        ["cron", "list", "--agent-id", "default", "&&", "echo", "x"],
        ["channels", "send", "--agent-id", "default", "--text", "No target"],
        ["cron", "create", "--agent-id", "default"],
        ["chats", "create", "--agent-id", "default", "--session-id", "x"],
        ["chats", "update", "chat-1", "--agent-id", "default"],
        [
            "cron",
            "update",
            "job-1",
            "--agent-id",
            "default",
            "--enabled",
            "--no-enabled",
        ],
    ],
)
def test_unreviewed_or_ambiguous_arguments_are_denied(cli, args):
    check, _ = cli
    with pytest.raises(PermissionError):
        check(args)


def cron_payload():
    return {
        "name": "Daily",
        "task_type": "agent",
        "schedule": {"type": "cron", "cron": "0 9 * * *"},
        "dispatch": {
            "channel": "console",
            "target": {"user_id": "alice", "session_id": "s-1"},
        },
        "request": {
            "input": [
                {
                    "role": "user",
                    "type": "message",
                    "content": [{"type": "text", "text": "Check"}],
                }
            ]
        },
    }


@pytest.mark.parametrize("group", ["cron", "chats"])
def test_workspace_json_contracts_require_admin(cli, group):
    check, workspace = cli
    payload = (
        cron_payload()
        if group == "cron"
        else {"user_id": "alice", "session_id": "s-1", "name": "Chat"}
    )
    (workspace / "payload.json").write_text(json.dumps(payload))
    assert (
        check(
            [
                group,
                "create",
                "--agent-id",
                "default",
                "--file",
                "payload.json",
            ]
        )
        is True
    )


@pytest.mark.parametrize(
    "case",
    [
        "outside",
        "symlink",
        "secret",
        "large",
        "array",
        "foreign-agent",
        "request-source",
        "request-agent",
        "request-user",
        "system-message",
        "url-content",
        "mixed-flags",
        "short-flag",
    ],
)
def test_json_cannot_escape_approved_contract(cli, tmp_path, case):
    check, workspace = cli
    payload = cron_payload()
    path = workspace / "payload.json"
    extra = []
    if case == "outside":
        path = tmp_path / "outside.json"
    elif case == "secret":
        path = workspace / "config.json"
    elif case == "array":
        payload = []
    elif case == "foreign-agent":
        payload["agent_id"] = "other"
    elif case == "request-source":
        payload["request"]["source"] = "cron"
    elif case == "request-agent":
        payload["request"]["agent_id"] = "other"
    elif case == "request-user":
        payload["request"]["user_id"] = "other"
    elif case == "system-message":
        payload["request"]["input"][0]["role"] = "system"
    elif case == "url-content":
        payload["request"]["input"][0]["content"] = [
            {"type": "image", "url": "file:///etc/passwd"}
        ]
    elif case == "mixed-flags":
        extra = ["--text", "Changed"]
    path.write_text(json.dumps(payload))
    if case == "large":
        path.write_text(json.dumps({"name": "x" * (256 * 1024)}))
    if case == "symlink":
        link = workspace / "link.json"
        link.symlink_to(path)
        path = link
    with pytest.raises(PermissionError):
        check(
            [
                "cron",
                "create",
                "--agent-id",
                "default",
                "-f" if case == "short-flag" else "--file",
                str(path),
                *extra,
            ]
        )


@pytest.mark.parametrize("task_type", ["text", "agent"])
def test_real_cron_cli_payload_is_accepted(cli, monkeypatch, task_type):
    """Use the real CLI builder behind the documented cron skill examples."""
    package = "_skill_cli_source_test"
    modules = {
        package: {},
        f"{package}.cli": {},
        f"{package}.cli.http": {"client": None, "print_json": None},
        f"{package}.app": {},
        f"{package}.app.channels": {},
        f"{package}.app.channels.schema": {"DEFAULT_CHANNEL": "console"},
    }
    for name, values in modules.items():
        module = ModuleType(name)
        module.__dict__.update(values)
        module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location(
        f"{package}.cli.cron_cmd", ROOT / "src/qwenpaw/cli/cron_cmd.py"
    )
    source = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(source)
    payload = source._build_spec_from_cli(
        task_type=task_type,
        schedule_type="scheduled",
        name="明早提醒",
        cron="",
        run_at="2026-12-01T09:00:00+08:00",
        repeat_every_days=1,
        repeat_end_type="count",
        repeat_until=None,
        repeat_count=5,
        channel="dingtalk",
        target_user="alice",
        target_session="alice-session",
        text="9 点开组会",
        timezone="Asia/Shanghai",
        enabled=True,
        mode="final",
        save_result_to_inbox=True,
        share_session=False,
        timeout_seconds=600,
    )
    check, workspace = cli
    (workspace / "cron.json").write_text(json.dumps(payload))
    assert (
        check(
            ["cron", "create", "--agent-id", "default", "--file", "cron.json"]
        )
        is True
    )


def test_exact_help_does_not_request_approval(cli):
    check, _ = cli
    assert check(["cron", "create", "--help"]) is False
