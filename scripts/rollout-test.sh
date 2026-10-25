#!/usr/bin/env bash
# Rolls each service in turn while requests go through the Ingress, and counts any that fail. The four services
# behind the Ingress are probed directly; the worker and the indexer are not, so for them work is submitted during
# the rollout and must all come out the other side, exactly once.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

stop_file=$(mktemp -u); ids_file=$(mktemp); probe_out=$(mktemp); probe_pid=""
# An interrupted run must not leave the probe sending requests for ever.
trap '[ -z "$probe_pid" ] || kill "$probe_pid" 2>/dev/null; rm -f "$auth_header" "$stop_file" "$ids_file" "$probe_out"' EXIT

image=$(api GET "/documents?source_system=seed" | jq -r '.[0].images[0].id // empty')
[ -n "$image" ] || image=$(upload_scan "rollout$(date +%s)")
[ -n "$image" ] || fail "no image to ask the image server about"

roll() { # roll DEPLOYMENT: restart it and wait until the new pods are ready
  kubectl -n "$NAMESPACE" rollout restart "deployment/$1" >/dev/null
  kubectl -n "$NAMESPACE" rollout status "deployment/$1" --timeout=300s >/dev/null
}

probe_during_roll() { # probe_during_roll DEPLOYMENT URL RATE [HEADER_FILE]
  local service=$1 url=$2 rate=$3 header=${4:-} result status=0
  rm -f "$stop_file"
  python3 "$SCRIPTS_DIR/probe.py" "$url" "$rate" "$stop_file" $header > "$probe_out" &
  local probe=$!; probe_pid=$probe
  sleep 3
  roll "$service"
  sleep 5 # the last old pod may still be going away
  touch "$stop_file"
  wait "$probe" || status=$?
  probe_pid=""
  result=$(cat "$probe_out")
  printf '  %-18s %s\n' "$service" "$result"
  return $status
}

failures=0
echo "Rolling each service while requests go through the Ingress:"
probe_during_roll web-ui "$BASE_URL/" 10 || failures=$((failures + 1))
probe_during_roll catalog-api "$BASE_URL/api/catalog/ships?source_system=seed" 10 "$auth_header" || failures=$((failures + 1))
# search-api answers 429 above 120 requests a minute from one address and replica. Three a second is 180 a minute over
# at least two replicas, so about 90 each: under the limit, but not by much, so do not raise it.
probe_during_roll search-api "$BASE_URL/api/search/subjects?q=nordstjarnan" 3 || failures=$((failures + 1))
probe_during_roll cantaloupe "$BASE_URL/iiif/3/$image/info.json" 10 || failures=$((failures + 1))
[ "$failures" -eq 0 ] || fail "$failures service(s) dropped requests while being rolled"

echo "Work submitted during a rollout is not lost:"
# The worker: six pages uploaded just before it is rolled must each be read once.
: > "$ids_file"
run=$(date +%s)
for n in 1 2 3 4 5 6; do ( upload_scan "roll-$run-$n" >> "$ids_file" ) & done
wait
roll transcribe-worker
for id in $(cat "$ids_file"); do
  wait_for_status "$id" ocr_done 240 || fail "Image $id was not read after the worker was rolled"
  [ "$(api GET "/images/$id/transcriptions" | jq length)" = 1 ] || fail "Image $id was not read exactly once"
done
echo "  transcribe-worker  6 pages uploaded, all read exactly once"

# The indexer: ships created while it is rolled must all become searchable.
: > "$ids_file"
kubectl -n "$NAMESPACE" rollout restart deployment/indexer >/dev/null
for n in 1 2 3 4 5 6; do
  name=$(LC_ALL=C tr -dc 'a-z' < /dev/urandom | head -c 12 || true)
  id=$(api POST /ships "{\"name\":\"Rull$name\",\"ship_type\":\"barque\"}" | jq -r .id)
  [ -n "$id" ] && [ "$id" != null ] || fail "could not create a ship during the indexer rollout"
  echo "$id Rull$name" >> "$ids_file"
  sleep 3
done
kubectl -n "$NAMESPACE" rollout status deployment/indexer --timeout=300s >/dev/null
while read -r id name; do
  found=false
  for _ in $(seq 1 60); do
    if curl -sfG "$BASE_URL/api/search/subjects" --data-urlencode "q=$name" --data-urlencode "_=$RANDOM" | jq -e --arg id "$id" 'any(.hits[]; .id == $id)' >/dev/null; then found=true; break; fi
    sleep 1
  done
  $found || fail "ship $name was created during the indexer rollout and never became searchable"
done < "$ids_file"
echo "  indexer            6 ships created during the rollout, all searchable"
echo "OK: no request failed while any service was rolled, and no work was lost"
