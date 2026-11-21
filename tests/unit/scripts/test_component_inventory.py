# -*- coding: utf-8 -*-
"""Verify sensitive-data handling and read-only evidence export."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/component_inventory.py"
SPEC = importlib.util.spec_from_file_location("component_inventory", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.write(
            self.repo / "pyproject.toml",
            '[project]\nname="sample"\ndependencies=["example>=1.2"]\n',
        )
        self.write(
            self.repo / "src/qwenpaw/config/config.py",
            "def _default_builtin_tools():\n"
            '    tools = {"read_file": None}\n'
            "    return tools\n",
        )

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def cli(self, output, working=None):
        command = [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(self.repo),
            "--output-dir",
            str(output),
        ]
        if working:
            command.extend(["--working-dir", str(working)])
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            check=False,
        )

    def test_export_omits_credentials_and_does_not_execute_or_modify_sources(
        self,
    ):
        working = self.root / "working"
        config = {
            "active_model": {
                "provider_id": "example",
                "model": "example-model",
            },
            "mcp": {
                "clients": {
                    "demo": {
                        "url": (
                            "https://USER_ONLY:PASS_ONLY@example.test/private/"
                            "URL_PATH_ONLY?token=QUERY_ONLY#FRAGMENT_ONLY"
                        ),
                        "enabled": True,
                        "headers": {"Authorization": "HEADER_ONLY"},
                        "args": ["ARGS_ONLY"],
                        "env": {"TOKEN": "ENV_ONLY"},
                        "oauth": {"access_token": "OAUTH_ONLY"},
                    }
                }
            },
            "tools": {
                "builtin_tools": {
                    "read_file": {
                        "enabled": True,
                        "config": {"api_key": "CONFIG_ONLY"},
                    }
                }
            },
        }
        self.write(working / "workspaces/demo/agent.json", json.dumps(config))
        self.write(working / ".env", "NEVER_READ_ONLY")
        self.write(
            self.repo / "plugins/demo/plugin.json",
            '{"id":"demo","version":"1.0"}',
        )
        marker = self.root / "executed"
        self.write(
            self.repo / "plugins/demo/__init__.py",
            "from pathlib import Path\n"
            f'Path({str(marker)!r}).write_text("executed")',
        )
        before = {
            p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()
        }
        output = self.root / "report"
        result = self.cli(output, working)
        self.assertEqual(result.returncode, 0, result.stderr)
        exported = (output / "components.json").read_text(encoding="utf-8") + (
            output / "components.html"
        ).read_text(encoding="utf-8")
        for secret in [
            "USER_ONLY",
            "PASS_ONLY",
            "URL_PATH_ONLY",
            "QUERY_ONLY",
            "FRAGMENT_ONLY",
            "HEADER_ONLY",
            "ARGS_ONLY",
            "ENV_ONLY",
            "OAUTH_ONLY",
            "CONFIG_ONLY",
            "NEVER_READ_ONLY",
        ]:
            self.assertNotIn(secret, exported)
        report = json.loads(
            (output / "components.json").read_text(encoding="utf-8")
        )
        mcp = next(r for r in report["components"] if r["kind"] == "MCP服务")
        self.assertEqual(mcp["target_origin"], "https://example.test")
        self.assertEqual(mcp["risk_level"], MODULE.UNKNOWN)
        self.assertIn("声明启用", mcp["state"])
        self.assertIn("未验证", mcp["state"])
        self.assertFalse(marker.exists())
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)

    def test_declared_dependencies_are_not_reported_as_installed(self):
        inventory = MODULE.Inventory()
        inventory.repository(self.repo)
        dependency = next(
            r for r in inventory.records if r["kind"] == "Python直接依赖"
        )
        self.assertEqual(dependency["version"], "example>=1.2")
        self.assertIn("未核实安装版本", dependency["state"])
        self.assertEqual(dependency["risk_level"], MODULE.UNKNOWN)

    def test_digest_matches_source_bytes_and_html_escapes_metadata(self):
        path = self.repo / "src/qwenpaw/agents/skills/demo/SKILL.md"
        path.parent.mkdir(parents=True)
        content = (
            b"\xef\xbb\xbf---\r\nname: demo\r\n"
            b"description: <script>alert(1)</script>\r\n---\r\n"
        )
        path.write_bytes(content)
        inventory = MODULE.Inventory()
        inventory.repository(self.repo)
        skill = next(r for r in inventory.records if r["kind"] == "技能")
        self.assertEqual(
            skill["source_file_sha256"], hashlib.sha256(content).hexdigest()
        )
        html = MODULE.render(inventory.report(False))
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_invalid_configuration_is_reported_without_echoing_content(self):
        working = self.root / "working"
        self.write(
            working / "config.json", '{"access_token":"INVALID_JSON_PRIVATE"'
        )
        inventory = MODULE.Inventory()
        inventory.configs(working, "working", "configuration")
        report = inventory.report(True)
        self.assertTrue(report["warnings"])
        self.assertNotIn("INVALID_JSON_PRIVATE", json.dumps(report))
        self.assertFalse(report["components"])

    def test_existing_report_is_not_overwritten(self):
        output = self.root / "report"
        output.mkdir()
        self.write(output / "components.json", "existing evidence")
        result = self.cli(output)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            (output / "components.json").read_text(), "existing evidence"
        )
        self.assertFalse((output / "components.html").exists())

    def test_report_cannot_be_written_inside_collected_working_directory(self):
        working = self.root / "working"
        working.mkdir()
        result = self.cli(working / "report", working)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((working / "report").exists())

    def test_nested_link_is_not_followed(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.write(outside / "plugin.json", '{"id":"OUTSIDE_PRIVATE"}')
        plugins = self.repo / "plugins"
        plugins.mkdir()
        try:
            (plugins / "linked").symlink_to(outside, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                self.skipTest("symlink creation is unavailable on this host")
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "New-Item -ItemType Junction "
                    "-Path $env:QWENPAW_TEST_LINK "
                    "-Target $env:QWENPAW_TEST_TARGET | Out-Null",
                ],
                env={
                    **os.environ,
                    "QWENPAW_TEST_LINK": str(plugins / "linked"),
                    "QWENPAW_TEST_TARGET": str(outside),
                },
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                check=False,
            )
            if result.returncode:
                self.skipTest("symlink/junction creation is unavailable")
        inventory = MODULE.Inventory()
        inventory.repository(self.repo)
        self.assertNotIn(
            "OUTSIDE_PRIVATE", json.dumps(inventory.report(False))
        )
        self.assertTrue(
            any("不安全目录" in warning for warning in inventory.warnings)
        )

    def test_nested_skill_scaffold_is_not_reported_as_another_component(self):
        skills = self.repo / "src/qwenpaw/agents/skills"
        self.write(
            skills / "demo/SKILL.md", "---\ndescription: real skill\n---\n"
        )
        self.write(
            skills / "demo/references/scaffold/SKILL.md",
            "not another installed skill",
        )
        inventory = MODULE.Inventory()
        inventory.repository(self.repo)
        skills = [r for r in inventory.records if r["kind"] == "技能"]
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0]["name"], "demo")


if __name__ == "__main__":
    unittest.main()
