import copy
import subprocess
from pathlib import Path

import pytest
import yaml

from hardening.audit import AUDIENCE, EXCEPTIONS, audit, load
from hardening.policies import ALLOWED, render

ROOT = Path(__file__).resolve().parents[2]


def container(**overrides) -> dict:
    spec = {
        "name": "app",
        "image": "kiwijos/ship-archive-catalog-api:1.0.0",
        "securityContext": {
            "runAsNonRoot": True,
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "capabilities": {"drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "resources": {"requests": {"memory": "64Mi"}, "limits": {"memory": "128Mi"}},
    }
    spec.update(overrides)
    return spec


def deployment(name="app", containers=None, **pod) -> dict:
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": "ship-archive"},
        "spec": {
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {"labels": {"app": name}},
                "spec": {"automountServiceAccountToken": False, "enableServiceLinks": False, "containers": containers or [container()], **pod},
            },
        },
    }


def policies(*names) -> list[dict]:
    """A default deny for the namespace and one allow rule that selects each named app."""
    deny = {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": "default-deny", "namespace": "ship-archive"},
            "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}}
    allows = [
        {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": f"allow-{n}", "namespace": "ship-archive"},
         "spec": {"podSelector": {"matchLabels": {"app": n}}, "policyTypes": ["Ingress"], "ingress": [{}]}}
        for n in names
    ]
    return [deny, *allows]


def found(documents, rule) -> list[str]:
    return [v.where for v in audit(documents) if v.rule == rule]


def test_a_workload_that_follows_every_rule_has_no_findings():
    assert audit([deployment(), *policies("app")]) == []


@pytest.mark.parametrize(
    "rule, change",
    [
        ("non-root", lambda c: c["securityContext"].pop("runAsNonRoot")),
        ("non-root", lambda c: c["securityContext"].update(runAsNonRoot=False)),
        ("no-privilege-escalation", lambda c: c["securityContext"].pop("allowPrivilegeEscalation")),
        ("drop-all-capabilities", lambda c: c["securityContext"].update(capabilities={"drop": ["NET_RAW"]})),
        ("read-only-root-filesystem", lambda c: c["securityContext"].update(readOnlyRootFilesystem=False)),
        ("seccomp", lambda c: c["securityContext"].pop("seccompProfile")),
        ("no-added-capabilities", lambda c: c["securityContext"]["capabilities"].update(add=["NET_ADMIN"])),
        ("memory-limit", lambda c: c.update(resources={"requests": {"memory": "64Mi"}})),
        ("pinned-image", lambda c: c.update(image="kiwijos/ship-archive-catalog-api")),
        ("pinned-image", lambda c: c.update(image="kiwijos/ship-archive-catalog-api:latest")),
    ],
)
def test_each_container_rule_is_enforced(rule, change):
    broken = container()
    change(broken)

    assert found([deployment(containers=[broken]), *policies("app")], rule) == ["Deployment/app container app"]


def test_the_pod_level_setting_counts_for_every_container_in_the_pod():
    inner = container()
    inner["securityContext"].pop("runAsNonRoot")
    workload = deployment(containers=[inner], securityContext={"runAsNonRoot": True})

    assert found([workload, *policies("app")], "non-root") == []


def test_init_containers_and_jobs_are_held_to_the_same_rules():
    bad = container(name="init")
    bad["securityContext"]["capabilities"] = {}
    workload = deployment(initContainers=[bad])
    job = {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": "migrate", "namespace": "ship-archive"},
           "spec": {"template": {"metadata": {"labels": {"app": "migrate"}}, "spec": {"automountServiceAccountToken": False, "enableServiceLinks": False, "containers": [bad]}}}}

    assert found([workload, job, *policies("app", "migrate")], "drop-all-capabilities") == ["Deployment/app container init", "Job/migrate container init"]


def test_a_pod_that_can_use_the_kubernetes_api_without_needing_it_is_a_finding():
    workload = deployment()
    del workload["spec"]["template"]["spec"]["automountServiceAccountToken"]

    assert found([workload, *policies("app")], "no-service-account-token") == ["Deployment/app"]


def test_a_pod_that_is_told_about_every_service_by_environment_variable_is_a_finding():
    workload = deployment()
    del workload["spec"]["template"]["spec"]["enableServiceLinks"]

    assert found([workload, *policies("app")], "no-service-links") == ["Deployment/app"]


def test_a_stated_exception_excuses_that_one_finding_and_says_why():
    workload = deployment(containers=[container(name="db")])
    workload["spec"]["template"]["spec"]["containers"][0]["securityContext"]["readOnlyRootFilesystem"] = False
    exceptions = {("Deployment/app", "db", "read-only-root-filesystem"): "writes its data directory"}

    assert audit([workload, *policies("app")], exceptions=exceptions) == []
    assert [v.rule for v in audit([workload, *policies("app")])] == ["read-only-root-filesystem"]


def test_an_exception_nobody_needs_any_more_is_itself_a_finding():
    exceptions = {("Deployment/app", "app", "read-only-root-filesystem"): "stale"}

    assert [v.rule for v in audit([deployment(), *policies("app")], exceptions=exceptions)] == ["unused-exception"]


def test_without_a_default_deny_nothing_is_protected():
    only_allow = policies("app")[1:]

    assert found([deployment(), *only_allow], "default-deny") == ["ship-archive"]


def test_a_default_deny_of_only_one_direction_is_not_enough():
    documents = policies("app")
    documents[0]["spec"]["policyTypes"] = ["Ingress"]

    assert found([deployment(), *documents], "default-deny") == ["ship-archive"]


def test_a_workload_that_no_policy_selects_is_reported():
    assert found([deployment(), *policies("other")], "network-policy") == ["Deployment/app"]


def test_a_service_open_to_the_outside_is_a_finding():
    service = {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "db", "namespace": "ship-archive"}, "spec": {"type": "NodePort"}}

    assert found([deployment(), *policies("app"), service], "internal-service") == ["Service/db"]


