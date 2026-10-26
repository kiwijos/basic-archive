#!/usr/bin/env bash
# Loads the archive until at least one HorizontalPodAutoscaler adds replicas, then waits for it to settle back.
# Tiles of the largest seeded drawing are requested from inside the cluster, and a burst of scans keeps the OCR
# workers busy. Needs `make demo` data for the drawing; without it the largest page available is used.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

LOAD_SECONDS=${LOAD_SECONDS:-150}
SETTLE_SECONDS=${SETTLE_SECONDS:-420}
SCANS=${SCANS:-20}
HPAS=(catalog-api search-api transcribe-worker cantaloupe)
trap 'rm -f "$auth_header" "$ids_file"; stop_tile_load' EXIT
ids_file=$(mktemp)

replicas() { kubectl -n "$NAMESPACE" get hpa "$1" -o jsonpath='{.status.currentReplicas}'; }
cpu() { kubectl -n "$NAMESPACE" get hpa "$1" -o jsonpath='{.status.currentMetrics[0].resource.current.averageUtilization}'; }

# Start from rest: an autoscaler still settling from an earlier load would hide a scale-up, or invent one.
min_of() { kubectl -n "$NAMESPACE" get hpa "$1" -o jsonpath='{.spec.minReplicas}'; }
echo "Waiting for every autoscaler to be at its minimum before the load starts (up to ${SETTLE_SECONDS} s)"
rest_deadline=$((SECONDS + SETTLE_SECONDS))
while true; do
  resting=true
  for h in "${HPAS[@]}"; do [ "$(replicas "$h")" -le "$(min_of "$h")" ] || resting=false; done
  $resting && break
  [ "$SECONDS" -lt "$rest_deadline" ] || fail "the autoscalers did not come to rest within ${SETTLE_SECONDS} s"
  sleep 10
done

image=$(biggest_image)

# Indexed arrays, not associative ones: macOS ships bash 3.2.
start=(); peak=()
for i in "${!HPAS[@]}"; do start[i]=$(replicas "${HPAS[i]}"); peak[i]=${start[i]}; done

start_tile_load "$image" "$LOAD_SECONDS"
echo "plus $SCANS scans to read"

run=$(date +%s)
for n in $(seq 1 "$SCANS"); do ( upload_scan "hpa-$run-$n" >> "$ids_file" ) & done
wait

deadline=$((SECONDS + LOAD_SECONDS + 30))
while [ "$SECONDS" -lt "$deadline" ]; do
  line=""
  for i in "${!HPAS[@]}"; do
    now=$(replicas "${HPAS[i]}")
    if [ "${now:-0}" -gt "${peak[i]}" ]; then peak[i]=$now; fi
    line="$line ${HPAS[i]}=$now(cpu $(cpu "${HPAS[i]}")%)"
  done
  echo "  +$((SECONDS - (deadline - LOAD_SECONDS - 30)))s$line"
  sleep 10
done

# A load that was refused is no load at all: the pod says how many tiles it got answered.
kubectl -n "$NAMESPACE" wait --for=jsonpath='{.status.phase}'=Succeeded pod/tile-load --timeout=90s >/dev/null 2>&1 || true
answered=$(kubectl -n "$NAMESPACE" logs tile-load 2>/dev/null | sed -n 's/^tiles answered: \([0-9]*\),.*/\1/p')
echo "tiles answered during the load: ${answered:-unknown}"
[ "${answered:-0}" -ge 100 ] || fail "the tile load was refused or barely answered (${answered:-no report} tiles), so this run shows nothing about autoscaling"

scaled=0
echo "Replicas, at the start and at the peak:"
for i in "${!HPAS[@]}"; do
  printf '  %-18s %s -> %s\n' "${HPAS[i]}" "${start[i]}" "${peak[i]}"
  if [ "${peak[i]}" -gt "${start[i]}" ]; then scaled=$((scaled + 1)); fi
done
[ "$scaled" -ge 1 ] || fail "no autoscaler added a replica under load"
echo "$scaled autoscaler(s) scaled up"

for id in $(cat "$ids_file"); do wait_for_status "$id" ocr_done 300 || fail "Image $id was never read"; done
echo "all $SCANS scans were read"

echo "Waiting for the replicas to settle back (up to ${SETTLE_SECONDS} s)"
settle_deadline=$((SECONDS + SETTLE_SECONDS))
while [ "$SECONDS" -lt "$settle_deadline" ]; do
  settled=true
  for i in "${!HPAS[@]}"; do [ "$(replicas "${HPAS[i]}")" -le "${start[i]}" ] || settled=false; done
  $settled && break
  sleep 10
done
$settled || fail "the replicas did not settle back to where they started within ${SETTLE_SECONDS} s"
echo "OK: load made $scaled autoscaler(s) add replicas, and they settled back afterwards"
