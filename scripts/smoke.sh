#!/usr/bin/env bash
# End-to-end check through the Ingress, as Staff: create and read back a Ship, rename it,
# sell it, rebuild its hull, and check validation and delete.
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

api() { # api METHOD PATH [JSON]: call catalog-api as Staff, fail on any non-2xx answer
  local method=$1 path=$2 body=${3:-}
  if [ -n "$body" ]; then
    curl -sf -X "$method" "$BASE_URL/api/catalog$path" -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' -d "$body"
  else
    curl -sf -X "$method" "$BASE_URL/api/catalog$path" -H "Authorization: Bearer $token"
  fi
}

run=$(date +%s)
ship=$(api POST /ships "{\"name\":\"Vega $run\",\"launched\":{\"date_text\":\"ca 1890\",\"date_from\":\"1889-01-01\",\"date_to\":\"1891-12-31\"}}" | jq -r .id) \
  || fail "creating a Ship with an uncertain launch date failed"

# A ship renamed twice is still one ship, with its whole name history.
api POST "/subjects/$ship/names" '{"name":"Sofia","date":{"date_from":"1905-03-01"}}' >/dev/null || fail "first rename failed"
api POST "/subjects/$ship/names" '{"name":"Nordstjernan","date":{"date_from":"1921-06-01"}}' >/dev/null || fail "second rename failed"
[ "$(api GET "/ships/$ship" | jq -r .name)" = "Nordstjernan" ] || fail "current name is not the latest"
[ "$(api GET "/subjects/$ship/names" | jq 'length')" = 3 ] || fail "name history should hold three names"

# A ship sold once has an ordered owner history.
owner_a=$(api POST /organisations '{"name":"Rederi A"}' | jq -r .id)
owner_b=$(api POST /organisations '{"name":"Rederi B"}' | jq -r .id)
sale=$(api POST /relations "{\"from_subject_id\":\"$ship\",\"predicate\":\"owned_by\",\"to_subject_id\":\"$owner_a\",\"date\":{\"date_from\":\"1890-05-01\"}}" | jq -r .id)
api PUT "/relations/$sale" '{"date":{"date_from":"1890-05-01","date_to":"1923-04-01"}}' >/dev/null || fail "closing the first ownership failed"
api POST /relations "{\"from_subject_id\":\"$ship\",\"predicate\":\"owned_by\",\"to_subject_id\":\"$owner_b\",\"date\":{\"date_from\":\"1923-04-01\"}}" >/dev/null || fail "second ownership failed"
owners=$(api GET "/subjects/$ship/relations?predicate=owned_by" | jq -r '[.[].to_name] | join(",")')
[ "$owners" = "Rederi A,Rederi B" ] || fail "owner history is [$owners]"

# A rebuilt hull is a new ship linked to the old one.
rebuilt=$(api POST /ships "{\"name\":\"Rebuilt $run\"}" | jq -r .id)
api POST /relations "{\"from_subject_id\":\"$rebuilt\",\"predicate\":\"rebuilt_from\",\"to_subject_id\":\"$ship\"}" >/dev/null || fail "rebuilt-from failed"
[ "$(api GET "/subjects/$ship/relations?predicate=rebuilt_from" | jq 'length')" = 1 ] || fail "old hull does not show the rebuild"

# An inverted date range is refused, and a deleted ship disappears.
status=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/catalog/ships" \
  -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  -d '{"name":"Inverted","launched":{"date_from":"1891-01-01","date_to":"1889-01-01"}}')
[ "$status" = 422 ] || fail "an inverted date range returned $status, expected 422"
api DELETE "/ships/$rebuilt" >/dev/null || fail "deleting a Ship failed"
status=$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/api/catalog/ships/$rebuilt" -H "Authorization: Bearer $token")
[ "$status" = 404 ] || fail "a deleted Ship returned $status, expected 404"

echo "SMOKE OK: ship $id created and read back as $staff_name; renames, sale, rebuild, validation and delete verified"
