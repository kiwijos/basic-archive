#!/usr/bin/env bash
# Four failure scenarios, on the real cluster:
#   A. RabbitMQ is restarted while a job is waiting: the queue and the job survive.
#   B. catalog-api is killed between a write and its publish, with the broker down: no event is lost,
#      the outbox is relayed by the replacement once the broker is back.
#   C. Meilisearch's pod is deleted: its indexes and registered keys come back from the volume.
#   D. Wikidata is unreachable: staff get a clear message quickly, and editing and search carry on.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

# After a rollout the old pod may still be shutting down and can answer a request, so wait until only the
# new one is left before judging what the service does.
settled() { # settled DEPLOYMENT: wait for the rollout, then for any terminating pod of it to be gone
  kubectl -n "$NAMESPACE" rollout status "deployment/$1" --timeout=180s >/dev/null
  local deadline=$((SECONDS + 90))
  # With a single replica the Ingress needs a moment to follow the new pod, so wait until it has answered
  # five times in a row. (A 401 to an unauthenticated /me is catalog-api itself answering; a gateway error
  # would be a 502.)
  local good=0
  while [ "$good" -lt 5 ]; do
    if [ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/api/catalog/me")" = 401 ]; then good=$((good + 1)); else good=0; fi
    [ "$SECONDS" -lt "$deadline" ] || fail "$1 does not answer steadily through the Ingress after its rollout"
    sleep 0.5
  done
  while [ "$(kubectl -n "$NAMESPACE" get pods -l "app=$1" -o json | jq '[.items[] | select(.metadata.deletionTimestamp != null)] | length')" != 0 ]; do
    [ "$SECONDS" -lt "$deadline" ] || fail "an old $1 pod never finished shutting down"
    sleep 1
  done
}

# A staff call whose answer is catalog-api's own. Right after a rollout the Ingress can still answer with its
# own plain-text "Bad Gateway" for a moment, which says nothing about the service, so that is tried again.
# Prints the body, then the status on a last line.
staff_call() { # staff_call METHOD PATH
  local deadline=$((SECONDS + 45)) out body
  while :; do
    out=$(curl -s -w '\n%{http_code}' -X "$1" -H @"$auth_header" "$BASE_URL/api/catalog$2")
    body=$(printf '%s' "$out" | sed '$d')
    if [ -z "$body" ] || printf '%s' "$body" | jq -e . >/dev/null 2>&1; then printf '%s' "$out"; return; fi
    [ "$SECONDS" -lt "$deadline" ] || { printf '%s' "$out"; return; }
    sleep 1
  done
}

restore() {
  rm -f "$auth_header"
  # Back to the real Wikidata whatever happened (a no-op when it was never changed).
  kubectl -n "$NAMESPACE" set env deployment/catalog-api WIKIDATA_API_URL- >/dev/null 2>&1 || true
  kubectl -n "$NAMESPACE" scale statefulset/rabbitmq --replicas=1 >/dev/null 2>&1 || true
  kubectl -n "$NAMESPACE" scale deployment/transcribe-worker --replicas=1 >/dev/null 2>&1 || true
}
trap restore EXIT

run=$(date +%s)

echo "== A. a waiting job survives a RabbitMQ restart"
kubectl -n "$NAMESPACE" scale deployment/transcribe-worker --replicas=0 >/dev/null
kubectl -n "$NAMESPACE" wait --for=delete pod -l app=transcribe-worker --timeout=120s >/dev/null 2>&1 || true
image=$(upload_scan "$run-a") || fail "upload failed"
deadline=$((SECONDS + 30))
until [ "$(queue_messages ocr.requested)" -ge 1 ]; do
  [ "$SECONDS" -lt "$deadline" ] || fail "the job never reached the ocr.requested queue"
  sleep 1
done
echo "job is waiting in the queue ($(queue_messages ocr.requested) message)"
kubectl -n "$NAMESPACE" delete pod rabbitmq-0 >/dev/null
kubectl -n "$NAMESPACE" rollout status statefulset/rabbitmq --timeout=240s >/dev/null
deadline=$((SECONDS + 60))
until [ "$(queue_messages ocr.requested 2>/dev/null || echo 0)" -ge 1 ]; do
  [ "$SECONDS" -lt "$deadline" ] || fail "the queued job did not survive the broker restart"
  sleep 2
done
echo "after the restart the queue still holds the job"
kubectl -n "$NAMESPACE" scale deployment/transcribe-worker --replicas=1 >/dev/null
wait_for_status "$image" ocr_done 180 || fail "the job was not processed once a worker returned"
echo "the job survived the restart and was processed"

