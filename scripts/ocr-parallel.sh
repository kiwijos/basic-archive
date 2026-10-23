#!/usr/bin/env bash
# Ten Images uploaded at once with three workers: all are read, in parallel, each exactly once.
# Scales the worker up for the run and back to one replica afterwards.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

REPLICAS=3
COUNT=10

kubectl -n "$NAMESPACE" scale deployment/transcribe-worker --replicas=$REPLICAS >/dev/null
trap 'kubectl -n "$NAMESPACE" scale deployment/transcribe-worker --replicas=1 >/dev/null' EXIT
kubectl -n "$NAMESPACE" rollout status deployment/transcribe-worker --timeout=180s >/dev/null
echo "$REPLICAS workers ready; uploading $COUNT pages at once"

run=$(date +%s)
ids_file=$(mktemp)
for n in $(seq 1 $COUNT); do
  ( upload_scan "$run-$n" >> "$ids_file" ) &
done
wait
uploaded=$(wc -l < "$ids_file" | tr -d ' ')
[ "$uploaded" -eq $COUNT ] || fail "only $uploaded of $COUNT uploads succeeded"

started=$SECONDS
for id in $(cat "$ids_file"); do
  wait_for_status "$id" ocr_done 180 || fail "Image $id never reached ocr_done"
done
echo "all $COUNT Images reached ocr_done after $((SECONDS - started)) s"

for id in $(cat "$ids_file"); do
  count=$(api GET "/images/$id/transcriptions" | jq length)
  [ "$count" = 1 ] || fail "Image $id has $count Machine transcriptions, expected exactly 1"
done
echo "each Image has exactly one Machine transcription"

# Which worker read which Image, from their logs.
busy=0
for pod in $(kubectl -n "$NAMESPACE" get pods -l app=transcribe-worker -o name); do
  log=$(kubectl -n "$NAMESPACE" logs "$pod" 2>/dev/null)
  handled=0
  for id in $(cat "$ids_file"); do
    if grep -q "Image $id read" <<< "$log"; then handled=$((handled + 1)); fi
  done
  total=$((${total:-0} + handled))
  echo "  $pod read $handled Images"
  if [ "$handled" -gt 0 ]; then busy=$((busy + 1)); fi
done
rm -f "$ids_file"
[ "$total" -eq $COUNT ] || fail "the workers' logs account for $total of $COUNT Images"
[ "$busy" -ge 2 ] || fail "only $busy worker(s) did any work, so nothing ran in parallel"
echo "OK: $COUNT Images read by $busy workers in parallel, each exactly once"
