"""Offline regressions for topology guidance and every CMDB CLI copy."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import requests


SCRIPT_DIR = Path(__file__).resolve().parents[1]
WORKSPACES_ROOT = Path(__file__).resolve().parents[5]
WORKSPACES = ("fault", "gateway", "inspection", "query", "resource")
sys.path.insert(0, str(SCRIPT_DIR))

import cmdb_output  # noqa: E402


def _load(workspace: str, name: str):
    path = (
        WORKSPACES_ROOT
        / workspace
        / "skills"
        / "zgops-cmdb"
        / "scripts"
        / f"{name}.py"
    )
    spec = importlib.util.spec_from_file_location(
        f"cmdb_regression_{workspace}_{name}", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _upstream_payload():
    return {
        "numfound": 2,
        "result": [
            {
                "_id": 10248,
                "ci_type": "project",
                "project_name": "demo-project",
            },
            {
                "_id": 10256,
                "ci_type": "kubernetes",
                "name": "demo-cluster",
                "bearer_token": "fixture-bearer-secret",
                "login_pwd": "fixture-login-password",
                "nested": [{"password": "fixture-nested-password"}],
            },
        ],
    }


class OutputRedactionTests(unittest.TestCase):
    def test_nested_credentials_are_masked_without_mutating_input(self):
        payload = _upstream_payload()
        output = cmdb_output.redact_output(payload)
        cluster = output["result"][1]
        self.assertEqual(cluster["bearer_token"], cmdb_output.MASK)
        self.assertEqual(cluster["login_pwd"], cmdb_output.MASK)
        self.assertEqual(cluster["nested"][0]["password"], cmdb_output.MASK)
        self.assertEqual(output["numfound"], 2)
        self.assertEqual(
            [item["_id"] for item in output["result"]], [10248, 10256]
        )
        self.assertEqual(
            payload["result"][1]["login_pwd"], "fixture-login-password"
        )
        self.assertEqual(cmdb_output.redact_output(output), output)

    def test_aliases_short_values_and_secret_containers_are_fully_masked(self):
        payload = {
            "BearerToken": "x",
            "LOGIN_PWD": "ab",
            "login-password": ["fixture-secret"],
            "private_key": {"value": "fixture-private-key"},
            "api_key": "fixture-key",
            "access_token": "fixture-access",
            "refresh_token": "fixture-refresh",
            "client_secret": "fixture-client",
            "Authorization": "Bearer fixture-auth",
            "_id": 10251,
        }
        result = cmdb_output.redact_output(payload)
        for key in payload:
            self.assertEqual(
                result[key], 10251 if key == "_id" else cmdb_output.MASK
            )

    def test_credential_free_output_is_unchanged(self):
        value = '{"numfound": 0, "result": [], "token_count": 3}'
        self.assertEqual(cmdb_output.redact_output(value), value)
        self.assertEqual(cmdb_output.redact_output(None), None)
        self.assertEqual(cmdb_output.redact_output(0), 0)

    def test_json_output_remains_parseable(self):
        output = io.StringIO()
        cmdb_output.safe_print(json.dumps(_upstream_payload()), file=output)
        result = json.loads(output.getvalue())
        self.assertEqual(result["numfound"], 2)
        self.assertEqual(result["result"][1]["login_pwd"], cmdb_output.MASK)
        self.assertNotIn("fixture-", output.getvalue())

    def test_text_errors_embedded_json_and_bearer_headers_are_masked(self):
        cases = [
            'HTTP 500: {"login_pwd": "fixture-secret", "code": 500}',
            "login_pwd=fixture-secret",
            "bearer_token: fixture-secret",
            "request failed: Bearer fixture-secret",
            'bad JSON: {"login_pwd": ["fixture-secret"]',
            '{"result": {"login_pwd": "fixture-secret"',
        ]
        for text in cases:
            with self.subTest(text=text):
                result = cmdb_output.redact_output(text)
                self.assertNotIn("fixture-secret", result)
                self.assertIn(cmdb_output.MASK, result)

    def test_json_encoded_body_inside_an_envelope_is_masked(self):
        output = cmdb_output.redact_output(
            {"error": json.dumps(_upstream_payload())}
        )
        self.assertNotIn("fixture-", output["error"])
        self.assertEqual(json.loads(output["error"])["numfound"], 2)

    def test_configured_request_token_is_not_echoed_in_unlabelled_errors(self):
        with patch.dict(
            "os.environ", {"INOE_API_TOKEN": "fixture-gateway-secret"}
        ):
            result = cmdb_output.redact_output(
                "request rejected fixture-gateway-secret"
            )
        self.assertEqual(result, "request rejected " + cmdb_output.MASK)

    def test_cli_failure_is_explicit_nonzero_and_has_no_raw_traceback(self):
        def fail():
            raise RuntimeError('HTTP 500: {"login_pwd": "fixture-secret"}')

        output = io.StringIO()
        with redirect_stderr(output):
            result = cmdb_output.run_cli(fail)
        self.assertEqual(result, 1)
        self.assertIn("RuntimeError: HTTP 500", output.getvalue())
        self.assertNotIn("fixture-secret", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())

    def test_redaction_failure_never_prints_raw_content(self):
        output = io.StringIO()
        with (
            patch.object(
                cmdb_output,
                "redact_output",
                side_effect=RuntimeError("redaction unavailable"),
            ),
            redirect_stdout(output),
            self.assertRaises(RuntimeError),
        ):
            cmdb_output.safe_print('{"login_pwd": "fixture-secret"}')
        self.assertEqual(output.getvalue(), "")


class WorkspaceRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = {
            workspace: {
                name: _load(workspace, name)
                for name in (
                    "app_topology",
                    "find_project",
                    "zgops_http",
                    "analyze_cmdb",
                    "inoe_cmdb_stats",
                )
            }
            for workspace in WORKSPACES
        }

    def test_all_script_copies_have_the_same_output_boundary(self):
        for workspace, modules in self.modules.items():
            for name, module in modules.items():
                with self.subTest(workspace=workspace, script=name):
                    self.assertIs(module.print, cmdb_output.safe_print)
                    self.assertIs(module.run_cli, cmdb_output.run_cli)
                    relative = Path("scripts") / f"{name}.py"
                    root = WORKSPACES_ROOT / workspace / "skills/zgops-cmdb"
                    self.assertEqual(
                        (root / relative).read_bytes(),
                        (SCRIPT_DIR / f"{name}.py").read_bytes(),
                    )
            self.assertEqual(
                (
                    WORKSPACES_ROOT
                    / workspace
                    / "skills/zgops-cmdb/scripts/cmdb_output.py"
                ).read_bytes(),
                (SCRIPT_DIR / "cmdb_output.py").read_bytes(),
            )

    def test_application_fetch_preserves_exact_forward_request(self):
        class Client:
            def __init__(self):
                self.paths = []

            def _request_json(self, path):
                self.paths.append(path)
                return {"numfound": 0, "result": []}

        for workspace, modules in self.modules.items():
            with self.subTest(workspace=workspace):
                client = Client()
                result = modules["app_topology"]._fetch_relations(
                    client, 10251
                )
                self.assertEqual(result, [])
                self.assertEqual(
                    client.paths,
                    [
                        "/api/v0.1/ci_relations/s?root_id=10251"
                        "&level=1,2,3&count=10000&page=1",
                    ],
                )

    def test_fallback_passes_reverse_and_masks_upstream_fixture(self):
        for workspace, modules in self.modules.items():
            http = modules["zgops_http"]
            for root_id in (10251, 10254):
                with self.subTest(workspace=workspace, root_id=root_id):
                    path = (
                        f"/api/v0.1/ci_relations/s?root_id={root_id}"
                        "&level=1,2,3"
                        "&count=10000&reverse=1"
                    )
                    response = http.FallbackResponse(
                        200, json.dumps(_upstream_payload())
                    )
                    output = io.StringIO()
                    with (
                        patch.dict(
                            "os.environ",
                            {
                                "INOE_API_BASE_URL": "http://gateway.example",
                                "INOE_API_TOKEN": "fixture-gateway-token",
                            },
                        ),
                        patch.object(
                            sys, "argv", ["zgops_http.py", "fetch", path]
                        ),
                        patch.object(
                            http,
                            "request_with_fallback",
                            return_value=response,
                        ) as request,
                        redirect_stdout(output),
                    ):
                        result = http.main()
                    self.assertEqual(result, 0)
                    query = parse_qs(urlsplit(request.call_args.args[2]).query)
                    self.assertEqual(query["root_id"], [str(root_id)])
                    self.assertEqual(query["reverse"], ["1"])
                    self.assertEqual(query["level"], ["1,2,3"])
                    body = json.loads(output.getvalue())["响应体"]
                    self.assertEqual(body["numfound"], 2)
                    self.assertEqual(
                        [item["_id"] for item in body["result"]],
                        [10248, 10256],
                    )
                    self.assertNotIn("fixture-", output.getvalue())

    def test_http_error_output_is_also_masked(self):
        for workspace, modules in self.modules.items():
            http = modules["zgops_http"]
            for body in (
                json.dumps(_upstream_payload()),
                "login_pwd=fixture-error-password",
            ):
                with self.subTest(workspace=workspace, body=body):
                    response = http.FallbackResponse(500, body)
                    error = requests.HTTPError(response=response)
                    output = io.StringIO()
                    with (
                        patch.dict(
                            "os.environ",
                            {
                                "INOE_API_BASE_URL": "http://gateway.example",
                                "INOE_API_TOKEN": "fixture-gateway-token",
                            },
                        ),
                        patch.object(
                            sys,
                            "argv",
                            [
                                "zgops_http.py",
                                "fetch",
                                "/api/v0.1/ci/10256",
                            ],
                        ),
                        patch.object(
                            http, "request_with_fallback", side_effect=error
                        ),
                        redirect_stdout(output),
                    ):
                        result = http.main()
                    self.assertEqual(result, 1)
                    self.assertEqual(json.loads(output.getvalue())["状态码"], 500)
                    self.assertNotIn("fixture-", output.getvalue())

    def test_application_output_formats_and_inline_merge_are_preserved(self):
        for workspace, modules in self.modules.items():
            app = modules["app_topology"]
            for output_format in ("markdown", "echarts", "json"):
                with self.subTest(workspace=workspace, format=output_format):
                    output = io.StringIO()
                    with (
                        patch.object(
                            sys,
                            "argv",
                            [
                                "app_topology.py",
                                "demo-project",
                                "--output",
                                output_format,
                            ],
                        ),
                        patch.object(app, "CmdbHttpClient") as client_cls,
                        patch.object(
                            app,
                            "_fetch_relations",
                            return_value=[_upstream_payload()["result"][1]],
                        ),
                        patch.object(app, "_fetch_ci_detail", return_value={}),
                        patch.object(
                            app,
                            "_resolve_inline_resources",
                            return_value=[
                                {
                                    "_id": 10251,
                                    "ci_type": "redis",
                                    "middleware_name": "demo-redis",
                                    "login_pwd": "fixture-redis-password",
                                }
                            ],
                        ),
                        redirect_stdout(output),
                    ):
                        client_cls.return_value.list_projects.return_value = [
                            _upstream_payload()["result"][0],
                        ]
                        result = app.main()
                    self.assertEqual(result, 0)
                    text = output.getvalue()
                    self.assertNotIn("fixture-", text)
                    if output_format == "markdown":
                        self.assertIn("```echarts", text)
                    else:
                        payload = json.loads(text)
                        if output_format == "json":
                            self.assertEqual(payload["resource_count"], 2)
                            payload = payload["option"]
                        self.assertEqual(payload["series"][0]["type"], "tree")
                        self.assertEqual(payload["series"][0]["orient"], "LR")

    def test_statistics_are_redacted_before_markdown_rendering(self):
        for workspace, modules in self.modules.items():
            stats = modules["inoe_cmdb_stats"]
            output = io.StringIO()
            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "inoe_cmdb_stats.py",
                        "group",
                        "--output",
                        "markdown",
                    ],
                ),
                patch.object(
                    stats,
                    "query_stat",
                    return_value={
                        "code": 200,
                        "login_pwd": "fixture-stat-password",
                    },
                ),
                patch.object(
                    stats,
                    "render_markdown",
                    side_effect=lambda payload: payload["login_pwd"],
                ),
                redirect_stdout(output),
            ):
                self.assertEqual(stats.main(), 0)
            self.assertEqual(output.getvalue().strip(), cmdb_output.MASK)

    def test_analysis_errors_are_redacted_before_rendering(self):
        for workspace, modules in self.modules.items():
            output = io.StringIO()
            with redirect_stdout(output):
                modules["analyze_cmdb"].print_result(
                    {
                        "code": 500,
                        "msg": "login_pwd=fixture-analysis-password",
                    },
                    "markdown",
                )
            self.assertIn("500", output.getvalue())
            self.assertNotIn("fixture-analysis-password", output.getvalue())

    def test_skill_copies_document_direction_errors_and_safe_graphs(self):
        for workspace in WORKSPACES:
            root = WORKSPACES_ROOT / workspace / "skills" / "zgops-cmdb"
            content = (root / "SKILL.md").read_text(encoding="utf-8")
            with self.subTest(workspace=workspace):
                for token in (
                    "`root_id`, `level`, `count`, `reverse`",
                    "### 查资源实例拓扑",
                    "reverse=0",
                    "reverse=1",
                    "level=1..3",
                    "关系 ID",
                    "源 CI ID",
                    "拓扑不完整",
                    "不能据此下“无关系”结论",
                    "`graph`",
                    "bearer_token",
                    "login_pwd",
                ):
                    self.assertIn(token, content)
                self.assertNotIn("查上下游关系链", content)
                application = content.split("### 查应用拓扑", 1)[1].split(
                    "### 查资源实例拓扑", 1
                )[0]
                self.assertNotIn("reverse=1", application)
                self.assertIn("默认正向查询", application)
                self.assertIn(
                    "reverse=1",
                    (root / "references/endpoints.md").read_text(
                        encoding="utf-8"
                    ),
                )
        fault = (
            WORKSPACES_ROOT / "fault/skills/zgops-cmdb/SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("不先调用 `cmdb-query__cmdbLogin`", fault)

    def test_inspection_and_rca_do_not_treat_forward_empty_as_no_relations(
        self,
    ):
        for workspace in ("gateway", "inspection"):
            root = WORKSPACES_ROOT / workspace / "skills/inspection-analyst"
            for relative in ("SKILL.md", "references/api-config.md"):
                content = (root / relative).read_text(encoding="utf-8")
                self.assertIn("reverse=1", content)
                self.assertIn("拓扑不完整", content)
                self.assertNotIn("空关系是合法结论", content)
        content = (
            WORKSPACES_ROOT / "fault/skills/alarm-analyst/SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("正向为空不代表无上游", content)
        self.assertIn("reverse=1", content)


if __name__ == "__main__":
    unittest.main()