echo "== B. catalog-api is killed between a write and its publish"
kubectl -n "$NAMESPACE" scale statefulset/rabbitmq --replicas=0 >/dev/null
kubectl -n "$NAMESPACE" wait --for=delete pod/rabbitmq-0 --timeout=120s >/dev/null
image=$(upload_scan "$run-b") || fail "upload failed while the broker was down"
waiting=$(unpublished_events)
[ "$waiting" -ge 2 ] || fail "expected events waiting in the outbox, found $waiting"
echo "upload accepted with the broker down; $waiting events wait in the outbox"
kubectl -n "$NAMESPACE" delete pod -l app=catalog-api >/dev/null
kubectl -n "$NAMESPACE" rollout status deployment/catalog-api --timeout=180s >/dev/null
echo "catalog-api killed and replaced; bringing the broker back"
kubectl -n "$NAMESPACE" scale statefulset/rabbitmq --replicas=1 >/dev/null
kubectl -n "$NAMESPACE" rollout status statefulset/rabbitmq --timeout=300s >/dev/null
wait_for_status "$image" ocr_done 240 || fail "the Image was never read: an event was lost"
deadline=$((SECONDS + 30))
until [ "$(unpublished_events)" = 0 ]; do
  [ "$SECONDS" -lt "$deadline" ] || fail "events are still unpublished: $(unpublished_events)"
  sleep 1
done
echo "OK: the outbox was relayed after the kill, nothing was lost"

echo "== C. Meilisearch keeps its data when its pod is deleted"
total() { curl -sfG "$BASE_URL/api/search/documents" --data-urlencode "n=$SECONDS$RANDOM" | jq -r .total; }
before=$(total)
[ "$before" -ge 1 ] || fail "nothing is indexed, so there is nothing to lose (run make smoke first)"
kubectl -n "$NAMESPACE" delete pod meilisearch-0 >/dev/null
kubectl -n "$NAMESPACE" rollout status statefulset/meilisearch --timeout=180s >/dev/null
deadline=$((SECONDS + 60))
until [ "$(total 2>/dev/null || echo -1)" = "$before" ]; do
  [ "$SECONDS" -lt "$deadline" ] || fail "after the restart search holds $(total 2>/dev/null || echo nothing) documents, expected $before"
  sleep 1
done
echo "OK: $before documents are still searchable after the pod was deleted, with the same keys"

echo "== D. Wikidata is unreachable"
ship=$(api POST /ships "{\"name\":\"Outage $run\"}" | jq -r .id) || fail "creating a ship failed"
# Nothing listens on this address inside the pod, which is what an outage looks like from catalog-api.
kubectl -n "$NAMESPACE" set env deployment/catalog-api WIKIDATA_API_URL=http://127.0.0.1:9/w/api.php >/dev/null
settled catalog-api
started=$SECONDS
reply=$(staff_call GET "/ships/$ship/wikidata-candidates")
code=$(echo "$reply" | tail -1)
detail=$(echo "$reply" | sed '$d' | jq -r .detail)
[ "$code" = 502 ] || fail "with Wikidata down, asking for candidates returned $code, expected 502 ($detail)"
echo "$detail" | grep -qi "not available right now" || fail "the message does not say Wikidata is unavailable: $detail"
[ $((SECONDS - started)) -le 15 ] || fail "the failure took $((SECONDS - started)) seconds, it should be bounded"
echo "staff are told within $((SECONDS - started)) s: $detail"
[ "$(staff_call PUT "/ships/$ship/wikidata/Q219821" | tail -1)" = 502 ] || fail "choosing during the outage did not fail cleanly"
[ "$(api GET "/ships/$ship" | jq '.external_refs | length')" = 0 ] || fail "a failed choice stored something"
api PUT "/ships/$ship" '{"ship_type":"barque"}' >/dev/null || fail "the ship could not be edited during the outage"
api POST "/subjects/$ship/names" '{"name":"Outage renamed","date":{"date_from":"1950-01-01"}}' >/dev/null || fail "the ship could not be renamed during the outage"
curl -sf "$BASE_URL/api/search/documents?q=anything&n=$RANDOM" >/dev/null || fail "search stopped working during the outage"
kubectl -n "$NAMESPACE" set env deployment/catalog-api WIKIDATA_API_URL- >/dev/null
settled catalog-api
after=$(staff_call GET "/ships/$ship")
[ "$(echo "$after" | tail -1)" = 200 ] || fail "the ship cannot be read after the outage: $(echo "$after" | tr '\n' ' ' | cut -c1-200)"
echo "$after" | sed '$d' | jq -e '.ship_type == "barque"' >/dev/null || fail "the edits made during the outage were lost"
api DELETE "/ships/$ship" >/dev/null
echo "OK: Wikidata being down gave a clear message within a bound, and nothing else stopped"
