"""Isolated security-contract probes for the 2026-11-13 auth review.

Run with .venv/bin/python scripts/verify/auth_review_20261113.py.
Uses synthetic credentials and local ASGI requests only. Exit 1 means a
security expectation is violated; this is an opt-in audit, not a unit suite.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import zipfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="qwenpaw-auth-review-") as temp:
        root = Path(temp)
        environment = {
            "QWENPAW_WORKING_DIR": str(root / "working"),
            "QWENPAW_SECRET_DIR": str(root / "secrets"),
            "QWENPAW_BACKUP_DIR": str(root / "backups"),
            "QWENPAW_AUTH_ENABLED": "false",
            "QWENPAW_PRODUCTION_GUARDS": "true",
            "QWENPAW_ADMIN_INOE_USER_IDS": "1",
            "QWENPAW_ALLOWED_SCRIPT_HASHES": "{}",
        }
        with patch.dict(os.environ, environment):
            return run_probes(root)


def run_probes(root: Path) -> int:
    # Import after the temporary runtime directories are selected.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from qwenpaw.app.auth import AuthMiddleware
    from qwenpaw.app.routers import agents, backup, config, files
    from qwenpaw.backup._ops import storage
    from qwenpaw.backup._utils import constants as backup_constants
    from qwenpaw.backup.models import BackupMeta, BackupScope
    from qwenpaw.config.config import (
        AgentProfileConfig,
        ChannelConfig,
        FeishuConfig,
    )
    from qwenpaw.extensions.api import settings_store
    from qwenpaw.extensions.api.sso_token_middleware import SsoTokenMiddleware
    from qwenpaw.extensions.security import execution_policy

    profile = AgentProfileConfig(
        id="gateway",
        name="fixture",
        channels=ChannelConfig(
            feishu=FeishuConfig(app_secret="fixture-channel-secret")
        ),
    )
    workspace = SimpleNamespace(config=profile)
    backup_dir = root / "backups"
    backup_dir.mkdir()
    meta = BackupMeta(
        id="fixture-backup",
        name="fixture",
        scope=BackupScope(include_secrets=True),
    )
    with zipfile.ZipFile(backup_dir / "fixture-backup.zip", "w") as archive:
        archive.writestr("meta.json", meta.model_dump_json())
        archive.writestr("data/secrets/.master_key", "fixture-master-key")

    database = root / "working/extensions/settings/settings.db"
    settings_store.set_values(
        "inoe", {"inoe_api_token": "fixture-service-token"}, db_path=database
    )
    app = FastAPI()
    validator = AsyncMock()
    validator.validate.return_value = {"userId": 2, "username": "ordinary"}
    app.add_middleware(AuthMiddleware)
    app.add_middleware(SsoTokenMiddleware, validator=validator)
    for router in (agents.router, config.router, backup.router, files.router):
        app.include_router(router, prefix="/api")
    app.include_router(config.router, prefix="/api/agents/{agentId}")

    failures = []

    def check(name: str, passed: bool, **details) -> None:
        print(json.dumps({"check": name, "pass": passed, **details}))
        if not passed:
            failures.append(name)

    with ExitStack() as stack:
        stack.enter_context(patch.object(backup_constants, "BACKUP_DIR", backup_dir))
        stack.enter_context(patch.object(storage, "BACKUP_DIR", backup_dir))
        stack.enter_context(
            patch.object(agents, "load_agent_config", return_value=profile)
        )
        stack.enter_context(
            patch.object(config, "get_available_channels", return_value=["feishu"])
        )
        stack.enter_context(
            patch(
                "qwenpaw.app.agent_context.get_agent_for_request",
                AsyncMock(return_value=workspace),
            )
        )
        client = stack.enter_context(TestClient(app))
        for required, headers in (
            ("true", {"X-Inoe-Token": "fixture-inoe"}),
            ("false", {}),
        ):
            os.environ["QWENPAW_SSO_TOKEN_REQUIRED"] = required
            scenario = "ordinary-user" if headers else "anonymous-gate-disabled"
            for path in (
                "/api/backups",
                "/api/backups/fixture-backup/export",
                "/api/config/channels",
                "/api/agents/gateway/config/channels",
                "/api/agents/gateway",
            ):
                response = client.get(path, headers=headers)
                details = {"status": response.status_code}
                if path.endswith("/export") and response.status_code == 200:
                    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                        details["fixture_master_key_downloaded"] = (
                            archive.read("data/secrets/.master_key")
                            == b"fixture-master-key"
                        )
                if "channels" in path or path == "/api/agents/gateway":
                    details["fixture_channel_secret_in_response"] = (
                        b"fixture-channel-secret" in response.content
                    )
                check(f"{scenario}:{path}", response.status_code == 403, **details)

            response = client.get(
                "/api/files/preview/" + str(database).lstrip("/"), headers=headers
            )
            check(
                f"{scenario}:protected-file-preview",
                response.status_code == 403,
                status=response.status_code,
                fixture_service_token_downloaded=(
                    b"fixture-service-token" in response.content
                ),
            )

    # Name allowlisting must support official read commands even when their
    # complete fixture dependency tree matches the managed seed manifest.
    seed = root / "seed"
    seed.mkdir()
    managed, skills, commands = {}, {}, []
    for name in ("get_alarms.py", "get_devices.py", "monitoring_overview.py"):
        relative = f"workspaces/query/skills/fixture-{name}/scripts/{name}"
        script = root / "working" / relative
        script.parent.mkdir(parents=True)
        script.write_text("print('fixture')\n")
        digest = hashlib.sha256(script.read_bytes()).hexdigest()
        managed[relative] = {"sha256": digest}
        skills[str(Path(relative).parents[1])] = {"files": {relative: digest}}
        commands.append((name, f"python3 {script}"))
    (seed / "seed-manifest.json").write_text(
        json.dumps(
            {
                "managed_files": managed,
                "managed_skills": skills,
            }
        )
    )
    with patch.dict(os.environ, {"QWENPAW_SKILL_SEED_PATH": str(seed)}):
        for name, command in commands:
            try:
                execution_policy.check_shell(command)
                allowed, detail = True, "allowed"
            except PermissionError as error:
                allowed, detail = False, str(error)
            check(f"matching-managed-seed:{name}", allowed, detail=detail)

    print(json.dumps({"failed_expectations": len(failures), "failures": failures}))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