def test_an_ingress_without_tls_is_a_finding():
    ingress = {"apiVersion": "networking.k8s.io/v1", "kind": "Ingress", "metadata": {"name": "site", "namespace": "ship-archive"}, "spec": {"rules": []}}
    secure = copy.deepcopy(ingress)
    secure["spec"]["tls"] = [{"secretName": "ship-archive-tls", "hosts": ["localhost"]}]

    assert found([deployment(), *policies("app"), ingress], "ingress-tls") == ["Ingress/site"]
    assert found([deployment(), *policies("app"), secure], "ingress-tls") == []


@pytest.mark.parametrize("value", ["hunter2-but-real", "9f2c0d7e5a1b4c3d8e6f7a8b9c0d1e2f"])
def test_a_secret_with_a_real_looking_value_is_a_finding_but_a_placeholder_is_not(value):
    secret = lambda v: {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "s", "namespace": "ship-archive"}, "stringData": {"TOKEN": v}}  # noqa: E731

    assert found([deployment(), *policies("app"), secret(value)], "no-real-secret") == ["Secret/s"]
    assert found([deployment(), *policies("app"), secret("CHANGE_ME")], "no-real-secret") == []


def test_a_secret_url_may_carry_a_placeholder_password():
    secret = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "s", "namespace": "ship-archive"},
              "stringData": {"DATABASE_URL": "postgresql+psycopg://postgres:CHANGE_ME@postgres:5432/archive", "STAFF": "alice=CHANGE_ME,bob=CHANGE_ME", "KEY": "GKCHANGE_ME"}}

    assert found([deployment(), *policies("app"), secret], "no-real-secret") == []


def reading(name, *secrets, via="envFrom") -> dict:
    """A workload whose one container reads the given Secrets, as environment variables or as volumes."""
    workload = deployment(name)
    pod = workload["spec"]["template"]["spec"]
    if via == "envFrom":
        pod["containers"][0]["envFrom"] = [{"secretRef": {"name": s}} for s in secrets]
    elif via == "env":
        pod["containers"][0]["env"] = [{"name": "X", "valueFrom": {"secretKeyRef": {"name": s, "key": "k"}}} for s in secrets]
    else:
        pod["volumes"] = [{"name": s, "secret": {"secretName": s}} for s in secrets]
    return workload


@pytest.mark.parametrize("via", ["envFrom", "env", "volume"])
def test_a_secret_read_by_a_workload_outside_its_audience_is_a_finding_however_it_is_read(via):
    audience = {"master-key": {"Deployment/indexer"}}
    documents = [reading("indexer", "master-key", via=via), reading("search", "master-key", via=via), *policies("indexer", "search")]

    assert [(v.rule, v.where) for v in audit(documents, audience=audience)] == [("secret-audience", "Deployment/search reads master-key")]


def test_a_secret_with_no_stated_audience_is_a_finding_so_a_new_one_cannot_be_forgotten():
    documents = [reading("indexer", "brand-new"), *policies("indexer")]

    assert [v.rule for v in audit(documents, audience={})] == ["secret-audience"]


def test_the_audience_names_of_this_repository_are_real_workloads_and_secrets():
    assert AUDIENCE["meilisearch-secrets"] == {"StatefulSet/meilisearch", "Job/meilisearch-init"}
    assert "Deployment/indexer" not in AUDIENCE["meilisearch-secrets"], "the indexer holds a key derived from the master key, never the master key"


def test_the_manifests_of_this_repository_follow_every_rule():
    rendered = subprocess.run(["kubectl", "kustomize", str(ROOT / "k8s")], capture_output=True, text=True, check=True).stdout
    template = (ROOT / "k8s" / "secrets.template.yaml").read_text()
    documents = load(rendered) + load(template)

    assert [str(v) for v in audit(documents, exceptions=EXCEPTIONS, audience=AUDIENCE)] == []
    assert any(d.get("kind") == "Deployment" for d in documents) and any(d.get("kind") == "NetworkPolicy" for d in documents)


def test_every_exception_of_this_repository_says_why():
    assert EXCEPTIONS
    for key, reason in EXCEPTIONS.items():
        assert len(reason) > 40, f"{key}: say why in a sentence"


def test_the_policies_in_the_repository_are_what_the_table_of_paths_generates():
    assert (ROOT / "k8s" / "network-policies.yaml").read_text() == render(), "run: uv run python -m hardening.policies > ../k8s/network-policies.yaml"


def test_every_path_is_one_egress_rule_and_one_ingress_rule_because_a_connection_needs_both():
    policies = [d for d in load(render()) if d["kind"] == "NetworkPolicy"]
    egress = [p["metadata"]["name"] for p in policies if p["spec"]["policyTypes"] == ["Egress"] and p["metadata"]["name"].startswith("allow-") and "-to-" in p["metadata"]["name"]]
    ingress = [p["metadata"]["name"] for p in policies if p["spec"]["policyTypes"] == ["Ingress"] and "-from-" in p["metadata"]["name"]]

    assert len(egress) >= len(ALLOWED) and len(ingress) == len(ALLOWED)
    for source, destination, port, _ in ALLOWED:
        assert f"allow-{source}-to-{destination}" in egress
        assert f"allow-{destination}-from-{source}" in ingress
