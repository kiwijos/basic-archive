"""Proves the NetworkPolicies from inside the running pods.

Every pod that has some way to open a TCP connection tries every internal service port. A connection that is allowed
reaches the service, or is refused by it; a connection the policies forbid is dropped, so it times out. A "refused"
answer therefore counts as the path being open, and only a timeout counts as blocked.

ALLOWED is the list of agreed paths, written out by hand from the ticket (plus the one the ticket missed: the worker
downloads a scan from Garage through the address catalog-api signed). It is deliberately not derived from the
policies, so the policies cannot mark their own work.
"""

import concurrent.futures
import subprocess
import sys

NAMESPACE = "ship-archive"
INGRESS_NAMESPACE = "traefik"
PROBE_IMAGE = "busybox:1.37.0"


def internal(service: str) -> str:
    """The full name, so the probe pods in another namespace resolve it too."""
    return f"{service}.{NAMESPACE}.svc.cluster.local"


TARGETS = {
    "postgres": (internal("postgres"), 5432),
    "garage-s3": (internal("garage"), 3900),
    "garage-admin": (internal("garage"), 3903),
    "rabbitmq": (internal("rabbitmq"), 5672),
    "meilisearch": (internal("meilisearch"), 7700),
    "catalog-api": (internal("catalog-api"), 8000),
    "search-api": (internal("search-api"), 8000),
    "web-ui": (internal("web-ui"), 8080),
    "cantaloupe": (internal("cantaloupe"), 8182),
    "internet:443": ("1.1.1.1", 443),
    "internet:80": ("1.1.1.1", 80),
}

PYTHON = (
    "import socket,sys\n"
    "s=socket.socket();s.settimeout(3)\n"
    "try:\n s.connect((sys.argv[1],int(sys.argv[2])));print('open')\n"
    "except ConnectionRefusedError:print('open')\n"  # the service answered: the path exists
    "except OSError:print('blocked')\n"
)

# name -> (namespace, what to exec in, how to open a connection)
SOURCES = {
    "catalog-api": (NAMESPACE, "deploy/catalog-api", "python"),
    "search-api": (NAMESPACE, "deploy/search-api", "python"),
    "indexer": (NAMESPACE, "deploy/indexer", "python"),
    "transcribe-worker": (NAMESPACE, "deploy/transcribe-worker", "python"),
    "cantaloupe": (NAMESPACE, "deploy/cantaloupe", "bash"),
    "web-ui": (NAMESPACE, "deploy/web-ui", "nc"),
    "postgres": (NAMESPACE, "sts/postgres", "nc"),
    "rabbitmq": (NAMESPACE, "sts/rabbitmq", "nc"),
    "meilisearch": (NAMESPACE, "sts/meilisearch", "nc"),
    # The Ingress controller's own image has no shell, so a throwaway pod in its namespace wears its labels: the policies
    # judge a pod by its namespace and labels, so it is treated exactly as Traefik is. A second pod in that namespace
    # without the labels shows that being near the controller is not enough.
    "ingress-controller": (INGRESS_NAMESPACE, "pod/np-ingress-like", "nc"),
    "stranger": (INGRESS_NAMESPACE, "pod/np-stranger", "nc"),
}
PROBE_PODS = {
    "np-ingress-like": {"app.kubernetes.io/name": "traefik"},
    "np-stranger": {"app": "np-stranger"},
}

ALLOWED = {
    ("catalog-api", "postgres"), ("catalog-api", "garage-s3"), ("catalog-api", "rabbitmq"), ("catalog-api", "internet:443"),
    ("search-api", "meilisearch"),
    ("indexer", "rabbitmq"), ("indexer", "catalog-api"), ("indexer", "meilisearch"),
    ("transcribe-worker", "rabbitmq"), ("transcribe-worker", "catalog-api"), ("transcribe-worker", "garage-s3"),
    ("cantaloupe", "garage-s3"),
    ("ingress-controller", "web-ui"), ("ingress-controller", "catalog-api"), ("ingress-controller", "search-api"), ("ingress-controller", "cantaloupe"),
}


