"""Prepares a fresh Garage node for the archive, and does nothing on a node that is already prepared.

Garage's image has no shell, so this talks to its admin API. It applies the cluster layout,
creates the buckets, imports the access keys given in the environment (so their values come
from Kubernetes Secrets, not from Garage), and sets who may read or write which bucket.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ADMIN_URL = os.environ["GARAGE_ADMIN_URL"].rstrip("/")
ADMIN_TOKEN = os.environ["GARAGE_ADMIN_TOKEN"]
CAPACITY_BYTES = int(os.environ.get("GARAGE_CAPACITY_BYTES", 4 * 1024**3))

BUCKETS = ["masters", "derivatives"]

# Each key, and what it may do. A key gets exactly these rights: anything else is taken away.
KEYS = {
    "catalog-api": {
        "id": os.environ["CATALOG_API_S3_ACCESS_KEY_ID"],
        "secret": os.environ["CATALOG_API_S3_SECRET_ACCESS_KEY"],
        "grants": {"masters": {"read": True, "write": True}},
    },
    "cantaloupe": {
        "id": os.environ["CANTALOUPE_S3_ACCESS_KEY_ID"],
        "secret": os.environ["CANTALOUPE_S3_SECRET_ACCESS_KEY"],
        "grants": {"masters": {"read": True}},
    },
}


def call(method: str, path: str, body: dict | None = None, query: dict | None = None):
    url = f"{ADMIN_URL}{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read() or "null")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")


def must(status: int, payload, what: str):
    if status != 200:
        sys.exit(f"{what} failed with status {status}: {payload}")
    return payload


def wait_for_garage() -> None:
    for _ in range(60):
        try:
            if call("GET", "/v2/GetClusterStatus")[0] == 200:
                return
        except OSError:
            pass
        time.sleep(2)
    sys.exit("Garage did not become reachable")


def apply_layout() -> None:
    node = must(*call("GET", "/v2/GetClusterStatus"), "reading cluster status")["nodes"][0]["id"]
    layout = must(*call("GET", "/v2/GetClusterLayout"), "reading the layout")
    if layout["roles"]:
        print("layout already applied")
        return
    role = {"id": node, "zone": "dc1", "capacity": CAPACITY_BYTES, "tags": []}
    must(*call("POST", "/v2/UpdateClusterLayout", {"roles": [role]}), "staging the layout")
    must(*call("POST", "/v2/ApplyClusterLayout", {"version": layout["version"] + 1}), "applying the layout")
    print("layout applied")


def ensure_bucket(name: str) -> str:
    status, payload = call("GET", "/v2/GetBucketInfo", query={"globalAlias": name})
    if status == 200:
        return payload["id"]
    if status != 404:
        sys.exit(f"looking up bucket {name} failed with status {status}: {payload}")
    print(f"creating bucket {name}")
    return must(*call("POST", "/v2/CreateBucket", {"globalAlias": name}), f"creating bucket {name}")["id"]


def ensure_key(name: str, key: dict) -> None:
    status, payload = call("GET", "/v2/GetKeyInfo", query={"id": key["id"]})
    if status == 200:
        return
    if status != 404:
        sys.exit(f"looking up key {name} failed with status {status}: {payload}")
    print(f"importing key {name}")
    body = {"accessKeyId": key["id"], "secretAccessKey": key["secret"], "name": name}
    must(*call("POST", "/v2/ImportKey", body), f"importing key {name}")


def set_permissions(bucket_id: str, key_id: str, wanted: dict) -> None:
    rights = ("read", "write", "owner")
    grant = {right: bool(wanted.get(right)) for right in rights}
    revoke = {right: not grant[right] for right in rights}
    target = {"bucketId": bucket_id, "accessKeyId": key_id}
    if any(grant.values()):
        must(*call("POST", "/v2/AllowBucketKey", {**target, "permissions": grant}), "granting access")
    must(*call("POST", "/v2/DenyBucketKey", {**target, "permissions": revoke}), "revoking access")


def main() -> None:
    wait_for_garage()
    apply_layout()
    bucket_ids = {name: ensure_bucket(name) for name in BUCKETS}
    for name, key in KEYS.items():
        ensure_key(name, key)
        for bucket, bucket_id in bucket_ids.items():
            set_permissions(bucket_id, key["id"], key["grants"].get(bucket, {}))
    print("garage is ready")


if __name__ == "__main__":
    main()
