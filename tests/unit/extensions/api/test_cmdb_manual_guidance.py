from __future__ import annotations

from qwenpaw.extensions.api.cmdb_manual_guidance import (
    build_manual_operation_guide,
    deployment_edges,
    public_deployment_attributes,
)


def _topology(kind: str | None = None):
    attrs = {"db_port": "3307", "manage_ip": "10.0.0.10"}
    if kind:
        attrs["deployment_kind"] = kind
    root = {
        "resId": "1",
        "ciType": "mysql",
        "name": "db",
        "publicAttributes": attrs,
    }
    return {"rootResource": root, "resources": [root], "queryComplete": True}


def test_confirmed_k3s_has_full_manual_access_and_diagnostic_chain():
    topology = _topology("k3s")
    topology["rootResource"]["publicAttributes"].update(
        {
            "kube_context": "production-k3s",
            "namespace": "database",
            "pod_name": "mysql-primary-0",
            "container_name": "mysql",
        }
    )
    guide = build_manual_operation_guide(topology, alarm_title="MySQL 慢 SQL")
    assert guide["deploymentKind"] == "kubernetes"
    assert guide["deploymentConfirmed"]
    assert guide["executionMode"] == "manual-only"
    assert guide["knownParameters"]["NAMESPACE"] == "database"
    assert "DB_USER" in guide["missingParameters"]
    text = guide["markdown"]
    assert text.index("kubectl config get-contexts") < text.index("exec -it")
    assert text.index("exec -it") < text.index("SHOW FULL PROCESSLIST")
    assert "events_statements_summary_by_digest" in text
    assert "--password" in text and "需人工确认审批" in text
    assert "恢复验证" in text and "系统未访问" in text


def test_explicit_host_deployment_is_not_overridden_by_related_kubernetes():
    topology = _topology("host")
    topology["resources"].append(
        {"resId": "2", "ciType": "kubernetes", "name": "related"}
    )
    guide = build_manual_operation_guide(topology)
    assert guide["deploymentKind"] == "host"
    assert "kubectl " not in guide["markdown"]
    assert 'mysql --host="$DB_HOST"' in guide["markdown"]


def test_docker_has_its_own_access_path_not_kubectl():
    topology = _topology("docker")
    topology["rootResource"]["publicAttributes"]["docker_name"] = "mysql-prod"
    guide = build_manual_operation_guide(topology)
    assert "docker inspect" in guide["markdown"]
    assert "docker exec -it" in guide["markdown"]
    assert "kubectl " not in guide["markdown"]


def test_association_is_only_a_conditional_kubernetes_candidate():
    topology = _topology()
    topology["resources"].append(
        {
            "resId": "2",
            "ciType": "kubernetes",
            "name": "related",
            "publicAttributes": {
                "namespace": "kube-system",
                "db_port": "6443",
            },
        }
    )
    guide = build_manual_operation_guide(topology)
    assert guide["deploymentKind"] == "kubernetes"
    assert not guide["deploymentConfirmed"]
    assert "关联到平台不等于部署" in guide["markdown"]
    assert "NAMESPACE" not in guide["knownParameters"]
    assert guide["knownParameters"]["DB_PORT"] == "3307"


def test_deploy_edges_can_confirm_a_placement_chain_but_contain_cannot():
    topology = _topology()
    topology["resources"].extend(
        [
            {"resId": "2", "ciType": "kubernetes", "name": "cluster"},
            {"resId": "3", "ciType": "docker", "name": "container"},
        ]
    )
    topology["edges"] = [
        {"src_ci_id": "2", "dst_ci_id": "3", "relation_type": "deploy"},
        {"src_ci_id": "3", "dst_ci_id": "1", "relation_type": "deploy"},
    ]
    assert build_manual_operation_guide(topology)["deploymentConfirmed"]
    topology["edges"][1]["relation_type"] = "contain"
    assert not build_manual_operation_guide(topology)["deploymentConfirmed"]


def test_sensitive_fields_are_not_retained_or_copied_into_commands():
    ci = {
        "deployment_kind": "k3s",
        "namespace": "database",
        "login_user": "secret-user",
        "login_pwd": "secret-password",
        "bearer_token": "secret-token",
        "private_key": "secret-key",
    }
    attrs = public_deployment_attributes(ci)
    assert attrs == {"deployment_kind": "k3s", "namespace": "database"}
    topology = _topology("k3s")
    topology["rootResource"]["publicAttributes"].update(ci)
    text = str(build_manual_operation_guide(topology))
    for secret in (
        "secret-user",
        "secret-password",
        "secret-token",
        "secret-key",
    ):
        assert secret not in text


