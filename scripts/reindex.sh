#!/usr/bin/env bash
# Rebuilds the whole search index from the catalog and waits for it to finish.
# The reindex token is read inside the indexer pod from its own environment, so it never appears on a
# command line here.
set -euo pipefail

NAMESPACE=${NAMESPACE:-ship-archive}

# Several indexer replicas run but only one applies changes (the queue allows one active consumer), and the lock
# that keeps a reindex from racing those changes lives in that process. So the reindex goes to the active replica,
# which RabbitMQ lists under the pod's name.
pod=$(kubectl -n "$NAMESPACE" exec rabbitmq-0 -- rabbitmqctl -q list_consumers queue_name consumer_tag active \
  | awk '$1 == "record.changed" && $3 == "true" {print $2}')
[ "$(echo "$pod" | wc -w | tr -d ' ')" = 1 ] || { echo "Expected one active indexer, found: '${pod:-none}'" >&2; exit 1; }
echo "Reindexing through the active indexer, $pod"

kubectl -n "$NAMESPACE" exec -i "pod/$pod" -- python - <<'PY'
import json, os, sys, time, urllib.error, urllib.request

headers = {"Authorization": "Bearer " + os.environ["REINDEX_TOKEN"]}


def call(method):
    request = urllib.request.Request("http://127.0.0.1:" + os.environ.get("HTTP_PORT", "8080") + "/reindex", method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        sys.exit(f"reindex refused: {error.code} {error.read().decode()}")


call("POST")
deadline = time.time() + 600
while time.time() < deadline:
    state = call("GET")
    if state["state"] in ("done", "failed"):
        print(json.dumps(state))
        sys.exit(0 if state["state"] == "done" else 1)
    time.sleep(1)
sys.exit("the reindex did not finish in ten minutes")
PY
