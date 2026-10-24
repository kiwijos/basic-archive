#!/usr/bin/env bash
# Runs every self-built service at three replicas and puts real traffic through them: the smoke test, ten scans read
# by the workers in parallel, and a hammering of image tiles. Passes if every replica stays ready without a restart,
# and prints the peak memory so it can be compared with what Docker Desktop has.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

SERVICES=(catalog-api search-api transcribe-worker cantaloupe web-ui indexer)
HPAS=(catalog-api search-api transcribe-worker cantaloupe)
mem_file=$(mktemp); saved=$(mktemp); sampler=""
restore() {
  [ -n "$sampler" ] && kill "$sampler" 2>/dev/null || true
  while read -r name min max; do
    kubectl -n "$NAMESPACE" patch hpa "$name" --type merge -p "{\"spec\":{\"minReplicas\":$min,\"maxReplicas\":$max}}" >/dev/null 2>&1 || true
  done < "$saved"
  rm -f "$auth_header" "$mem_file" "$saved"
}
trap restore EXIT

# The autoscalers would take replicas back down, so while this runs their floor is three.
for h in "${HPAS[@]}"; do
  read -r min max <<< "$(kubectl -n "$NAMESPACE" get hpa "$h" -o jsonpath='{.spec.minReplicas} {.spec.maxReplicas}')"
  echo "$h $min $max" >> "$saved"
  kubectl -n "$NAMESPACE" patch hpa "$h" --type merge -p "{\"spec\":{\"minReplicas\":3,\"maxReplicas\":$((max > 3 ? max : 3))}}" >/dev/null
done

for _ in $(seq 1 60); do
  ready=true
  for s in "${SERVICES[@]}"; do
    [ "$(kubectl -n "$NAMESPACE" get deploy "$s" -o jsonpath='{.status.readyReplicas}')" -ge 3 ] 2>/dev/null || ready=false
  done
  $ready && break
  sleep 5
done
$ready || fail "not every service reached three ready replicas"
kubectl -n "$NAMESPACE" get deploy "${SERVICES[@]}" -o custom-columns=SERVICE:.metadata.name,READY:.status.readyReplicas,DESIRED:.spec.replicas
kubectl -n "$NAMESPACE" top pods --no-headers >/dev/null 2>&1 || sleep 30 # metrics need a moment after the pods start

restarts() { kubectl -n "$NAMESPACE" get pods -o json | jq -r '[.items[] | select(.status.phase == "Running") | .status.containerStatuses[].restartCount] | add'; }
before=$(restarts)
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)

mib() { awk '{v=$1; if (v ~ /Gi$/) {sub(/Gi/,"",v); v*=1024} else if (v ~ /Mi$/) {sub(/Mi/,"",v)} else if (v ~ /Ki$/) {sub(/Ki/,"",v); v/=1024} print v+0}'; }
( while true; do
    pods=$(kubectl -n "$NAMESPACE" top pods --no-headers 2>/dev/null | awk '{print $3}' | mib | paste -sd+ - | bc 2>/dev/null || echo 0)
    node=$(kubectl top nodes --no-headers 2>/dev/null | awk '{print $4}' | mib)
    echo "${pods:-0} ${node:-0}" >> "$mem_file"
    sleep 5
  done ) &
sampler=$!

echo "--- smoke"; "$SCRIPTS_DIR/smoke.sh" | tail -1 | cut -c1-80
echo "--- ocr-parallel"; "$SCRIPTS_DIR/ocr-parallel.sh" | tail -1
echo "--- iiif-limits"; "$SCRIPTS_DIR/iiif-limits.sh" | tail -1
sleep 10

kill "$sampler" 2>/dev/null || true; sampler=""
after=$(restarts)
[ "$after" = "$before" ] || fail "containers restarted during the run ($before -> $after)"
notready=$(kubectl -n "$NAMESPACE" get pods -o json | jq '[.items[] | select(.status.phase == "Running" and .metadata.deletionTimestamp == null) | select(any(.status.containerStatuses[]; .ready | not))] | length')
[ "$notready" = 0 ] || fail "$notready pod(s) are not ready"
oom=$(kubectl -n "$NAMESPACE" get pods -o json | jq '[.items[].status.containerStatuses[]?.lastState.terminated.reason? | select(. == "OOMKilled")] | length')
[ "$oom" = 0 ] || fail "$oom container(s) were killed for running out of memory"
crashes=0
for s in "${SERVICES[@]}"; do
  n=$(kubectl -n "$NAMESPACE" logs -l "app=$s" --since-time="$started" --tail=-1 --max-log-requests=10 2>/dev/null | grep -c "Traceback" || true)
  crashes=$((crashes + n))
done
[ "$crashes" = 0 ] || fail "$crashes unhandled exception(s) in the service logs during the run"

total=$(awk -v t="$(docker info --format '{{.MemTotal}}')" 'BEGIN{printf "%d", t/1048576}')
peak_pods=$(sort -n "$mem_file" | tail -1 | awk '{print $1}'); peak_node=$(awk '{print $2}' "$mem_file" | sort -n | tail -1)
echo "Peak memory while every service ran three replicas under load:"
printf '  pods in %s (sum of working sets)  %6d MiB\n' "$NAMESPACE" "${peak_pods%.*}"
printf '  the whole node (all namespaces)       %6d MiB of %d MiB given to Docker (%d%%)\n' "${peak_node%.*}" "$total" $((${peak_node%.*} * 100 / total))
echo "OK: three replicas of every service, no restarts, nothing unready, no out-of-memory kills, no unhandled exceptions"
