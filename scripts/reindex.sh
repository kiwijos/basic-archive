#!/usr/bin/env bash
# Rebuilds the whole search index from the catalog and waits for it to finish.
# The reindex token is read inside the indexer pod from its own environment, so it never appears on a
# command line here.
set -euo pipefail

NAMESPACE=${NAMESPACE:-ship-archive}

kubectl -n "$NAMESPACE" exec -i deploy/indexer -- python - <<'PY'
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
