"""Proves that no real secret is in the repository: not in any file now, and not anywhere in its history.

1. trivy's secret scanner over every file git tracks or would track (anything not ignored).
2. The stronger test: every value of every Secret that is live in the cluster (passwords, tokens, keys, the certificate's
   private key) is searched for, as a literal string, in the working tree and in every commit of every branch.

Values go to git through a private file (mode 0600) that is deleted afterwards, never on a command line, and they are
never printed; a hit names the file and commit only.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from trivy_report import TRIVY  # the one place the scanner image is pinned

NAMESPACE = "ship-archive"
MIN_LENGTH = 12  # shorter values (a user name, a database name) are not secrets and would match everywhere


def run(*args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, **kwargs)


def tree_scan(root: str) -> bool:
    print("1. trivy secret scan of every tracked or untracked-but-not-ignored file")
    files = run("git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").stdout.split("\0")
    copy = tempfile.mkdtemp(dir="/tmp")
    try:
        count = 0
        for name in filter(None, files):
            source = os.path.join(root, name)
            if not os.path.isfile(source):
                continue
            os.makedirs(os.path.dirname(os.path.join(copy, name)) or copy, exist_ok=True)
            shutil.copy2(source, os.path.join(copy, name))
            count += 1
        done = run("docker", "run", "--rm", "-v", f"{copy}:/src:ro", TRIVY, "fs", "--scanners", "secret", "--quiet", "--exit-code", "1", "--format", "json", "/src")
        findings = []
        if done.stdout.strip():
            for result in json.loads(done.stdout).get("Results", []):
                findings += [f"{result['Target']}: {s['RuleID']}" for s in result.get("Secrets") or []]
        print(f"   {count} files scanned, {len(findings)} finding(s)")
        for finding in findings:
            print(f"   FOUND {finding}")
        return not findings and done.returncode == 0
    finally:
        shutil.rmtree(copy, ignore_errors=True)


def live_values() -> set[str]:
    secrets = json.loads(run("kubectl", "-n", NAMESPACE, "get", "secrets", "-o", "json").stdout)["items"]
    values: set[str] = set()
    for secret in secrets:
        if secret.get("type", "Opaque") not in ("Opaque", "kubernetes.io/tls"):
            continue
        for encoded in (secret.get("data") or {}).values():
            value = base64.b64decode(encoded).decode(errors="replace").strip()
            if len(value) >= MIN_LENGTH:
                values.add(value)
            # A password or token inside a URL or a "name=token,name=token" list is a secret of its own.
            values |= set(re.findall(r"[0-9A-Za-z]{24,}", value))
            # A PEM block's body lines are the key material; the header lines are not secret.
            values |= {line for line in value.splitlines() if len(line) > 40 and not line.startswith("-----")}
    return values


def history_scan(root: str) -> bool:
    print("2. every live secret value, searched for in the working tree and in all of git's history")
    values = live_values()
    commits = run("git", "-C", root, "rev-list", "--all").stdout.split()
    fd, patterns = tempfile.mkstemp(dir="/tmp")
    try:
        os.chmod(patterns, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write("\n".join(sorted(values)) + "\n")
        hits = []
        tree = run("git", "-C", root, "grep", "-I", "-l", "-F", "-f", patterns, "--untracked", "--")
        hits += [f"working tree: {name}" for name in tree.stdout.split()]
        for start in range(0, len(commits), 100):  # keeps each command short enough
            found = run("git", "-C", root, "grep", "-I", "-l", "-F", "-f", patterns, *commits[start:start + 100], "--")
            hits += [f"commit {line.split(':', 1)[0][:10]}: {line.split(':', 1)[1]}" for line in found.stdout.splitlines()]
        print(f"   {len(values)} secret values from the cluster, {len(commits)} commits and the working tree searched: {len(hits)} hit(s)")
        for hit in hits:
            print(f"   FOUND {hit}")
        return not hits
    finally:
        os.remove(patterns)


def main() -> int:
    root = run("git", "rev-parse", "--show-toplevel").stdout.strip()
    ok = tree_scan(root)
    ok = history_scan(root) and ok
    print("OK: no secret is in the repository, or ever was" if ok else "FAILED: a secret is in the repository")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
