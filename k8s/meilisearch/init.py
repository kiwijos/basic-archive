"""Registers the search keys in Meilisearch. Safe to run again at any time.

A key's value is derived from the master key and the key's uid, so the Secrets made by
scripts/create-secrets.sh already hold the right values; this only makes Meilisearch accept them.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = os.environ["MEILI_URL"]
MASTER = os.environ["MEILI_MASTER_KEY"]
SPECS = json.load(open("/init/keys.json"))


def call(method, path, body=None):
    request = urllib.request.Request(
        URL + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {MASTER}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, None


def wait_for_meilisearch():
    for _ in range(90):
        try:
            if urllib.request.urlopen(URL + "/health", timeout=3).status == 200:
                return
        except OSError:
            pass
        time.sleep(2)
    sys.exit("Meilisearch did not become healthy")


def same(existing, spec):
    return sorted(existing["actions"]) == sorted(spec["actions"]) and sorted(existing["indexes"]) == sorted(spec["indexes"])


wait_for_meilisearch()
for spec in SPECS:
    status, existing = call("GET", f"/keys/{spec['uid']}")
    if status == 200 and same(existing, spec):
        print(f"key {spec['name']}: already registered")
        continue
    if status == 200:
        call("DELETE", f"/keys/{spec['uid']}")  # its rights changed; the value stays the same
    status, _ = call("POST", "/keys", spec)
    if status != 201:
        sys.exit(f"could not create key {spec['name']}: {status}")
    print(f"key {spec['name']}: registered")