def probe(source: str, host: str, port: int) -> str:
    namespace, target, method = SOURCES[source]
    if method == "python":
        command = ["python", "-c", PYTHON, host, str(port)]
    elif method == "bash":
        command = ["bash", "-c", f"timeout 3 bash -c 'exec 3<>/dev/tcp/{host}/{port}' 2>&1; echo rc=$?"]
    else:
        command = ["sh", "-c", f"nc -w 3 {host} {port} </dev/null 2>&1; echo rc=$?"]
    done = subprocess.run(["kubectl", "-n", namespace, "exec", target, "--", *command], capture_output=True, text=True, timeout=60)
    out = (done.stdout + done.stderr).strip()
    if method == "python":
        return out.splitlines()[-1] if out else f"error: {done.stderr[:80]}"
    rc = out.splitlines()[-1] if out else ""
    refused = "refused" in out.lower()
    if rc == "rc=0" or refused:
        return "open"
    return "blocked" if rc in ("rc=124", "rc=1") else f"error: {out[:80]}"


def probe_pods(create: bool) -> None:
    """The two throwaway pods the Ingress-controller rows are probed from."""
    if not create:
        subprocess.run(["kubectl", "-n", INGRESS_NAMESPACE, "delete", "pod", *PROBE_PODS, "--ignore-not-found", "--wait=false", "--grace-period=1"], capture_output=True)
        return
    for name, labels in PROBE_PODS.items():
        label_args = ",".join(f"{k}={v}" for k, v in labels.items())
        subprocess.run(["kubectl", "-n", INGRESS_NAMESPACE, "delete", "pod", name, "--ignore-not-found"], capture_output=True)
        subprocess.run(["kubectl", "-n", INGRESS_NAMESPACE, "run", name, f"--labels={label_args}", f"--image={PROBE_IMAGE}", "--image-pull-policy=IfNotPresent",
                        "--restart=Never", "--command", "--", "sleep", "900"], capture_output=True, check=True)
    subprocess.run(["kubectl", "-n", INGRESS_NAMESPACE, "wait", "--for=condition=Ready", *[f"pod/{n}" for n in PROBE_PODS], "--timeout=90s"], capture_output=True, check=True)


def internet_reachable() -> bool:
    return subprocess.run(["nc", "-zw3", "1.1.1.1", "443"], capture_output=True).returncode == 0


def main() -> int:
    targets = dict(TARGETS)
    if not internet_reachable():
        print("note: this machine cannot reach 1.1.1.1:443, so the internet columns are left out")
        targets = {k: v for k, v in targets.items() if not k.startswith("internet")}

    def row(source: str) -> tuple[str, dict[str, str]]:
        # A pod is not asked to reach itself, and these policies govern only this namespace's egress, so the probe pods in
        # the Ingress controller's namespace are not asked about the internet.
        outside = SOURCES[source][0] != NAMESPACE
        return source, {name: probe(source, host, port) for name, (host, port) in targets.items()
                        if not host.startswith(f"{source}.") and not (outside and name.startswith("internet"))}

    probe_pods(create=True)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
            results = dict(pool.map(row, SOURCES))
    finally:
        probe_pods(create=False)

    print(f"{'from \\ to':<20}" + "".join(f"{name:<14}" for name in targets))
    wrong = []
    for source in SOURCES:
        cells = []
        for name in targets:
            got = results[source].get(name)
            expected = "open" if (source, name) in ALLOWED else "blocked"
            if got is None or source == name:
                cells.append(f"{'-':<14}")
                continue
            cells.append(f"{'ok ' + got:<14}" if got == expected else f"{'WRONG ' + got:<14}")
            if got != expected:
                wrong.append((source, name, expected, got))
        print(f"{source:<20}" + "".join(cells))

    headline = results["search-api"].get("postgres")
    print()
    print(f"search-api -> postgres:5432 is {headline}" + (" (the connection timed out: the policies dropped it)" if headline == "blocked" else ""))
    if wrong:
        print("\nWRONG:")
        for source, name, expected, got in wrong:
            print(f"  {source} -> {name}: expected {expected}, got {got}")
        return 1
    print(f"OK: {len(ALLOWED)} allowed paths open and every other connection among {len(SOURCES)} sources and {len(targets)} destinations is blocked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
