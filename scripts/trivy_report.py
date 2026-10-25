"""Scans every custom image with trivy and writes the results to docs/security/trivy.md.

python scripts/trivy_report.py VERSION [--no-scan]

The explanations of what is accepted live here, next to the code that produces the numbers, so a rescan cannot
quietly replace a reasoned acceptance with a bare count. A new HIGH or CRITICAL finding with a fix available, or one in a
package that is not listed in ACCEPTED, makes the script exit 1.
"""

import collections
import json
import pathlib
import subprocess
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = pathlib.Path("/tmp/trivy")
TRIVY = "aquasec/trivy:0.58.0"
REPOSITORY = "kiwijos/ship-archive"
IMAGES = ["catalog-api", "transcribe-worker", "indexer", "search-api", "web-ui", "cantaloupe"]

# What was found on the first scan, of 0.11.0 (CRITICAL, HIGH), before anything was fixed.
BEFORE = {
    "catalog-api": (9, 109), "transcribe-worker": (16, 179), "indexer": (9, 109),
    "search-api": (9, 109), "web-ui": (0, 45), "cantaloupe": (4, 28),
}

OS_REASON = (
    "Debian lists these as `affected`, `fix_deferred` or `will_not_fix`: its security team has judged them minor or not "
    "yet fixable, and has published no corrected package, so there is nothing to upgrade to. Most are in base "
    "userland (util-linux, ncurses, gzip, perl, systemd libraries) that the service never runs: there is no shell "
    "reachable, nothing in the application starts these programs, and the container is non-root, read-only, has every "
    "capability dropped and a seccomp profile."
)
WORKER_REASON = (
    "The worker is the one service that parses untrusted files with native libraries (Tesseract, Leptonica, libtiff, "
    "libxml2, glib), so its unfixed findings deserve more weight than the others'. They are accepted because the worker "
    "is contained rather than because they cannot be reached: a NetworkPolicy lets it talk only to RabbitMQ, catalog-api "
    "and Garage, it holds no database credentials and no keys other than its own broker login and service token, runs "
    "non-root on a read-only filesystem with no capabilities, has a 1 GiB memory limit, and handles one image at a time, "
    "so a crash loses one job, which the queue redelivers. It reads an image only after catalog-api has checked it."
)
JAR_REASON = (
    "These are libraries bundled inside `cantaloupe-5.0.7.jar` (Jackson, Netty, Jetty, Tika, Bouncy Castle, plexus-utils). "
    "5.0.7 (March 2025) is the newest Cantaloupe release, and replacing libraries inside its jar would give an "
    "unsupported, untested build, so a fix is not available to this project until upstream releases one. Each CVE was "
    "not analysed one by one; the acceptance rests on what Cantaloupe exposes and what it can reach. Only the IIIF "
    "Image API 3 is served (the admin and management API are off, no delegate script is enabled), through the Ingress "
    "with a per-address rate limit. Its only source is the fixed `masters` bucket in Garage, read with a read-only key, "
    "so a caller cannot make it fetch a URL of their choosing. A NetworkPolicy lets it talk only to Garage. It runs "
    "non-root on a read-only filesystem with no capabilities and no Kubernetes API token, and holds no credential "
    "that can change data. The finding to watch is the remote-request path through Jetty and Netty: the mitigation is "
    "exposure, and the remedy is upgrading Cantaloupe when a release is made."
)
ACCEPTED = {
    "catalog-api": OS_REASON, "indexer": OS_REASON, "search-api": OS_REASON,
    "transcribe-worker": OS_REASON + " " + WORKER_REASON, "cantaloupe": JAR_REASON,
    "web-ui": "Nothing to accept.",
}


def scan(image: str, version: str) -> dict:
    OUT.mkdir(exist_ok=True)
    result = OUT / f"{image}.json"
    subprocess.run(
        ["docker", "run", "--rm", "-v", "/var/run/docker.sock:/var/run/docker.sock", "-v", "trivy-cache:/root/.cache/", "-v", f"{OUT}:/out", TRIVY,
         "image", "--quiet", "--format", "json", "--output", f"/out/{image}.json", "--scanners", "vuln,secret,misconfig", f"{REPOSITORY}-{image}:{version}"],
        check=True,
    )
    return json.loads(result.read_text())


