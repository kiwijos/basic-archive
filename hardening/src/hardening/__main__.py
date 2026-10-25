"""python -m hardening [K8S_DIR]: render the manifests, audit them, and exit 1 if any rule is broken."""

import subprocess
import sys
from pathlib import Path

from hardening.audit import AUDIENCE, EXCEPTIONS, WORKLOADS, audit, load


def main() -> int:
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[3] / "k8s"
    rendered = subprocess.run(["kubectl", "kustomize", str(directory)], capture_output=True, text=True, check=True).stdout
    documents = load(rendered) + load((directory / "secrets.template.yaml").read_text())
    findings = audit(documents, exceptions=EXCEPTIONS, audience=AUDIENCE)
    for finding in findings:
        print(f"FAIL {finding}")
    workloads = sum(1 for d in documents if d.get("kind") in WORKLOADS)
    print(f"{workloads} workloads audited, {len(findings)} finding(s), {len(EXCEPTIONS)} stated exception(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
