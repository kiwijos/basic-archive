#!/usr/bin/env bash
# Loads the archive until at least one HorizontalPodAutoscaler adds replicas, then waits for it to settle back.
# Tiles of the largest seeded drawing are requested from inside the cluster (past the Ingress's rate limit, which
# is there to stop exactly this), and a burst of scans keeps the OCR workers busy. Needs `make demo` data for the
# drawing; without it the largest scan available is used.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

LOAD_SECONDS=${LOAD_SECONDS:-150}
SETTLE_SECONDS=${SETTLE_SECONDS:-420}
HPAS=(catalog-api search-api transcribe-worker cantaloupe)
trap 'rm -f "$auth_header" "$ids_file"; kubectl -n "$NAMESPACE" delete pod hpa-load --ignore-not-found --wait=false >/dev/null 2>&1' EXIT
ids_file=$(mktemp)

replicas() { kubectl -n "$NAMESPACE" get hpa "$1" -o jsonpath='{.status.currentReplicas}'; }
cpu() { kubectl -n "$NAMESPACE" get hpa "$1" -o jsonpath='{.status.currentMetrics[0].resource.current.averageUtilization}'; }

# The biggest picture: the widest image of the seeded plates, else any seeded scan, else a fresh upload.
image=$(api GET "/documents?source_system=wikimedia-commons" | jq -r '.[0].images[0].id // empty')
[ -n "$image" ] || image=$(api GET "/documents?source_system=seed" | jq -r '.[0].images[0].id // empty')
[ -n "$image" ] || image=$(upload_scan "hpa$(date +%s)")
width=$(curl -sf "$BASE_URL/iiif/3/$image/info.json" | jq -r .width)
echo "Load: random tiles of image $image (${width} px wide) from inside the cluster for ${LOAD_SECONDS} s, plus 20 scans to read"

# Indexed arrays, not associative ones: macOS ships bash 3.2.
start=(); peak=()
for i in "${!HPAS[@]}"; do start[i]=$(replicas "${HPAS[i]}"); peak[i]=${start[i]}; done

kubectl -n "$NAMESPACE" delete pod hpa-load --ignore-not-found --wait=true >/dev/null
kubectl -n "$NAMESPACE" run hpa-load --restart=Never --image="kiwijos/ship-archive-search-api:$(kubectl -n "$NAMESPACE" get deploy search-api -o jsonpath='{.spec.template.spec.containers[0].image}' | cut -d: -f2)" \
  --image-pull-policy=IfNotPresent --env="IMAGE=$image" --env="WIDTH=$width" --env="SECONDS_TO_RUN=$LOAD_SECONDS" --command -- python -c '
import os, random, threading, time, urllib.request
image, width, until = os.environ["IMAGE"], int(os.environ["WIDTH"]), time.time() + int(os.environ["SECONDS_TO_RUN"])
def fetch():
    while time.time() < until:
        size = random.choice((1024, 2048, 3072))
        x, y = random.randrange(0, max(1, width - size)), random.randrange(0, max(1, width // 2 - size))
        try:
            urllib.request.urlopen(f"http://cantaloupe:8182/iiif/3/{image}/{x},{y},{size},{size}/!512,/0/default.jpg", timeout=30).read()
        except Exception:
            time.sleep(0.2)
threads = [threading.Thread(target=fetch) for _ in range(24)]
[t.start() for t in threads]
[t.join() for t in threads]
' >/dev/null

run=$(date +%s)
for n in $(seq 1 20); do ( upload_scan "hpa-$run-$n" >> "$ids_file" ) & done
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

scaled=0
echo "Replicas, at the start and at the peak:"
for i in "${!HPAS[@]}"; do
  printf '  %-18s %s -> %s\n' "${HPAS[i]}" "${start[i]}" "${peak[i]}"
  if [ "${peak[i]}" -gt "${start[i]}" ]; then scaled=$((scaled + 1)); fi
done
[ "$scaled" -ge 1 ] || fail "no autoscaler added a replica under load"
echo "$scaled autoscaler(s) scaled up"

for id in $(cat "$ids_file"); do wait_for_status "$id" ocr_done 300 || fail "Image $id was never read"; done
echo "all 20 scans were read"

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
