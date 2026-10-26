"""Checks the written deliverables against what the ticket and the repository say they must contain.

    python3 scripts/check_docs.py

It does not judge the prose. It checks the things that rot or get forgotten: every link resolves (files and headings),
every ADR is linked from the document it belongs to, every component the manifests run is in the architecture table
(and every third-party one says why it exists), the named patterns and sections are present, every `make` command in
the demo script exists, and the demo script has a step for each acceptance criterion of the spec and the assignment.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DELIVERABLES = ["docs/architecture.md", "docs/security.md", "docs/discussion.md", "docs/demo.md"]

# Which ADRs each document must link, because it is where the decision is explained.
ADRS_LINKED_FROM = {
    "docs/architecture.md": [
        "0001-append-only-transcriptions-with-source", "0003-transactional-outbox", "0004-subjects-with-dated-names-and-relations",
        "0005-derived-search-index-and-per-service-keys", "0006-cantaloupe-serves-originals-by-image-id",
        "0007-wikidata-matches-are-chosen-by-a-person-and-fetched-by-the-server", "0009-the-indexer-runs-as-hot-standbys",
    ],
    "docs/security.md": ["0002-no-person-or-crew-data", "0005-derived-search-index-and-per-service-keys", "0010-security-deny-by-default-with-proofs"],
    "docs/discussion.md": ["0003-transactional-outbox", "0008-the-demo-is-seeded-through-the-public-api-with-source-keys", "0009-the-indexer-runs-as-hot-standbys"],
}

SELF_CREATED = ["catalog-api", "search-api", "indexer", "transcribe-worker", "web-ui"]
THIRD_PARTY = ["Postgres", "RabbitMQ", "Meilisearch", "Garage", "Cantaloupe", "Traefik", "metrics-server"]
PATTERNS = ["microservices", "CQRS", "competing consumers", "event-driven", "eventual consistency", "stateless", "API gateway"]

# Each is a heading the demo script must contain, so that it can be followed to every criterion.
SPEC_CRITERIA = {
    "A1": "one command", "A2": "ten uploads", "A3": "verified correction", "A4": "misspelled", "A5": "blueprint zooms",
    "A6": "delete the Postgres pod", "A7": "reindex", "A8": "three replicas", "A9": "blocked",
}
ASSIGNMENT_CRITERIA = {
    "R1": "two self-created services", "R2": "scale independently", "R3": "database survives restarts",
    "R4": "Docker Hub", "R5": "external REST API", "R6": "reachable from outside",
}

problems: list[str] = []


def fail(message: str) -> None:
    problems.append(message)


def slug(heading: str) -> str:
    text = re.sub(r"[`*_]", "", heading.strip().lower())
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s", "-", text)


def headings(path: Path) -> set[str]:
    found, in_code = set(), False
    for line in path.read_text().splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code and re.match(r"#{1,6} ", line):
            found.add(slug(line.lstrip("# ")))
    return found


def read(name: str) -> str:
    path = ROOT / name
    return path.read_text() if path.exists() else ""


def markdown_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "GLOSSARY.md", ROOT / "seed" / "SOURCES.md"]
    files += sorted((ROOT / "docs").rglob("*.md"))
    return [f for f in files if f.exists()]


def check_links() -> None:
    for source in markdown_files():
        text = re.sub(r"```.*?```", "", source.read_text(), flags=re.S)
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if re.match(r"[a-z]+:", target) or target.startswith("#") and False:
                continue
            path_part, _, anchor = target.partition("#")
            resolved = source if not path_part else (source.parent / path_part).resolve()
            where = f"{source.relative_to(ROOT)} -> {target}"
            if not resolved.exists():
                fail(f"broken link: {where}")
            elif anchor and resolved.suffix == ".md" and anchor not in headings(resolved):
                fail(f"no such heading: {where}")


def check_deliverables_exist() -> None:
    for name in DELIVERABLES:
        if not (ROOT / name).exists():
            fail(f"missing document: {name}")


def check_adr_links() -> None:
    adrs = sorted(p.stem for p in (ROOT / "docs" / "adr").glob("*.md"))
    linked_anywhere = set()
    for name, wanted in ADRS_LINKED_FROM.items():
        text = read(name)
        for adr in wanted:
            if f"adr/{adr}.md" not in text:
                fail(f"{name} does not link ADR {adr}")
        linked_anywhere |= {adr for adr in adrs if f"adr/{adr}.md" in text}
    for adr in adrs:
        if adr not in linked_anywhere:
            fail(f"ADR {adr} is not linked from the architecture, security or discussion document")


def table_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if line.startswith("|") and not re.match(r"\|[\s:|-]+\|?$", line):
            rows.append([re.sub(r"[`*]", "", cell).strip() for cell in line.strip().strip("|").split("|")])
    return rows


def check_architecture() -> None:
    text = read("docs/architecture.md")
    if not text:
        return
    rows = table_rows(text)
    first_column = {row[0].lower(): row for row in rows if row}
    for name in SELF_CREATED + THIRD_PARTY:
        if name.lower() not in first_column:
            fail(f"architecture.md has no table row for {name}")
    for name in THIRD_PARTY:
        row = first_column.get(name.lower())
        if row and max(len(cell) for cell in row[1:]) < 40:
            fail(f"architecture.md says too little about why {name} exists")
    # Everything the manifests run must be in the table.
    running = set()
    for manifest in (ROOT / "k8s").glob("*.yaml"):
        running |= set(re.findall(r"kind: (?:Deployment|StatefulSet)\nmetadata:\n  name: (\S+)", manifest.read_text()))
    for name in sorted(running):
        if name.lower() not in first_column:
            fail(f"architecture.md has no table row for the workload {name}, which the manifests run")
    lowered = text.lower()
    for pattern in PATTERNS:
        if pattern.lower() not in lowered:
            fail(f"architecture.md does not name the pattern '{pattern}'")
    for heading in ("logical components", "diagram"):
        if heading not in lowered:
            fail(f"architecture.md has no '{heading}' section")
    if "```mermaid" not in text:
        fail("architecture.md has no diagram (a mermaid block)")


def check_security() -> None:
    text = read("docs/security.md")
    if not text:
        return
    lowered = text.lower()
    header = next((row for row in table_rows(text) if row and row[0].lower() == "threat"), None)
    if not header or "mitigation" not in " ".join(header).lower():
        fail("security.md has no threat table with a Mitigation column")
    for word in ("GDPR", "CC0", "OIDC", "per-replica", "single instance"):
        if word.lower() not in lowered:
            fail(f"security.md does not mention '{word}'")
    for heading in ("known limitations", "proposed"):
        if heading not in lowered:
            fail(f"security.md has no '{heading}' section")


def check_discussion() -> None:
    text = read("docs/discussion.md")
    if not text:
        return
    lowered = text.lower()
    for heading in ("benefits", "challenges", "too small", "pretend"):
        if heading not in lowered:
            fail(f"discussion.md has no '{heading}' section or mention")
    for word in ("Kraken", "eScriptorium", "local-path", "eventual consistency", "single-instance", "object storage", "operational complexity", "fault isolation"):
        if word.lower() not in lowered:
            fail(f"discussion.md does not mention '{word}'")


def make_targets() -> set[str]:
    return set(re.findall(r"^([a-z][a-z0-9-]*):", read("Makefile"), flags=re.M))


def check_demo() -> None:
    text = read("docs/demo.md")
    if not text:
        return
    for identifier, topic in {**SPEC_CRITERIA, **ASSIGNMENT_CRITERIA}.items():
        if not re.search(rf"^#+ {identifier}\b", text, flags=re.M):
            fail(f"demo.md has no step headed {identifier} ({topic})")
    targets = make_targets()
    for command in re.findall(r"^\s*make ([a-z][a-z0-9-]*)", text, flags=re.M):
        if command not in targets:
            fail(f"demo.md runs `make {command}`, which is not a Makefile target")
    for script in re.findall(r"\./scripts/([\w.-]+)", text):
        if not (ROOT / "scripts" / script).exists():
            fail(f"demo.md runs scripts/{script}, which does not exist")


def check_readme() -> None:
    text = read("README.md")
    lowered = text.lower()
    for heading in ("## prerequisites", "## quick start", "## documents"):
        if heading not in lowered:
            fail(f"README.md has no '{heading[3:]}' section")
    for name in DELIVERABLES:
        if name not in text:
            fail(f"README.md does not say where {name} is")
    quick = re.search(r"## Quick start(.*?)\n## ", text, flags=re.S | re.I)
    if not quick or "make demo" not in quick.group(1):
        fail("the README's quick start does not give the one command, `make demo`")


def main() -> int:
    check_deliverables_exist()
    check_links()
    check_adr_links()
    check_architecture()
    check_security()
    check_discussion()
    check_demo()
    check_readme()
    for problem in problems:
        print(f"FAIL {problem}")
    checked = len(markdown_files())
    print(f"{checked} markdown files checked, {len(problems)} problem(s)" if problems else f"OK: {checked} markdown files checked, every rule holds")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
