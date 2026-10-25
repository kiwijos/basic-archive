"""Checks rendered Kubernetes manifests against the security rules of Ship Archive Lite.

audit(documents) returns the findings, and an empty list means every rule holds. A rule that cannot be met by a
particular container (say, a database that must write its data directory) is excused by an entry in `exceptions`
that says why, and an exception nobody needs any more is a finding of its own, so the list cannot go stale.
"""

import re
from dataclasses import dataclass

import yaml

WORKLOADS = {"Deployment", "StatefulSet", "DaemonSet", "Job"}
LOOKS_SECRET = re.compile(r"token|secret|pass|key|credential|url", re.IGNORECASE)
PLACEHOLDER = "CHANGE_ME"
LONG_HEX = re.compile(r"[0-9a-f]{24,}")


# What the manifests of this repository are excused from, and why. A key is (workload, container, rule).
EXCEPTIONS = {
    ("StatefulSet/garage", "own-volume", "non-root"): (
        "Runs as root for a moment, with only the capabilities needed to hand a volume from before slice 13, whose "
        "files are root-owned, to the user Garage now runs as. The kubelet does not re-own hostPath volumes."
    ),
    ("StatefulSet/garage", "own-volume", "no-added-capabilities"): (
        "CHOWN, DAC_OVERRIDE and FOWNER are what changing the owner of root-owned files takes; nothing else is added."
    ),
}


# Who may read each Secret: the workload that is the secret's owner, and a Job that sets up what the secret opens.
# Meilisearch's master key is read only by Meilisearch and the Job that registers the service keys derived from it; the
# indexer holds its own derived key (indexes only) and search-api a search-only key. Each S3 key is read by its one
# service and by garage-init, which gives it its permissions. A Secret nobody here reads (the Ingress's certificate,
# read by the Ingress controller) is not listed.
AUDIENCE = {
    "meilisearch-secrets": {"StatefulSet/meilisearch", "Job/meilisearch-init"},
    "indexer-env": {"Deployment/indexer"},
    "search-api-env": {"Deployment/search-api"},
    "postgres-credentials": {"StatefulSet/postgres"},
    "catalog-api-secrets": {"Deployment/catalog-api", "Job/catalog-api-migrate"},
    "catalog-api-service-tokens": {"Deployment/catalog-api"},
    "catalog-api-amqp": {"Deployment/catalog-api"},
    "catalog-api-s3": {"Deployment/catalog-api", "Job/garage-init"},
    "cantaloupe-s3": {"Deployment/cantaloupe", "Job/garage-init"},
    "garage-secrets": {"StatefulSet/garage", "Job/garage-init"},
    "transcribe-worker-env": {"Deployment/transcribe-worker"},
    "rabbitmq-credentials": {"StatefulSet/rabbitmq"},
    "rabbitmq-users": {"StatefulSet/rabbitmq"},
}


def _secrets_read(pod: dict) -> set[str]:
    """Every Secret a pod gets: as environment variables, one key at a time, or mounted as files."""
    names = set()
    for container in _containers(pod):
        names |= {source["secretRef"]["name"] for source in container.get("envFrom", []) if "secretRef" in source}
        for variable in container.get("env", []):
            reference = (variable.get("valueFrom") or {}).get("secretKeyRef")
            if reference:
                names.add(reference["name"])
    for volume in pod.get("volumes", []):
        if "secret" in volume:
            names.add(volume["secret"]["secretName"])
        for source in (volume.get("projected") or {}).get("sources", []):
            if "secret" in source:
                names.add(source["secret"]["name"])
    return names


@dataclass(frozen=True)
class Violation:
    rule: str
    where: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.rule}: {self.where}" + (f" ({self.detail})" if self.detail else "")


def load(text: str) -> list[dict]:
    return [document for document in yaml.safe_load_all(text) if document]


def _name(document: dict) -> str:
    return f"{document['kind']}/{document['metadata']['name']}"


def _pod(document: dict) -> dict:
    return document["spec"]["template"]["spec"]


def _containers(pod: dict) -> list[dict]:
    return [*pod.get("initContainers", []), *pod.get("containers", [])]


def _effective(pod: dict, container: dict, field: str):
    """A container's own setting wins over the pod's."""
    own = (container.get("securityContext") or {}).get(field)
    return own if own is not None else (pod.get("securityContext") or {}).get(field)


def _pinned(image: str) -> bool:
    if "@sha256:" in image:
        return True
    name = image.rsplit("/", 1)[-1]
    return ":" in name and not name.endswith(":latest")


