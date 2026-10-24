#!/usr/bin/env bash
# Loads the demo data into the running archive, or checks that it is there: seed.sh [seed|check] [options].
# Safe to run again. The staff token goes to the seed in a private file, never on a command line.
set -euo pipefail

. "$(dirname "$0")/lib.sh"
token_file=$(mktemp)
trap 'rm -f "$auth_header" "$token_file"' EXIT
printf '%s' "$token" > "$token_file"

command=${1:-seed}
[ $# -gt 0 ] && shift
cd "$SCRIPTS_DIR/../seed"
uv run --quiet --no-dev python -m archive_seed --base-url "$BASE_URL" --token-file "$token_file" "$command" "$@"
