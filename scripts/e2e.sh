#!/usr/bin/env bash
# Runs the browser test against the deployed cluster. The staff token is passed to Playwright in its
# environment, never on a command line.
set -euo pipefail

. "$(dirname "$0")/lib.sh"
scan=$(mktemp); blueprint=$(mktemp); blueprint_two=$(mktemp)
trap 'rm -f "$auth_header" "$scan" "$blueprint" "$blueprint_two"' EXIT

run=$(date +%s)
uv run --quiet --no-project --with pillow==11.3.0 python "$SCRIPTS_DIR/make_scan.py" "$scan" "$run" >/dev/null

# A large drawing to zoom into, and a smaller second sheet so a Document can have two pages.
uv run --quiet --no-project --with pillow==11.3.0 python "$SCRIPTS_DIR/make_blueprint.py" "$blueprint" "$run" 9000 6000 >/dev/null
uv run --quiet --no-project --with pillow==11.3.0 python "$SCRIPTS_DIR/make_blueprint.py" "$blueprint_two" "$run-two" 3000 2000 >/dev/null

cd "$SCRIPTS_DIR/../services/web-ui"
[ -d node_modules ] || npm ci
npx --no-install playwright install chromium

STAFF_TOKEN=$token SCAN_FILE=$scan BLUEPRINT_FILE=$blueprint BLUEPRINT_FILE_2=$blueprint_two RUN_ID=$run ARCHIVE_URL=$BASE_URL npx --no-install playwright test
