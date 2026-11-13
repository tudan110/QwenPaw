# -*- coding: utf-8 -*-
"""Tests for the environment-independent qwenpaw image seed builder."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


BUILDER_PATH = (
    Path(__file__).parents[3]
    / "deploy-all/qwenpaw/scripts/build_universal_seed.py"
)
SPEC = importlib.util.spec_from_file_location(
    "build_universal_seed",
    BUILDER_PATH,
)
assert SPEC and SPEC.loader
seed_builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seed_builder)


def test_all_runtime_agents_share_the_same_manual_guidance_boundaries():
    workspaces = BUILDER_PATH.parent.parent / "working/workspaces"
    policies = []
    for agent in (
        "gateway", "fault", "query", "inspection", "resource",
        "order", "operator", "knowledge", "fde",
    ):
        text = (workspaces / agent / "AGENTS.md").read_text(encoding="utf-8")
        policies.append(
            text.split("<!-- cmdb-manual-guidance:start -->", 1)[1]
            .split("<!-- cmdb-manual-guidance:end -->", 1)[0]
        )
    assert len(set(policies)) == 1
    assert "不新增远程执行" in policies[0]
    assert "不默认" in policies[0]
    assert "缺登录信息不阻断" in policies[0]


def test_real_alarm_credentials_reach_all_five_seed_workspaces(tmp_path):
    workspaces = BUILDER_PATH.parent.parent / "working/workspaces"
    output = tmp_path / "seed"
    canonical = workspaces / "query/skills/real-alarm"
    for workspace in ("query", "fault", "gateway", "order", "resource"):
        target = output / f"workspaces/{workspace}/skills"
        source = workspaces / workspace / "skills/real-alarm"
        if source.exists():
            seed_builder.copy_managed_tree(source, target / "real-alarm")
        seed_builder.materialize_missing_skills(
            workspace, {"real-alarm": {"enabled": True}}, target,
            workspaces, {}, {"real-alarm": "query"}, set(),
        )
        script = target / "real-alarm/scripts/get_alarms.py"
        assert script.read_bytes() == (
            canonical / "scripts/get_alarms.py"
        ).read_bytes()
    manifest = seed_builder.build_sync_manifest(output)
    for workspace in ("query", "fault", "gateway", "order", "resource"):
        relative = (
            f"workspaces/{workspace}/skills/real-alarm/scripts/get_alarms.py"
        )
        assert manifest["managed_files"][relative]["sha256"] == (
            seed_builder.sha256(output / relative)
        )


def test_full_release_seed_and_upgrade_keep_fixes_and_user_model(tmp_path):
    root = BUILDER_PATH.parents[3]
    seed = tmp_path / "release-seed"
    seed_builder.build_seed(seed_builder.argparse.Namespace(
        source=BUILDER_PATH.parent.parent / "working",
        builtin_root=root / "src/qwenpaw/agents/skills",
        output=seed,
        runtime_working_dir="/app/working",
        manifest=None,
    ))
    target = tmp_path / "customer-working"
    write_json(target / "config.json", {"custom": "customer"})
    write_json(target / "workspaces/knowledge/agent.json", {
        "id": "knowledge",
        "name": "customer",
        "active_model": {"provider_id": "customer", "model": "keep"},
    })
    history = target / "workspaces/knowledge/sessions/history.json"
    write_json(history, {"user": "preserve"})
    subprocess.run([
        sys.executable, str(BUILDER_PATH.parent / "sync_managed_seed.py"),
        "--apply", "--yes", "--seed", str(seed), "--target", str(target),
    ], check=True, capture_output=True, text=True)
    model = json.loads(
        (target / "workspaces/knowledge/agent.json").read_text()
    )["active_model"]
    assert model == {"provider_id": "customer", "model": "keep"}
    assert json.loads(history.read_text()) == {"user": "preserve"}
    manifest = json.loads((seed / "seed-manifest.json").read_text())
    for workspace in ("query", "fault", "gateway", "order", "resource"):
        relative = (
            f"workspaces/{workspace}/skills/real-alarm/scripts/get_alarms.py"
        )
        assert (target / relative).read_bytes() == (seed / relative).read_bytes()
        assert manifest["managed_files"][relative]["sha256"] == (
            seed_builder.sha256(target / relative)
        )
    llm_path = Path(
        "workspaces/knowledge/skills/knowledge-base/providers/llm.py"
    )
    assert (target / llm_path).read_bytes() == (seed / llm_path).read_bytes()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_skill(path: Path, name: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")


def build_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "working"
    workspace = source / "workspaces/demo"
    builtin_root = tmp_path / "builtins"
    output = tmp_path / "seed"

    write_json(
        source / "config.json",
        {
            "channels": {"discord": {"bot_token": "do-not-package"}},
            "last_api": {"host": "10.0.0.1", "port": 8088},
            "active_model": {"provider_id": "environment-provider"},
            "tools": {
                "builtin_tools": {
                    "get_token_usage": {
                        "name": "get_token_usage",
                        "enabled": True,
                    },
                },
            },
            "agents": {
                "active_agent": "demo",
                "profiles": {
                    "demo": {
                        "id": "wrong-id",
                        "workspace_dir": "~/.qwenpaw/workspaces/demo",
                    },
                },
            },
        },
    )
    write_json(
        workspace / "agent.json",
        {
            "id": "wrong-id",
            "name": "Demo",
            "workspace_dir": "~/.qwenpaw/workspaces/demo",
            "api_key": "do-not-package",
            "active_model": {"provider_id": "environment-provider"},
        },
    )
    write_json(
        workspace / "jobs.json",
        {"version": 1, "jobs": [{"id": "old"}]},
    )
    write_json(
        workspace / "skill.json",
        {
            "schema_version": "workspace-skill-manifest.v1",
            "skills": {
                "custom": {"enabled": True, "channels": ["all"]},
                "docx": {"enabled": True, "channels": ["all"]},
                "retired": {"enabled": True, "channels": ["all"]},
            },
        },
    )
    write_skill(workspace / "skills/custom", "custom")
    (workspace / "skills/custom/.env").write_text(
        "TOKEN=secret\n",
        encoding="utf-8",
    )
    (workspace / "skills/custom/.env.example").write_text(
        "TOKEN=\n",
        encoding="utf-8",
    )
    (workspace / "skills/custom/cache.db").write_text(
        "runtime\n",
        encoding="utf-8",
    )
    (workspace / "skills/custom/__pycache__").mkdir()
    (workspace / "skills/custom/__pycache__/cache.pyc").write_bytes(b"cache")
    write_skill(builtin_root / "docx-zh", "docx")
    write_json(
        source / "universal-seed.json",
        {
            "schema_version": 1,
            "builtin_language": "zh",
            "default_builtin_skills": ["docx"],
            "retired_skills": ["retired"],
            "shared_skill_sources": {},
        },
    )
    return source, builtin_root, output


def test_cmdb_skill_output_guard_is_packaged_with_integrity_hashes(
    tmp_path: Path,
) -> None:
    source_root = (
        Path(__file__).parents[3] / "deploy-all/qwenpaw/working/workspaces"
    )
    seed = tmp_path / "seed"
    for workspace in ("fault", "gateway", "inspection", "query", "resource"):
        relative = Path("workspaces") / workspace / "skills/zgops-cmdb"
        source = source_root / workspace / "skills/zgops-cmdb"
        seed_builder.copy_managed_tree(source, seed / relative)

    manifest = seed_builder.build_sync_manifest(seed)
    for workspace in ("fault", "gateway", "inspection", "query", "resource"):
        relative = Path("workspaces") / workspace / "skills/zgops-cmdb"
        for name in ("cmdb_output.py", "cmdb_contract.py"):
            helper = relative / "scripts" / name
            expected_hash = seed_builder.sha256(seed / helper)
            assert manifest["managed_files"][str(helper)] == {
                "kind": "skill_file",
                "sha256": expected_hash,
            }
            assert (
                manifest["managed_skills"][str(relative)]["files"][str(helper)]
                == expected_hash
            )
        assert "reverse=1" in (seed / relative / "SKILL.md").read_text(
            encoding="utf-8",
        )


def test_builds_sanitized_seed_with_builtin_and_retired_skill_handling(
    tmp_path: Path,
) -> None:
    source, builtin_root, output = build_fixture(tmp_path)
    args = seed_builder.argparse.Namespace(
        source=source,
        builtin_root=builtin_root,
        output=output,
        runtime_working_dir="/app/working",
        manifest=None,
    )

    seed_builder.build_seed(args)

    config = json.loads((output / "config.json").read_text(encoding="utf-8"))
    assert config["agents"]["profiles"] == {
        "demo": {
            "id": "demo",
            "workspace_dir": "/app/working/workspaces/demo",
            "enabled": True,
        },
    }
    assert config["agents"]["agent_order"] == ["default", "demo"]
    assert config["agents"]["active_agent"] == "default"
    assert config["channels"]["discord"]["bot_token"] == ""
    assert config["last_api"] is None
    assert "active_model" not in config
    default_manifest = json.loads(
        (output / "workspaces/default/skill.json").read_text(encoding="utf-8"),
    )
    assert default_manifest["skills"]["docx"]["enabled"] is True
    assert (output / "workspaces/default/skills/docx/SKILL.md").is_file()
    assert config["tools"]["builtin_tools"]["get_token_usage"] == {
        "name": "get_token_usage",
        "enabled": True,
    }

    agent = json.loads(
        (output / "workspaces/demo/agent.json").read_text(encoding="utf-8"),
    )
    assert agent["id"] == "demo"
    assert agent["workspace_dir"] == "/app/working/workspaces/demo"
    assert agent["api_key"] == ""
    assert "active_model" not in agent
    assert json.loads(
        (output / "workspaces/demo/jobs.json").read_text(encoding="utf-8"),
    ) == {"version": 1, "jobs": []}

    skill_manifest = json.loads(
        (output / "workspaces/demo/skill.json").read_text(encoding="utf-8"),
    )
    assert set(skill_manifest["skills"]) == {"custom", "docx"}
    assert skill_manifest["skills"]["docx"]["enabled"] is True
    assert (output / "workspaces/demo/skills/docx/SKILL.md").is_file()
    assert not (output / "workspaces/demo/skills/retired").exists()
    assert not (output / "workspaces/demo/skills/custom/.env").exists()
    assert (output / "workspaces/demo/skills/custom/.env.example").is_file()
    assert (output / "workspaces/demo/skills/custom/cache.db").is_file()
    assert not (output / "workspaces/demo/skills/custom/__pycache__").exists()
    assert (output / "seed-manifest.json").is_file()


def test_rejects_manifest_skill_without_a_managed_source(
    tmp_path: Path,
) -> None:
    source, builtin_root, output = build_fixture(tmp_path)
    manifest = json.loads(
        (source / "workspaces/demo/skill.json").read_text(encoding="utf-8"),
    )
    manifest["skills"]["missing"] = {"enabled": True}
    write_json(source / "workspaces/demo/skill.json", manifest)
    args = seed_builder.argparse.Namespace(
        source=source,
        builtin_root=builtin_root,
        output=output,
        runtime_working_dir="/app/working",
        manifest=None,
    )

    with pytest.raises(seed_builder.SeedError, match="No source exists"):
        seed_builder.build_seed(args)
