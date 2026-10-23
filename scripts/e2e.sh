#!/usr/bin/env bash
# Runs the browser test against the deployed cluster. The staff token is passed to Playwright in its
# environment, never on a command line.
set -euo pipefail

. "$(dirname "$0")/lib.sh"
scan=$(mktemp)
trap 'rm -f "$auth_header" "$scan"' EXIT

run=$(date +%s)
uv run --quiet --no-project --with pillow==11.3.0 python "$SCRIPTS_DIR/make_scan.py" "$scan" "$run" >/dev/null

cd "$SCRIPTS_DIR/../services/web-ui"
[ -d node_modules ] || npm ci
npx --no-install playwright install chromium

STAFF_TOKEN=$token SCAN_FILE=$scan RUN_ID=$run ARCHIVE_URL=$BASE_URL npx --no-install playwright test
