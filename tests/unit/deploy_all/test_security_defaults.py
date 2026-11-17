"""Packaging security regressions; no cluster or image build is required."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[3]
CHART = ROOT / "deploy-all/qwenpaw/helm/qwenpaw"
BUNDLE = ROOT / "deploy-all/helm/cnos-inoe-agent-1.0.0.tgz"


def render(chart: Path = CHART, *args: str) -> list[dict]:
    helm = shutil.which("helm")
    if not helm:
        pytest.skip("helm is not installed")
    result = subprocess.run(
        [helm, "template", "security-test", str(chart), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def resource(documents: list[dict], kind: str) -> dict:
    return next(
        doc
        for doc in documents
        if doc["kind"] == kind and doc["metadata"]["name"] == "qwenpaw"
    )


@pytest.mark.parametrize("chart", [CHART, BUNDLE])
def test_chart_and_shipped_bundle_use_restricted_defaults(chart: Path) -> None:
    documents = render(chart)
    service = resource(documents, "Service")["spec"]
    assert service["type"] == "ClusterIP"
    assert "nodePort" not in service["ports"][0]

    pod = resource(documents, "Deployment")["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    context = pod["securityContext"]
    assert context["runAsNonRoot"] is True
    assert context["runAsUser"] == context["runAsGroup"] == 10001
    assert context["fsGroup"] == 10001
    assert context["fsGroupChangePolicy"] == "OnRootMismatch"
    assert context["seccompProfile"]["type"] == "RuntimeDefault"
    assert {item["name"] for item in pod["initContainers"]} == {
        "pvc-layout-bootstrap",
        "managed-seed-sync",
    }
    for container in pod["containers"] + pod["initContainers"]:
        security = container["securityContext"]
        assert security["allowPrivilegeEscalation"] is False
        assert security["readOnlyRootFilesystem"] is True
        assert security["capabilities"]["drop"] == ["ALL"]
    app = pod["containers"][0]
    env = {item["name"]: item["value"] for item in app["env"]}
    assert env["QWENPAW_SSO_TOKEN_REQUIRED"] == "true"
    assert env["QWENPAW_ADMIN_INOE_USER_IDS"] == "1"
    assert env["QWENPAW_INTERNAL_API_ORIGINS"] == "http://qwenpaw:8088"
    assert "QWENPAW_AUTH_ENABLED" not in env
    assert app["envFrom"][0]["secretRef"]["optional"] is False
    mounts = {item["mountPath"] for item in app["volumeMounts"]}
    assert {
        "/app/runtime",
        "/tmp",
        "/app/working",
        "/app/working.secret",
        "/app/working.backups",
    } <= mounts

    policy = resource(documents, "NetworkPolicy")["spec"]
    assert policy["podSelector"]["matchLabels"] == (
        resource(documents, "Deployment")["spec"]["selector"]["matchLabels"]
    )
    assert policy["policyTypes"] == ["Ingress", "Egress"]
    portal_name = "digital-workforce-portal"
    assert policy["ingress"] == [
        {
            "from": [
                {
                    "podSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/name": portal_name,
                            "app.kubernetes.io/instance": "security-test",
                        },
                    },
                }
            ],
            "ports": [{"protocol": "TCP", "port": 8088}],
        }
    ]
    assert len(policy["egress"]) == 1
    dns = policy["egress"][0]
    assert dns["to"] == [
        {
            "namespaceSelector": {
                "matchLabels": {"kubernetes.io/metadata.name": "kube-system"},
            },
            "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
        }
    ]
    assert dns["ports"] == [
        {"protocol": "UDP", "port": 53},
        {"protocol": "TCP", "port": 53},
    ]


def test_explicit_network_peers_and_service_override(tmp_path: Path) -> None:
    groups = ("inoe", "model", "mcp", "audit", "retrieval")
    rules = {
        name: [
            {
                "to": [
                    {
                        "namespaceSelector": {
                            "matchLabels": {
                                "kubernetes.io/metadata.name": "internal"
                            },
                        },
                        "podSelector": {"matchLabels": {"app": name}},
                    }
                ],
                "ports": [{"protocol": "TCP", "port": 8080 + index}],
            }
        ]
        for index, name in enumerate(groups)
    }
    rules["additional"] = [
        {
            "to": [{"ipBlock": {"cidr": "192.0.2.8/32"}}],
            "ports": [{"protocol": "TCP", "port": 443}],
        }
    ]
    ingress = [
        {
            "from": [{"podSelector": {"matchLabels": {"app": "inoe"}}}],
            "ports": [{"protocol": "TCP", "port": 8088}],
        }
    ]
    values = tmp_path / "network-values.yaml"
    values.write_text(
        yaml.safe_dump(
            {
                "networkPolicy": {"egress": rules, "ingress": ingress},
                "service": {"type": "NodePort", "nodePort": 30088},
            }
        ),
        encoding="utf-8",
    )
    documents = render(CHART, "-f", str(values))
    policy = resource(documents, "NetworkPolicy")["spec"]
    assert policy["ingress"][1:] == ingress
    for rule in rules.values():
        assert rule[0] in policy["egress"]
    assert len(policy["egress"]) == 7
    service = resource(documents, "Service")["spec"]
    assert service["type"] == "NodePort"
    assert service["ports"][0]["nodePort"] == 30088
    cluster_ip = resource(
        render(CHART, "--set", "service.nodePort=30088"),
        "Service",
    )
    assert "nodePort" not in cluster_ip["spec"]["ports"][0]


@pytest.mark.parametrize("chart,prefix", [(CHART, ""), (BUNDLE, "qwenpaw.")])
def test_operator_can_override_default_admin_to_empty(
    chart: Path, prefix: str
) -> None:
    deployment = resource(
        render(
            chart,
            "--set-string",
            f"{prefix}env.QWENPAW_ADMIN_INOE_USER_IDS=",
        ),
        "Deployment",
    )
    env = {
        item["name"]: item["value"]
        for item in deployment["spec"]["template"]["spec"]["containers"][0][
            "env"
        ]
    }
    assert env["QWENPAW_ADMIN_INOE_USER_IDS"] == ""


def test_deny_all_and_operator_policy_opt_out() -> None:
    denied = render(
        CHART,
        "--set",
        "networkPolicy.dns.enabled=false",
        "--set",
        "networkPolicy.portalIngress.enabled=false",
    )
    policy = resource(denied, "NetworkPolicy")["spec"]
    assert policy["ingress"] == policy["egress"] == []
    opted_out = render(CHART, "--set", "networkPolicy.enabled=false")
    assert all(doc["kind"] != "NetworkPolicy" for doc in opted_out)


@pytest.mark.parametrize(
    "args",
    [
        ["--set", "persistence.enabled=false", "--set-json", "envFrom=[]"],
        [
            "--set",
            "persistence.workingDir.enabled=false",
            "--set",
            "persistence.secretDir.enabled=false",
            "--set",
            "persistence.backupsDir.enabled=false",
        ],
        [
            "--set",
            "persistence.rootBootstrap.enabled=false",
            "--set",
            "skillSync.enabled=false",
        ],
    ],
)
def test_storage_variants_have_writable_runtime_mounts(
    args: list[str],
) -> None:
    pod = resource(render(CHART, *args), "Deployment")["spec"]["template"][
        "spec"
    ]
    volumes = {item["name"] for item in pod["volumes"]}
    app = pod["containers"][0]
    mounts = {item["mountPath"]: item["name"] for item in app["volumeMounts"]}
    for directory in (
        "/app/runtime",
        "/tmp",
        "/app/working",
        "/app/working.secret",
        "/app/working.backups",
    ):
        assert mounts[directory] in volumes
    if "envFrom=[]" in args:
        assert "envFrom" not in app
        assert "initContainers" not in pod
    if "skillSync.enabled=false" in args:
        assert "initContainers" not in pod


def test_pvc_bootstrap_creates_private_custom_layout(tmp_path: Path) -> None:
    documents = render(
        CHART,
        "--set",
        f"persistence.rootBootstrap.mountPath={tmp_path}",
        "--set",
        "persistence.workingDir.subPath=custom/working",
        "--set",
        "persistence.secretDir.subPath=custom/secret",
        "--set",
        "persistence.backupsDir.subPath=custom/backups",
    )
    pod = resource(documents, "Deployment")["spec"]["template"]["spec"]
    bootstrap = pod["initContainers"][0]["command"][2]
    subprocess.run(["sh", "-ec", bootstrap], check=True)
    assert (tmp_path / "custom/secret").stat().st_mode & 0o777 == 0o700
    assert (tmp_path / "custom/working").stat().st_mode & 0o777 == 0o750
    assert (tmp_path / "custom/backups").stat().st_mode & 0o777 == 0o750
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    legacy = subprocess.run(
        ["sh", "-ec", bootstrap],
        capture_output=True,
        text=True,
    )
    assert legacy.returncode != 0
    assert "migration is required" in legacy.stderr


def test_image_excludes_credentials_and_drops_root_after_install() -> None:
    dockerfile = (ROOT / "deploy-all/qwenpaw/Dockerfile").read_text()
    copies = re.findall(r"^COPY .*(?:\n\s+.*)?", dockerfile, re.MULTILINE)
    assert all("qwenpaw/data" not in line for line in copies)
    assert ".working.secret.backup" not in dockerfile
    assert dockerfile.rindex("USER 10001:10001") > dockerfile.rindex("RUN ")
    assert "ENV QWENPAW_SSO_TOKEN_REQUIRED=true" in dockerfile
    assert 'ENV QWENPAW_ADMIN_INOE_USER_IDS="1"' in dockerfile
    assert "QWENPAW_AUTH_ENABLED" not in dockerfile
    assert "--legacy-peer-deps" not in dockerfile
    assert "chmod 777" not in dockerfile
    ignore = (ROOT / ".dockerignore").read_text().splitlines()
    assert "deploy-all/qwenpaw/data" in ignore
    assert "**/.master_key" in ignore
    assert not any(
        line.startswith("!deploy-all/qwenpaw/data") for line in ignore
    )
    entrypoint = (ROOT / "deploy-all/qwenpaw/entrypoint.sh").read_text()
    assert "SECRET_BACKUP" not in entrypoint
    supervisor = (
        ROOT / "deploy-all/qwenpaw/config/supervisord.conf.template"
    ).read_text()
    assert "user=root" not in supervisor
    assert "/var/log/" not in supervisor
    assert "--system" not in supervisor
    subprocess.run(
        ["sh", "-n", str(ROOT / "deploy-all/qwenpaw/entrypoint.sh")],
        check=True,
    )