def test_invalid_kubernetes_names_and_parent_host_are_not_bound():
    topology = _topology("k3s")
    topology["rootResource"]["publicAttributes"].update(
        {
            "namespace": "database;bad-command",
            "pod_name": "mysql\nbad",
        }
    )
    guide = build_manual_operation_guide(topology)
    assert "NAMESPACE" in guide["missingParameters"]
    assert "MYSQL_POD" in guide["missingParameters"]
    assert "bad-command" not in guide["markdown"]
    root = {"resId": "1", "ciType": "mysql", "publicAttributes": {}}
    topology = {
        "rootResource": root,
        "resources": [
            root,
            {
                "resId": "2",
                "ciType": "physicalmachine",
                "publicAttributes": {"manage_ip": "10.0.0.99"},
            },
        ],
        "edges": [
            {"src_ci_id": "2", "dst_ci_id": "1", "relation_type": "deploy"}
        ],
    }
    assert (
        "DB_HOST"
        not in build_manual_operation_guide(topology)["knownParameters"]
    )


def test_non_mysql_component_does_not_get_mysql_login_or_sql():
    topology = _topology("k3s")
    topology["rootResource"]["ciType"] = "redis"
    guide = build_manual_operation_guide(topology)
    assert "DB_USER" not in guide["missingParameters"]
    assert "SHOW FULL PROCESSLIST" not in guide["markdown"]


def test_edge_extraction_keeps_only_explicit_deploy_relations():
    rows = [{"relation": "deploy", "source": {"_id": 2}, "target": {"_id": 1}}]
    assert deployment_edges(rows) == [
        {"src_ci_id": "2", "dst_ci_id": "1", "relation_type": "deploy"}
    ]
    assert deployment_edges([{"src_ci_id": 2, "dst_ci_id": 1}]) == []


def test_conflicting_deployment_facts_are_not_treated_as_confirmed():
    topology = _topology("host")
    topology["resources"].append({"resId": "2", "ciType": "kubernetes"})
    topology["edges"] = [
        {
            "src_ci_id": "2",
            "dst_ci_id": "1",
            "relation_type": "deploy",
        }
    ]
    guide = build_manual_operation_guide(topology)
    assert guide["deploymentKind"] == "unknown"
    assert not guide["deploymentConfirmed"]


def test_invalid_container_names_and_conflicting_parameters_stay_unknown():
    topology = _topology("docker")
    topology["rootResource"]["publicAttributes"][
        "docker_name"
    ] = "--privileged"
    assert (
        "MYSQL_DOCKER_CONTAINER"
        in build_manual_operation_guide(topology)["missingParameters"]
    )
    topology = _topology("k3s")
    topology["rootResource"]["publicAttributes"].update(
        {
            "namespace": "invalid.namespace",
            "namespace_name": "valid-namespace",
            "pod_name": "invalid..pod",
            "container_name": "invalid.container",
        }
    )
    guide = build_manual_operation_guide(topology)
    assert "MYSQL_POD" in guide["missingParameters"]
    assert "MYSQL_CONTAINER" in guide["missingParameters"]
    topology["rootResource"]["publicAttributes"]["namespace"] = "another-valid"
    assert (
        "NAMESPACE"
        in build_manual_operation_guide(topology)["missingParameters"]
    )


def test_explicit_k3s_keeps_verified_parent_container_parameters():
    topology = _topology("k3s")
    topology["resources"].append(
        {
            "resId": "2",
            "ciType": "docker",
            "publicAttributes": {
                "namespace": "database",
                "pod_name": "mysql-0",
                "container_name": "mysql",
            },
        }
    )
    topology["edges"] = [
        {
            "src_ci_id": "2",
            "dst_ci_id": "1",
            "relation_type": "deploy",
        }
    ]
    guide = build_manual_operation_guide(topology)
    assert guide["knownParameters"]["MYSQL_POD"] == "mysql-0"
    assert guide["knownParameters"]["NAMESPACE"] == "database"


def test_multiple_placement_candidates_cannot_mix_connection_parameters():
    topology = _topology()
    topology["resources"].extend(
        [
            {
                "resId": "2",
                "ciType": "kubernetes",
                "publicAttributes": {"kube_context": "cluster-a"},
            },
            {"resId": "3", "ciType": "kubernetes"},
            {
                "resId": "4",
                "ciType": "pod",
                "publicAttributes": {
                    "namespace": "database-b",
                    "pod_name": "mysql-b",
                },
            },
        ]
    )
    topology["edges"] = [
        {"src_ci_id": "2", "dst_ci_id": "1", "relation_type": "deploy"},
        {"src_ci_id": "3", "dst_ci_id": "4", "relation_type": "deploy"},
        {"src_ci_id": "4", "dst_ci_id": "1", "relation_type": "deploy"},
    ]
    guide = build_manual_operation_guide(topology)
    assert not guide["deploymentConfirmed"]
    assert "KUBE_CONTEXT" in guide["missingParameters"]
    assert "MYSQL_POD" in guide["missingParameters"]


def test_non_ascii_database_ports_are_unknown_instead_of_crashing():
    for value in ("²", "٣٣٠٦"):
        topology = _topology("host")
        topology["rootResource"]["publicAttributes"]["db_port"] = value
        assert (
            "DB_PORT"
            in build_manual_operation_guide(topology)["missingParameters"]
        )
