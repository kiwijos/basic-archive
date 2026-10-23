#!/usr/bin/env bash
# Two failure scenarios, on the real cluster:
#   A. RabbitMQ is restarted while a job is waiting: the queue and the job survive.
#   B. catalog-api is killed between a write and its publish, with the broker down: no event is lost,
#      the outbox is relayed by the replacement once the broker is back.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

restore() {
  rm -f "$auth_header"
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