def _container_findings(pod: dict, container: dict) -> list[tuple[str, str]]:
    context = container.get("securityContext") or {}
    found = []
    if _effective(pod, container, "runAsNonRoot") is not True:
        found.append(("non-root", "runAsNonRoot is not true"))
    if context.get("allowPrivilegeEscalation") is not False:
        found.append(("no-privilege-escalation", "allowPrivilegeEscalation is not false"))
    if (context.get("capabilities") or {}).get("drop") != ["ALL"]:
        found.append(("drop-all-capabilities", "capabilities are not dropped"))
    if (context.get("capabilities") or {}).get("add"):
        found.append(("no-added-capabilities", f"adds {', '.join(context['capabilities']['add'])}"))
    if context.get("readOnlyRootFilesystem") is not True:
        found.append(("read-only-root-filesystem", "the root filesystem is writable"))
    profile = _effective(pod, container, "seccompProfile") or {}
    if profile.get("type") != "RuntimeDefault":
        found.append(("seccomp", "no RuntimeDefault seccomp profile"))
    if not ((container.get("resources") or {}).get("limits") or {}).get("memory"):
        found.append(("memory-limit", "no memory limit"))
    if not _pinned(container.get("image", "")):
        found.append(("pinned-image", container.get("image", "")))
    return found


def _selects(policy: dict, labels: dict) -> bool:
    wanted = (policy["spec"].get("podSelector") or {}).get("matchLabels") or {}
    return bool(wanted) and all(labels.get(key) == value for key, value in wanted.items())


def _is_default_deny(policy: dict) -> bool:
    spec = policy["spec"]
    return (
        not spec.get("podSelector")
        and {"Ingress", "Egress"} <= set(spec.get("policyTypes", []))
        and not spec.get("ingress")
        and not spec.get("egress")
    )


def _holds_real_secret(document: dict) -> bool:
    for key, value in {**document.get("stringData", {}), **document.get("data", {})}.items():
        value = str(value)
        if PLACEHOLDER in value:
            continue
        if LOOKS_SECRET.search(key) or LONG_HEX.search(value):
            return True
    return False


def audit(
    documents: list[dict],
    exceptions: dict[tuple[str, str, str], str] | None = None,
    audience: dict[str, set[str]] | None = None,
) -> list[Violation]:
    """`audience` says which workloads may read each Secret; leave it out to skip that rule."""
    exceptions = exceptions or {}
    used: set[tuple[str, str, str]] = set()
    violations: list[Violation] = []
    policies = [d for d in documents if d.get("kind") == "NetworkPolicy"]
    allows = [p for p in policies if not _is_default_deny(p)]
    namespaces = set()

    for document in documents:
        kind = document.get("kind")
        if kind in WORKLOADS:
            name, pod = _name(document), _pod(document)
            namespaces.add(document["metadata"].get("namespace", "default"))
            for container in _containers(pod):
                for rule, detail in _container_findings(pod, container):
                    key = (name, container["name"], rule)
                    if key in exceptions:
                        used.add(key)
                        continue
                    violations.append(Violation(rule, f"{name} container {container['name']}", detail))
            if audience is not None:
                for secret in sorted(_secrets_read(pod)):
                    if name not in audience.get(secret, set()):
                        violations.append(Violation("secret-audience", f"{name} reads {secret}", "not in that secret's stated audience"))
            if pod.get("enableServiceLinks") is not False:
                violations.append(Violation("no-service-links", name, "every Service's address and port is put in the pod's environment"))
            if pod.get("automountServiceAccountToken") is not False:
                violations.append(Violation("no-service-account-token", name, "the pod can read a Kubernetes API token it does not need"))
            labels = document["spec"]["template"].get("metadata", {}).get("labels", {})
            if not any(_selects(policy, labels) for policy in allows):
                violations.append(Violation("network-policy", name, "no NetworkPolicy allows anything to or from this pod"))
        elif kind == "Service" and document["spec"].get("type") in {"NodePort", "LoadBalancer"}:
            violations.append(Violation("internal-service", _name(document), f"type {document['spec']['type']} is reachable from outside"))
        elif kind == "Ingress" and not document["spec"].get("tls"):
            violations.append(Violation("ingress-tls", _name(document), "no TLS section"))
        elif kind == "Secret" and _holds_real_secret(document):
            violations.append(Violation("no-real-secret", _name(document), "a value is not a CHANGE_ME placeholder"))

    for namespace in sorted(namespaces):
        denying = [p for p in policies if p["metadata"].get("namespace", "default") == namespace and _is_default_deny(p)]
        if not denying:
            violations.append(Violation("default-deny", namespace, "no policy denies all ingress and egress by default"))

    for key, reason in exceptions.items():
        if key not in used:
            violations.append(Violation("unused-exception", "/".join(key), reason))
    return violations
