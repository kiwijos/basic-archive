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

TARGETS = {
    "postgres": ("postgres", 5432),
    "garage-s3": ("garage", 3900),
    "garage-admin": ("garage", 3903),
    "rabbitmq": ("rabbitmq", 5672),
    "meilisearch": ("meilisearch", 7700),
    "catalog-api": ("catalog-api", 8000),
    "search-api": ("search-api", 8000),
    "web-ui": ("web-ui", 8080),
    "cantaloupe": ("cantaloupe", 8182),
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

SOURCES = {
    "catalog-api": ("deploy/catalog-api", "python"),
    "search-api": ("deploy/search-api", "python"),
    "indexer": ("deploy/indexer", "python"),
    "transcribe-worker": ("deploy/transcribe-worker", "python"),
    "cantaloupe": ("deploy/cantaloupe", "bash"),
    "web-ui": ("deploy/web-ui", "nc"),
    "postgres": ("sts/postgres", "nc"),
    "rabbitmq": ("sts/rabbitmq", "nc"),
    "meilisearch": ("sts/meilisearch", "nc"),
}

ALLOWED = {
    ("catalog-api", "postgres"), ("catalog-api", "garage-s3"), ("catalog-api", "rabbitmq"), ("catalog-api", "internet:443"),
    ("search-api", "meilisearch"),
    ("indexer", "rabbitmq"), ("indexer", "catalog-api"), ("indexer", "meilisearch"),
    ("transcribe-worker", "rabbitmq"), ("transcribe-worker", "catalog-api"), ("transcribe-worker", "garage-s3"),
    ("cantaloupe", "garage-s3"),
}


def probe(source: str, host: str, port: int) -> str:
    target, method = SOURCES[source]
    if method == "python":
        command = ["python", "-c", PYTHON, host, str(port)]
    elif method == "bash":
        command = ["bash", "-c", f"timeout 3 bash -c 'exec 3<>/dev/tcp/{host}/{port}' 2>&1; echo rc=$?"]
    else:
        command = ["sh", "-c", f"nc -w 3 {host} {port} </dev/null 2>&1; echo rc=$?"]
    done = subprocess.run(["kubectl", "-n", NAMESPACE, "exec", target, "--", *command], capture_output=True, text=True, timeout=60)
    out = (done.stdout + done.stderr).strip()
    if method == "python":
        return out.splitlines()[-1] if out else f"error: {done.stderr[:80]}"
    rc = out.splitlines()[-1] if out else ""
    refused = "refused" in out.lower()
    if rc == "rc=0" or refused:
        return "open"
    return "blocked" if rc in ("rc=124", "rc=1") else f"error: {out[:80]}"


def internet_reachable() -> bool:
    return subprocess.run(["nc", "-zw3", "1.1.1.1", "443"], capture_output=True).returncode == 0


def main() -> int:
    targets = dict(TARGETS)
    if not internet_reachable():
        print("note: this machine cannot reach 1.1.1.1:443, so the internet columns are left out")
        targets = {k: v for k, v in targets.items() if not k.startswith("internet")}

    def row(source: str) -> tuple[str, dict[str, str]]:
        # A pod is not asked to reach itself.
        return source, {name: probe(source, host, port) for name, (host, port) in targets.items() if host != source}

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        results = dict(pool.map(row, SOURCES))

    print(f"{'from \\ to':<19}" + "".join(f"{name:<14}" for name in targets))
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
        print(f"{source:<19}" + "".join(cells))

    headline = results["search-api"].get("postgres")
    print()
    print(f"search-api -> postgres:5432 is {headline}" + (" (the connection timed out: the policies dropped it)" if headline == "blocked" else ""))
    if wrong:
        print("\nWRONG:")
        for source, name, expected, got in wrong:
            print(f"  {source} -> {name}: expected {expected}, got {got}")
        return 1
    print(f"OK: {len(ALLOWED)} allowed paths open and every other connection among {len(SOURCES)} pods and {len(targets)} destinations is blocked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
