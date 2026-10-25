#!/usr/bin/env bash
# Deletes the Postgres, Garage, Meilisearch and RabbitMQ pods one at a time and proves each comes back with its
# data, read through the same API a visitor or staff member uses. Each check prints a line to record.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

content=$(mktemp)
trap 'rm -f "$auth_header" "$content"; kubectl -n "$NAMESPACE" scale deployment/transcribe-worker --replicas=1 >/dev/null 2>&1 || true' EXIT

restart_pod() { # restart_pod POD: delete it, then wait for its StatefulSet to bring it back ready
  local pvc_before pvc_after
  pvc_before=$(kubectl -n "$NAMESPACE" get pvc "data-$1" -o jsonpath='{.metadata.uid}')
  kubectl -n "$NAMESPACE" delete pod "$1" --wait=true >/dev/null
  until kubectl -n "$NAMESPACE" get pod "$1" >/dev/null 2>&1; do sleep 1; done
  kubectl -n "$NAMESPACE" wait --for=condition=Ready "pod/$1" --timeout=240s >/dev/null
  pvc_after=$(kubectl -n "$NAMESPACE" get pvc "data-$1" -o jsonpath='{.metadata.uid}')
  [ "$pvc_before" = "$pvc_after" ] || fail "$1 came back on a different volume"
}

search_finds() { # search_finds PATH ID SECONDS [curl args]: the public search answers with this id
  local path=$1 id=$2 seconds=$3; shift 3
  local deadline=$((SECONDS + seconds))
  while [ "$SECONDS" -lt "$deadline" ]; do
    curl -sfG "$BASE_URL/api/search$path" --data-urlencode "_=$RANDOM$SECONDS" "$@" | jq -e --arg id "$id" 'any(.hits[]; .id == $id)' >/dev/null && return 0
    sleep 1
  done
  return 1
}

run=$(LC_ALL=C tr -dc 'a-z' < /dev/urandom | head -c 12 || true)

# Postgres: a Ship created before the pod is deleted is still there afterwards.
ship=$(api POST /ships "{\"name\":\"Pers$run\",\"ship_type\":\"barque\"}" | jq -r .id)
[ -n "$ship" ] && [ "$ship" != null ] || fail "could not create the Ship"
restart_pod postgres-0
[ "$(api GET "/ships/$ship" | jq -r .name)" = "Pers$run" ] || fail "the Ship was lost when the Postgres pod was deleted"
echo "postgres-0     deleted and back: Ship Pers$run read back by id"

# Garage: the stored scan comes back byte for byte.
image=$(upload_scan "pers$run") || fail "upload failed"
sha=$(api GET "/images/$image" | jq -r .sha256)
restart_pod garage-0
# A single instance is unreachable for a moment after it reports ready, until its Service points at it again, and
# catalog-api answers 502 meanwhile. How long that lasted is part of the record.
waited_from=$SECONDS; code=000
while [ "$((SECONDS - waited_from))" -le 30 ]; do
  code=$(curl -s -o "$content" -w '%{http_code}' "$BASE_URL/api/catalog/images/$image/content" -H @"$auth_header")
  [ "$code" = 200 ] && break
  sleep 1
done
[ "$code" = 200 ] || fail "the scan could not be downloaded within 30 s of Garage coming back: HTTP $code $(head -c 200 "$content")"
unavailable=$((SECONDS - waited_from))
[ "$(shasum -a 256 "$content" | cut -d' ' -f1)" = "$sha" ] || fail "the scan changed while Garage was restarted"
echo "garage-0       deleted and back: scan $image downloaded, SHA-256 unchanged (unreachable for ${unavailable} s after ready)"

# Meilisearch: the index answers again without a reindex.
search_finds /subjects "$ship" 60 --data-urlencode "q=Pers$run" || fail "the Ship was not in the search index before the test"
restart_pod meilisearch-0
search_finds /subjects "$ship" 60 --data-urlencode "q=Pers$run" || fail "the search index lost the Ship when its pod was deleted"
echo "meilisearch-0  deleted and back: the Ship is still found by search, with no reindex"

# RabbitMQ: a job waiting for a reader outlives the broker's pod, and is read once a worker is back.
kubectl -n "$NAMESPACE" scale deployment/transcribe-worker --replicas=0 >/dev/null
kubectl -n "$NAMESPACE" wait --for=delete pod -l app=transcribe-worker --timeout=180s >/dev/null 2>&1 || true
waiting=$(upload_scan "queue$run") || fail "upload failed"
for _ in $(seq 1 30); do [ "$(queue_messages ocr.requested)" -ge 1 ] && break; sleep 1; done
before=$(queue_messages ocr.requested)
[ "$before" -ge 1 ] || fail "the OCR job never reached the queue"
restart_pod rabbitmq-0
after=$(queue_messages ocr.requested)
[ "$after" -ge 1 ] || fail "the queued OCR job was lost when the RabbitMQ pod was deleted"
kubectl -n "$NAMESPACE" scale deployment/transcribe-worker --replicas=1 >/dev/null
wait_for_status "$waiting" ocr_done 240 || fail "the queued scan was never read after the broker came back"
echo "rabbitmq-0     deleted and back: $before queued OCR job(s) before, $after after, then read"
echo "OK: no data was lost when any of the four stateful pods was deleted"
