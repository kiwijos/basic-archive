"""python -m archive_seed seed|check: load the demo data into a running archive, or check that it is there."""

import argparse
import logging
import sys
from pathlib import Path

import httpx

from archive_seed.check import Check
from archive_seed.loader import DEFAULT_CACHE, Report, SeedError, Seeder
from archive_seed.plates import PlateIntegrityError


def staff_client(base_url: str, token_file: Path) -> httpx.Client:
    # The token is read from a file the caller keeps private, never from the command line.
    token = token_file.read_text().strip()
    return httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {token}"}, timeout=120)


def seed(args) -> int:
    with staff_client(args.base_url, args.token_file) as api:
        seeder = Seeder(api, cache_dir=args.cache_dir, with_plates=not args.no_plates, ocr_timeout=args.ocr_timeout)
        try:
            report = seeder.seed()
        except (SeedError, PlateIntegrityError) as error:
            print(f"The seed stopped: {error}", file=sys.stderr)
            return 1
    summary(report)
    return 0


def summary(report: Report) -> None:
    print("Seed finished.")
    for what in sorted(set(report.created) | set(report.found)):
        print(f"  {what:<18} {report.created[what]:>3} made, {report.found[what]:>3} already there")
    for message in report.skipped:
        print(f"  SKIPPED {message}")
    print()
    print(report.table())


def check(args) -> int:
    with staff_client(args.base_url, args.token_file) as staff, httpx.Client(base_url=args.base_url, timeout=60) as public:
        run = Check(staff, public, index_wait=args.index_wait)
        findings = run.run()
        print("Demo check:")
        for finding in findings:
            print(finding)
        if run.pages:
            print()
            print(Report(pages=run.pages).table())
        return 1 if run.failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="archive_seed")
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--token-file", type=Path, required=True, help="a file holding a staff token")
    commands = parser.add_subparsers(dest="command", required=True)
    loading = commands.add_parser("seed", help="load the demo data; safe to run again")
    loading.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    loading.add_argument("--no-plates", action="store_true", help="leave out the drawings fetched from Wikimedia Commons")
    loading.add_argument("--ocr-timeout", type=float, default=300.0, help="seconds to wait for the OCR")
    loading.set_defaults(run=seed)
    checking = commands.add_parser("check", help="read-only: is what the demo needs there?")
    checking.add_argument("--index-wait", type=float, default=90.0, help="seconds to wait for the search index")
    checking.set_defaults(run=check)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