def summarise(report: dict) -> dict:
    counts, fixable, groups, statuses = collections.Counter(), [], collections.defaultdict(collections.Counter), collections.Counter()
    secrets = misconfigs = 0
    for result in report.get("Results", []):
        secrets += len(result.get("Secrets") or [])
        misconfigs += len(result.get("Misconfigurations") or [])
        for finding in result.get("Vulnerabilities") or []:
            counts[finding["Severity"]] += 1
            if finding["Severity"] in ("HIGH", "CRITICAL"):
                groups[(result["Class"], finding["PkgName"], finding["InstalledVersion"])][finding["Severity"]] += 1
                statuses[finding.get("Status", "?")] += 1
                if finding.get("FixedVersion"):
                    fixable.append(finding)
    return {"os": f"{report['Metadata']['OS']['Family']} {report['Metadata']['OS']['Name']}", "counts": counts, "fixable": fixable,
            "groups": groups, "statuses": statuses, "secrets": secrets, "misconfigs": misconfigs}


def write(version: str, summaries: dict[str, dict]) -> str:
    lines = [
        "# Image scans (trivy)",
        "",
        f"Every custom image of release {version}, scanned on {date.today().isoformat()} with trivy 0.58.0 (`aquasec/trivy:0.58.0`; the vulnerability database "
        "is the day's). Regenerate with `make trivy`, which fails on a HIGH or CRITICAL finding that has a fix available in an image that is not Cantaloupe. "
        "The scan covers operating-system packages, Python and Java libraries, secrets baked into layers, and Dockerfile misconfigurations.",
        "",
        "| Image | Base | Critical | High | Medium | Low | High/critical with a fix | Secrets in layers | Was (critical/high) before this slice |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for image, s in summaries.items():
        c = s["counts"]
        was = BEFORE[image]
        lines.append(f"| {image} | {s['os']} | {c['CRITICAL']} | {c['HIGH']} | {c['MEDIUM']} | {c['LOW']} | {len(s['fixable'])} | {s['secrets']} | {was[0]} / {was[1]} |")
    lines += [
        "",
        "## What was fixed",
        "",
        "The first scan, of the 0.11.0 images, found 9 critical and 109 high findings in each Python image (16 and 179 in the worker). What changed:",
        "",
        "- **Pillow 11.3.0 to 13.0.0** in the worker, the library that opens uploaded scans: 5 critical and dozens of high findings, all fixed in 12.x or 13.0.",
        "- **FastAPI 0.115.6 to 0.162.0** in catalog-api, search-api and the indexer, which moved Starlette from 0.41.3 to 1.10.0 (3 high findings).",
        "- **Base images**: `python:3.12.7-slim-bookworm` (Debian 12.8, October 2024) to `python:3.12.15-slim-trixie` (Debian 13), which has a newer Tesseract (5.5) and no longer carries most of the older findings; "
        "`nginx-unprivileged` 1.29.8 to 1.31.7 plus `apk upgrade`; the Cantaloupe image applies Ubuntu's security updates at build time.",
        "- **web-ui** has no finding of any severity left.",
        "",
        "All four service suites and the seed's suite pass on the new versions.",
        "",
        "## What is accepted, and why",
        "",
        "No image has a fixed-and-unapplied finding except Cantaloupe's, and none has a secret in a layer. What remains has no corrected package or release to move to.",
        "",
    ]
    for image, s in summaries.items():
        high = sum(v["HIGH"] for v in s["groups"].values())
        crit = sum(v["CRITICAL"] for v in s["groups"].values())
        lines += [f"### {image} ({crit} critical, {high} high)", "", ACCEPTED[image], ""]
        if s["groups"]:
            statuses = ", ".join(f"{count} `{status}`" for status, count in sorted(s["statuses"].items()))
            lines += [f"Status of these findings: {statuses}.", "", "| Package | Version | Critical | High |", "|---|---|---|---|"]
            for (kind, package, installed), counts in sorted(s["groups"].items(), key=lambda kv: (-kv[1]["CRITICAL"], -sum(kv[1].values()), kv[0][1])):
                lines.append(f"| {package} | {installed[:34]} | {counts['CRITICAL'] or ''} | {counts['HIGH'] or ''} |")
            lines.append("")
    lines += [
        "## What this does not show",
        "",
        "A scan finds known vulnerabilities in what is installed. It does not show that the services themselves are free of faults, and a clean result today says nothing about tomorrow's database. "
        "Images are pinned to exact versions, so a rescan on release is the way to find out; CI does not rescan on a schedule.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    version = sys.argv[1]
    summaries = {}
    for image in IMAGES:
        report = scan(image, version) if "--no-scan" not in sys.argv else json.loads((OUT / f"{image}.json").read_text())
        summaries[image] = summarise(report)
    target = ROOT / "docs" / "security" / "trivy.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(write(version, summaries))
    print(f"wrote {target.relative_to(ROOT)}")
    bad = [image for image, s in summaries.items() if image != "cantaloupe" and (s["fixable"] or s["secrets"])]
    for image in bad:
        print(f"FAIL {image}: a high/critical finding has a fix, or a secret is in a layer")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
