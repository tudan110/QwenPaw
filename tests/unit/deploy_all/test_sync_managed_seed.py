# -*- coding: utf-8 -*-
"""Unit tests for the deploy-all managed seed synchronizer."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SCRIPT = (
    Path(__file__).parents[3]
    / "deploy-all/qwenpaw/scripts/sync_managed_seed.py"
)
SPEC = importlib.util.spec_from_file_location("sync_managed_seed", SCRIPT)
assert SPEC and SPEC.loader
sync_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync_module
SPEC.loader.exec_module(sync_module)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: dict) -> None:
    write(path, json.dumps(payload, ensure_ascii=False, indent=2))


def build_seed(seed: Path) -> None:
    write_json(seed / "config.json", {"runtime": "seed"})
    write(seed / "workspaces/demo/AGENTS.md", "new instructions\n")
    write(seed / "workspaces/demo/skills/example/SKILL.md", "# new\n")
    write(
        seed / "workspaces/demo/skills/example/scripts/run.py",
        "print('new')\n",
    )
    write_json(
        seed / "workspaces/demo/agent.json",
        {
            "id": "demo",
            "name": "New Demo",
            "description": "new description",
            "workspace_dir": "/app/working/workspaces/demo",
            "channels": {"discord": {"bot_token": ""}},
        },
    )
    write_json(
        seed / "workspaces/demo/skill.json",
        {
            "schema_version": "workspace-skill-manifest.v1",
            "skills": {
                "example": {
                    "enabled": True,
                    "channels": ["all"],
                    "source": "customized",
                },
            },
        },
    )

    files = {}
    for path in sorted(seed.rglob("*")):
        if path.is_file() and path.name not in {
            "seed-manifest.json",
            "config.json",
        }:
            relative = str(path.relative_to(seed))
            kind = "skill_file"
            if relative.endswith("AGENTS.md"):
                kind = "workspace_file"
            elif relative.endswith("agent.json"):
                kind = "agent_config"
            elif relative.endswith("skill.json"):
                kind = "skill_manifest"
            files[relative] = {"kind": kind, "sha256": sha256(path)}
    write_json(
        seed / "seed-manifest.json",
        {
            "schema_version": "qwenpaw-seed.v2",
            "seed_id": "test-seed",
            "managed_files": files,
            "managed_skills": {
                "workspaces/demo/skills/example": {
                    "tree_sha256": "unused-in-test",
                    "files": {
                        name: data["sha256"]
                        for name, data in files.items()
                        if "/skills/example/" in name
                    },
                },
            },
        },
    )


def build_target(target: Path) -> None:
    write_json(target / "config.json", {"runtime": "target"})
    write(target / "workspaces/demo/AGENTS.md", "old instructions\n")
    write(target / "workspaces/demo/skills/example/SKILL.md", "# old\n")
    write(
        target / "workspaces/demo/skills/example/scripts/run.py",
        "print('old')\n",
    )
    write(
        target / "workspaces/demo/skills/example/data/knowledge.db",
        "keep\n",
    )
    write(target / "workspaces/demo/skills/example/.env", "TOKEN=keep\n")
    write(target / "workspaces/demo/skills/user/SKILL.md", "# user\n")
    write_json(
        target / "workspaces/demo/agent.json",
        {
            "id": "demo",
            "name": "Old Demo",
            "description": "old description",
            "workspace_dir": "/old/demo",
            "channels": {"discord": {"bot_token": "keep-me"}},
            "active_model": {"provider_id": "keep"},
        },
    )
    write_json(
        target / "workspaces/demo/jobs.json",
        {"jobs": [{"id": "keep"}]},
    )
    write_json(
        target / "workspaces/demo/skill.json",
        {
            "schema_version": "workspace-skill-manifest.v1",
            "version": 5,
            "skills": {
                "example": {
                    "enabled": False,
                    "config": {"local": True},
                    "tags": ["keep"],
                },
                "user": {"enabled": True},
            },
        },
    )


@pytest.mark.parametrize("existing_working", [False, True])
@pytest.mark.parametrize("existing_secret", [False, True])
def test_entrypoint_preserves_live_secrets_and_syncs_existing_seed(
    tmp_path: Path,
    existing_working: bool,
    existing_secret: bool,
) -> None:
    if not shutil.which("envsubst"):
        pytest.skip("envsubst is not installed")
    root = Path(__file__).parents[3]
    seed = tmp_path / "seed"
    working = tmp_path / "working"
    secret = tmp_path / "secret"
    runtime = tmp_path / "runtime"
    build_seed(seed)
    if existing_working:
        build_target(working)
    if existing_secret:
        write(secret / ".master_key", "operator-key")
        write(secret / "providers/custom.json", "operator-provider")
    supervisor_stub = tmp_path / "supervisord"
    write(supervisor_stub, '#!/bin/sh\ntest -s "$2"\n')
    supervisor_stub.chmod(0o755)
    template = tmp_path / "supervisord.conf.template"
    shutil.copyfile(
        root / "deploy-all/qwenpaw/config/supervisord.conf.template",
        template,
    )
    entrypoint = (root / "deploy-all/qwenpaw/entrypoint.sh").read_text(
        encoding="utf-8"
    )
    replacements = {
        "/app/share/qwenpaw-seed": str(seed),
        "/usr/local/bin/sync_managed_seed.py": str(SCRIPT),
        "/etc/supervisor/conf.d/supervisord.conf.template": str(template),
        "/usr/bin/supervisord": str(supervisor_stub),
    }
    for before, after in replacements.items():
        entrypoint = entrypoint.replace(before, after)
    script = tmp_path / "entrypoint.sh"
    write(script, entrypoint)
    env = {
        **os.environ,
        "QWENPAW_WORKING_DIR": str(working),
        "QWENPAW_SECRET_DIR": str(secret),
        "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
        "QWENPAW_RUNTIME_DIR": str(runtime),
        "QWENPAW_PORT": "9088",
    }
    for _ in range(2):
        subprocess.run(
            ["sh", str(script)],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
    if existing_secret:
        assert (secret / ".master_key").read_text() == "operator-key"
        assert (secret / "providers/custom.json").read_text() == (
            "operator-provider"
        )
    else:
        assert list(secret.iterdir()) == []
    assert (working / "config.json").read_text() == (
        json.dumps(
            {"runtime": "target" if existing_working else "seed"},
            ensure_ascii=False,
            indent=2,
        )
    )
    assert (
        working / "workspaces/demo/skills/example/SKILL.md"
    ).read_text() == ("# new\n")
    if existing_working:
        assert (
            working / "workspaces/demo/skills/example/.env"
        ).read_text() == ("TOKEN=keep\n")
        assert (
            working / "workspaces/demo/skills/user/SKILL.md"
        ).read_text() == ("# user\n")
    assert (working / "custom_channels/portal_api.py").is_file()
    config = (runtime / "supervisord.conf").read_text()
    assert "--port 9088" in config
    assert f"pidfile={runtime}/supervisord.pid" in config
    assert "${QWENPAW_RUNTIME_DIR}" not in config


def test_empty_target_bootstraps_full_seed(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    target = tmp_path / "target"
    target.mkdir()
    build_seed(seed)

    result = sync_module.sync_managed_seed(seed, target, apply=True)

    assert result.summary() == {"bootstrap": 1}
    assert (target / "config.json").is_file()
    assert (target / "workspaces/demo/agent.json").is_file()


def test_existing_target_overwrites_managed_files_only(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    target = tmp_path / "target"
    build_seed(seed)
    build_target(target)

    result = sync_module.sync_managed_seed(seed, target, apply=True)

    assert result.summary()["update"] >= 1
    assert (
        target / "workspaces/demo/AGENTS.md"
    ).read_text() == "new instructions\n"
    assert (
        target / "workspaces/demo/skills/example/SKILL.md"
    ).read_text() == "# new\n"
    assert (
        target / "workspaces/demo/skills/example/data/knowledge.db"
    ).read_text() == "keep\n"
    assert (
        target / "workspaces/demo/skills/example/.env"
    ).read_text() == "TOKEN=keep\n"
    assert (target / "workspaces/demo/skills/user/SKILL.md").is_file()
    assert json.loads((target / "workspaces/demo/jobs.json").read_text())[
        "jobs"
    ] == [{"id": "keep"}]

    agent = json.loads((target / "workspaces/demo/agent.json").read_text())
    assert agent["name"] == "New Demo"
    assert agent["channels"]["discord"]["bot_token"] == "keep-me"
    assert agent["active_model"] == {"provider_id": "keep"}

    manifest = json.loads((target / "workspaces/demo/skill.json").read_text())
    assert manifest["skills"]["example"]["enabled"] is True
    assert manifest["skills"]["example"]["config"] == {"local": True}
    assert "user" in manifest["skills"]

    second = sync_module.sync_managed_seed(seed, target)
    assert second.summary()["unchanged"] >= 1


def integrity_fixture(tmp_path: Path, monkeypatch):
    from qwenpaw.extensions.security import execution_policy

    seed, target = tmp_path / "seed", tmp_path / "target"
    build_seed(seed)
    build_target(target)
    old = "workspaces/demo/skills/example/scripts/run.py"
    relative = old.replace("run.py", "query_knowledge.py")
    (seed / old).rename(seed / relative)
    manifest = json.loads((seed / "seed-manifest.json").read_text())
    manifest["managed_files"][relative] = manifest["managed_files"].pop(old)
    files = manifest["managed_skills"]["workspaces/demo/skills/example"][
        "files"
    ]
    files[relative] = files.pop(old)
    write_json(seed / "seed-manifest.json", manifest)
    # The old run.py intentionally remains an undeclared code file on the PVC.
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    monkeypatch.setenv("QWENPAW_ALLOWED_SCRIPT_HASHES", "{}")
    monkeypatch.setenv("QWENPAW_SKILL_SEED_PATH", str(seed))
    monkeypatch.setattr(execution_policy, "WORKING_DIR", target)
    return seed, target, relative, execution_policy


def test_sync_reports_execution_blockers_and_reviewed_quarantine_restores_read(
    tmp_path, monkeypatch
):
    seed, target, relative, policy = integrity_fixture(tmp_path, monkeypatch)
    extra = target / "workspaces/demo/skills/example/tmp_query.py"
    write(extra, "print('user temporary code')\n")
    extra.chmod(0o640)
    result = sync_module.sync_managed_seed(seed, target, apply=True)
    assert result.integrity["execution_ready"] is False
    assert extra.exists()
    with pytest.raises(PermissionError, match="UNDECLARED_CODE"):
        policy.check_shell(f"python {target / relative}")
    skill = "workspaces/demo/skills/example"
    plan = sync_module.plan_quarantine(seed, target, [skill])
    assert extra.exists()
    with pytest.raises(sync_module.ManagedSyncError, match="confirmation"):
        sync_module.apply_quarantine(seed, target, plan, confirmed=False)
    applied = sync_module.apply_quarantine(seed, target, plan, confirmed=True)
    assert applied["integrity"]["execution_ready"] is True
    backup = Path(applied["backup_path"]) / "files" / extra.relative_to(target)
    assert backup.read_text() == "print('user temporary code')\n"
    assert backup.stat().st_mode & 0o777 == 0o640
    assert not extra.exists()
    assert (target / relative).read_bytes() == (seed / relative).read_bytes()
    assert (target / skill / ".env").read_text() == "TOKEN=keep\n"
    assert (target / skill / "data/knowledge.db").read_text() == "keep\n"
    assert (target / "workspaces/demo/skills/user/SKILL.md").is_file()
    policy.check_shell(f"python {target / relative}")
    with pytest.raises(PermissionError):
        policy.check_path(str(backup))
    assert sync_module.plan_quarantine(seed, target, [skill])["files"] == []
    with pytest.raises(sync_module.ManagedSyncError, match="stale"):
        sync_module.apply_quarantine(seed, target, plan, confirmed=True)


@pytest.mark.parametrize(
    "change", ["file", "permissions", "new_code", "manifest", "plan"]
)
def test_quarantine_rejects_stale_or_altered_preview_without_moving_files(
    tmp_path, monkeypatch, change
):
    seed, target, _, _ = integrity_fixture(tmp_path, monkeypatch)
    sync_module.sync_managed_seed(seed, target, apply=True)
    skill = "workspaces/demo/skills/example"
    original = target / skill / "scripts/run.py"
    plan = sync_module.plan_quarantine(seed, target, [skill])
    if change == "file":
        original.write_text("changed after review")
    elif change == "permissions":
        original.chmod(0o700)
    elif change == "new_code":
        write(target / skill / "new.py", "print('new')")
    elif change == "manifest":
        manifest = json.loads((seed / "seed-manifest.json").read_text())
        manifest["seed_id"] = "new-release"
        write_json(seed / "seed-manifest.json", manifest)
    else:
        plan["files"][0]["path"] = "config.json"
    with pytest.raises(sync_module.ManagedSyncError, match="stale or altered"):
        sync_module.apply_quarantine(seed, target, plan, confirmed=True)
    assert original.exists()
    assert not (target / ".qwenpaw-managed-sync/quarantine").exists()


def test_quarantine_rolls_back_file_moves_on_failure(tmp_path, monkeypatch):
    seed, target, _, _ = integrity_fixture(tmp_path, monkeypatch)
    sync_module.sync_managed_seed(seed, target, apply=True)
    skill = "workspaces/demo/skills/example"
    write(target / skill / "second.py", "print('second')")
    plan = sync_module.plan_quarantine(seed, target, [skill])
    rename = sync_module.os.rename
    calls = 0

    def fail_second(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("fixture move failure")
        return rename(source, destination)

    monkeypatch.setattr(sync_module.os, "rename", fail_second)
    with pytest.raises(OSError, match="fixture move failure"):
        sync_module.apply_quarantine(seed, target, plan, confirmed=True)
    for entry in plan["files"]:
        assert sha256(target / entry["path"]) == entry["sha256"]
    manifests = list(
        (target / ".qwenpaw-managed-sync/quarantine").glob("*/manifest.json")
    )
    assert json.loads(manifests[0].read_text())["status"] == "rolled_back"


def test_quarantine_refuses_managed_modifications_and_symlinks(
    tmp_path, monkeypatch
):
    seed, target, relative, _ = integrity_fixture(tmp_path, monkeypatch)
    sync_module.sync_managed_seed(seed, target, apply=True)
    skill = "workspaces/demo/skills/example"
    (target / relative).write_text("user edited managed script")
    with pytest.raises(
        sync_module.ManagedSyncError, match="MANAGED_HASH_MISMATCH"
    ):
        sync_module.plan_quarantine(seed, target, [skill])
    (target / relative).write_bytes((seed / relative).read_bytes())
    (target / skill / "unsafe.py").symlink_to(tmp_path / "outside.py")
    with pytest.raises(sync_module.ManagedSyncError, match="SYMLINK_BLOCKED"):
        sync_module.plan_quarantine(seed, target, [skill])


def test_quarantine_cli_preview_is_readonly_and_apply_requires_confirmation(
    tmp_path, monkeypatch
):
    seed, target, _, _ = integrity_fixture(tmp_path, monkeypatch)
    sync_module.sync_managed_seed(seed, target, apply=True)
    plan = tmp_path / "review.json"
    args = [
        sys.executable,
        str(SCRIPT),
        "--seed",
        str(seed),
        "--target",
        str(target),
    ]
    preview = subprocess.run(
        [
            *args,
            "--plan-quarantine",
            str(plan),
            "--skill",
            "workspaces/demo/skills/example",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(preview.stdout)["files"]
    code = target / "workspaces/demo/skills/example/scripts/run.py"
    assert code.exists()
    saved_plan = plan.read_bytes()
    duplicate = subprocess.run(
        [
            *args,
            "--plan-quarantine",
            str(plan),
            "--skill",
            "workspaces/demo/skills/example",
        ],
        capture_output=True,
        text=True,
    )
    assert duplicate.returncode == 2
    assert plan.read_bytes() == saved_plan
    config_content = (target / "config.json").read_bytes()
    unsafe = subprocess.run(
        [
            *args,
            "--plan-quarantine",
            str(target / "config.json"),
            "--skill",
            "workspaces/demo/skills/example",
        ],
        capture_output=True,
        text=True,
    )
    assert unsafe.returncode == 2
    assert (target / "config.json").read_bytes() == config_content
    refused = subprocess.run(
        [*args, "--quarantine-plan", str(plan), "--apply"],
        capture_output=True,
        text=True,
    )
    assert refused.returncode == 2
    assert code.exists()
    applied = subprocess.run(
        [*args, "--quarantine-plan", str(plan), "--apply", "--yes"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(applied.stdout)["status"] == "completed"
    assert not code.exists()


def test_noncode_artifacts_do_not_block_but_missing_managed_docs_do(
    tmp_path, monkeypatch
):
    seed, target, _, _ = integrity_fixture(tmp_path, monkeypatch)
    sync_module.sync_managed_seed(seed, target, apply=True)
    skill = "workspaces/demo/skills/example"
    plan = sync_module.plan_quarantine(seed, target, [skill])
    sync_module.apply_quarantine(seed, target, plan, confirmed=True)
    write(target / skill / "report.json", '{"result":"user report"}')
    write(target / skill / "notes.txt", "user note")
    assert sync_module.sync_managed_seed(seed, target).integrity[
        "execution_ready"
    ]
    (target / skill / "SKILL.md").unlink()
    inspection = sync_module.sync_managed_seed(seed, target).integrity
    assert inspection["execution_ready"] is False
    assert any(
        blocker["code"] == "MANAGED_FILE_MISSING"
        for blocker in inspection["skills"][0]["blockers"]
    )


def test_quarantine_never_moves_code_uploaded_as_preserved_business_data(
    tmp_path, monkeypatch
):
    seed, target, _, _ = integrity_fixture(tmp_path, monkeypatch)
    sync_module.sync_managed_seed(seed, target, apply=True)
    skill = "workspaces/demo/skills/example"
    uploaded = target / skill / "data/uploaded.py"
    write(uploaded, "user uploaded data")
    with pytest.raises(sync_module.ManagedSyncError, match="Manual review"):
        sync_module.plan_quarantine(seed, target, [skill])
    assert uploaded.read_text() == "user uploaded data"


@pytest.mark.parametrize("suffix", [".py", ".so", ".pth"])
def test_quarantine_covers_each_undeclared_executable_suffix(
    tmp_path, monkeypatch, suffix
):
    seed, target, _, _ = integrity_fixture(tmp_path, monkeypatch)
    sync_module.sync_managed_seed(seed, target, apply=True)
    skill = "workspaces/demo/skills/example"
    extra = target / skill / ("extra" + suffix)
    write(extra, "fixture unreviewed content")
    plan = sync_module.plan_quarantine(seed, target, [skill])
    assert str(extra.relative_to(target)) in {
        item["path"] for item in plan["files"]
    }
    result = sync_module.apply_quarantine(seed, target, plan, confirmed=True)
    assert not extra.exists()
    assert result["integrity"]["execution_ready"] is True
