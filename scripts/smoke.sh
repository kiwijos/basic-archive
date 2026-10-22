#!/usr/bin/env bash
# End-to-end check through the Ingress: create a Ship as Staff and read it back.
# Each slice extends this script, and a slice is accepted when it passes.
set -euo pipefail

BASE_URL=${BASE_URL:-http://localhost}
NAMESPACE=ship-archive

fail() { echo "SMOKE FAILED: $*" >&2; exit 1; }

first_pair=$(kubectl -n "$NAMESPACE" get secret catalog-api-secrets \
  -o jsonpath='{.data.STAFF_TOKENS}' | base64 -d | cut -d, -f1)
staff_name=${first_pair%%=*}
token=${first_pair#*=}

status=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/catalog/ships" \
  -H 'Content-Type: application/json' -d '{"name":"Unauthorised"}')
[ "$status" = 401 ] || fail "creating a Ship without a token returned $status, expected 401"

name="Smoke $(date +%s)"
created=$(curl -sf -X POST "$BASE_URL/api/catalog/ships" \
  -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  -d "{\"name\":\"$name\"}") || fail "creating a Ship through the Ingress failed"
id=$(echo "$created" | jq -r .id)

read_back=$(curl -sf "$BASE_URL/api/catalog/ships/$id" -H "Authorization: Bearer $token") \
  || fail "reading the Ship back failed"
[ "$(echo "$read_back" | jq -r .name)" = "$name" ] || fail "name did not round-trip: $read_back"
[ "$(echo "$read_back" | jq -r .created_by)" = "$staff_name" ] || fail "author not recorded: $read_back"

echo "SMOKE OK: created and read back Ship $id as $staff_name"
