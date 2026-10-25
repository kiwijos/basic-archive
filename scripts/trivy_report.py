"""Scans every custom image with trivy and writes the results to docs/security/trivy.md.

python scripts/trivy_report.py VERSION [--no-scan]

The explanations of what is accepted live here, next to the code that produces the numbers, so a rescan cannot
quietly replace a reasoned acceptance with a bare count. A HIGH or CRITICAL finding with a fix available makes the script exit 1, except
the Cantaloupe findings already recorded in docs/security/cantaloupe-accepted.txt: a new one there fails too.
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
CANTALOUPE_ACCEPTED = ROOT / "docs" / "security" / "cantaloupe-accepted.txt"

# Images the stack runs that are not ours: scanned and recorded, and a fixable HIGH or CRITICAL finding in them fails
# the run, because for these the fix is a newer tag in a manifest. name -> (image, where it is used)
OTHERS = {
    "init Jobs": ("python:3.12.15-slim-trixie", "garage-init and meilisearch-init, one of which holds the Meilisearch master key"),
    "postgres": ("postgres:16.15-alpine", "the database, and the migration Job's readiness wait"),
    "rabbitmq": ("rabbitmq:4.3.7-alpine", "the broker"),
    "garage": ("dxflrs/garage:v2.4.1", "object storage"),
    "meilisearch": ("getmeili/meilisearch:v1.55.0", "the search index"),
    "busybox": ("busybox:1.37.0", "Garage's one-time ownership fix"),
}
# Accepted because the newest upstream release is already in use and the fix is in the distribution's packages.
OTHERS_ACCEPTED = {
    "postgres": "Every remaining finding (1 critical, 25 high, all `stdlib` v1.24.6) is the Go standard library compiled into "
    "`gosu`, the helper the image's entrypoint uses to drop from root to the postgres user. This deployment starts as the "
    "postgres user (uid 70) from the first instruction, so `gosu` is never run; PostgreSQL itself and the Alpine packages have "
    "no fixable finding. A newer tag that rebuilds `gosu` removes them.",
    "meilisearch": "v1.55.0 is the newest Meilisearch release. Its ten HIGH findings are Alpine packages with a fix in a newer Alpine "
    "that this release has not been rebuilt on, so there is nothing to change here short of building our own Meilisearch image. "
    "Meilisearch is reachable only from search-api (search key) and the indexer (index key) and runs non-root on a read-only "
    "filesystem; its master key is held by nothing else.",
}

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
    "Unlike every other finding here, these are fixable: each has a corrected library version, but the libraries "
    "(Jackson, Netty, Jetty, Tika, Bouncy Castle, plexus-utils) are bundled inside `cantaloupe-5.0.7.jar`. 5.0.7 (March 2025) "
    "is the newest Cantaloupe release, and replacing libraries inside its jar would give an unsupported, untested build, so "
    "the remedy is a Cantaloupe release, and until then this is an accepted risk, not a resolved one. It is accepted on "
    "containment and on what is reachable, and the CVEs were not analysed one by one, so **the HTTP-handling ones (Jetty, "
    "Netty) should be treated as reachable by anyone who can reach the Ingress**: Traefik forwards only `/iiif/3`, but it "
    "does not make Jetty's request parsing safe. What limits the damage: only the IIIF Image API 3 is served (the admin and "
    "management API are off and no delegate script is enabled); its only source is the fixed `masters` bucket in Garage, "
    "read with a read-only key, so a caller cannot make it fetch a URL of their choosing; a NetworkPolicy lets it talk "
    "only to Garage; and it runs non-root on a read-only filesystem with no capabilities, no Kubernetes API token and no "
    "credential that can change data. The exact findings accepted are listed in `docs/security/cantaloupe-accepted.txt`, "
    "and `make trivy` fails if a new fixable one appears. The Bouncy Castle and Tika findings concern TLS and document "
    "parsing, which this configuration does not use (HTTPS is off in Cantaloupe, and no document format is read), but that "
    "was not verified at runtime."
)
ACCEPTED = {
    "catalog-api": OS_REASON, "indexer": OS_REASON, "search-api": OS_REASON,
    "transcribe-worker": OS_REASON + " " + WORKER_REASON, "cantaloupe": JAR_REASON,
    "web-ui": "Nothing to accept.",
}



def scan(name: str, reference: str) -> dict:
    OUT.mkdir(exist_ok=True)
    result = OUT / f"{name.replace(' ', '_')}.json"
    subprocess.run(
        ["docker", "run", "--rm", "-v", "/var/run/docker.sock:/var/run/docker.sock", "-v", "trivy-cache:/root/.cache/", "-v", f"{OUT}:/out", TRIVY,
         "image", "--quiet", "--format", "json", "--output", f"/out/{result.name}", "--scanners", "vuln,secret,misconfig", reference],
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
    system = report["Metadata"].get("OS")  # an image built from scratch has none
    return {"os": f"{system['Family']} {system['Name']}" if system else "no OS packages", "counts": counts, "fixable": fixable,
            "groups": groups, "statuses": statuses, "secrets": secrets, "misconfigs": misconfigs}


def write(version: str, summaries: dict[str, dict], others: dict[str, dict]) -> str:
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
        "No image has a fixed-and-unapplied finding except Cantaloupe's, and none has a secret in a layer. Apart from Cantaloupe's, what remains is a finding Debian has chosen not to fix or has not yet fixed, so there is no corrected package to move to.",
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
        "## The other images the stack runs",
        "",
        "Not ours, so not part of the acceptance, but they run in the same namespace, so they are scanned too and a fixable HIGH or CRITICAL finding in any of them fails `make trivy`. "
        "Postgres 16.4, which the first scan found with 7 critical and 82 high findings, all fixable, was moved to 16.15 (the same major version, so the data directory is unchanged), "
        "and the init Jobs' Python base from `python:3.12.7-slim-bookworm` to `3.12.15-slim-trixie`.",
        "",
        "| Used for | Image | Base | Critical | High | High/critical with a fix |",
        "|---|---|---|---|---|---|",
    ]
    for name, s in others.items():
        image, use = OTHERS[name]
        lines.append(f"| {use} | `{image}` | {s['os']} | {s['counts']['CRITICAL']} | {s['counts']['HIGH']} | {len(s['fixable'])} |")
    lines.append("")
    for name, reason in OTHERS_ACCEPTED.items():
        lines += [f"**{name}.** {reason}", ""]
    lines += [
        "## What this does not show",
        "",
        "A scan finds known vulnerabilities in what is installed. It does not show that the services themselves are free of faults, and a clean result today says nothing about tomorrow's database. "
        "Images are pinned to exact versions, so a rescan on release is the way to find out; CI does not rescan on a schedule.",
        "",
    ]
    return "\n".join(lines)


def reports(references: dict[str, str], skip_scan: bool) -> dict[str, dict]:
    out = {}
    for name, reference in references.items():
        result = OUT / f"{name.replace(' ', '_')}.json"
        out[name] = summarise(json.loads(result.read_text()) if skip_scan else scan(name, reference))
    return out


def main() -> int:
    version = sys.argv[1]
    skip = "--no-scan" in sys.argv
    summaries = reports({image: f"{REPOSITORY}-{image}:{version}" for image in IMAGES}, skip)
    others = reports({name: image for name, (image, _) in OTHERS.items()}, skip)
    target = ROOT / "docs" / "security" / "trivy.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(write(version, summaries, others))
    print(f"wrote {target.relative_to(ROOT)}")

    accepted = set(CANTALOUPE_ACCEPTED.read_text().split()) if CANTALOUPE_ACCEPTED.exists() else set()
    fixable_now = {f["VulnerabilityID"] for f in summaries["cantaloupe"]["fixable"]}
    if not skip and not accepted:
        CANTALOUPE_ACCEPTED.write_text("\n".join(sorted(fixable_now)) + "\n")  # first run: record what is accepted today
        accepted = fixable_now
    problems = [f"FAIL {image}: a high/critical finding has a fix, or a secret is in a layer" for image, s in summaries.items() if image != "cantaloupe" and (s["fixable"] or s["secrets"])]
    problems += [f"FAIL {name}: a high/critical finding has a fix" for name, s in others.items() if s["fixable"] and name not in OTHERS_ACCEPTED]
    problems += [f"FAIL cantaloupe: new fixable finding {cve} is not in {CANTALOUPE_ACCEPTED.name}" for cve in sorted(fixable_now - accepted)]
    print("\n".join(problems) or f"OK: nothing new; {len(accepted)} Cantaloupe findings accepted")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
