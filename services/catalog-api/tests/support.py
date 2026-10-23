"""Helpers shared by the upload tests."""

import json
import time

API = "/api/catalog"
PNG = b"\x89PNG\r\n\x1a\n" + b"pretend this is a scanned letter"


def upload(client, staff, content=PNG, filename="scan.png", **fields):
    data = {"title": "Letter from the yard", **fields}
    files = {"file": (filename, content, "application/octet-stream")}
    return client.post(f"{API}/documents", data=data, files=files, headers=staff)


def stored_objects(s3):
    return s3.list_objects_v2(Bucket="masters").get("KeyCount", 0)


def receive(channel, queue, expected, timeout=10.0, settle=0.0):
    """Take messages off a queue until `expected` have arrived, then keep watching for `settle`
    seconds to catch any extras. Returns (decoded body, properties) pairs."""
    received = []
    deadline = time.monotonic() + timeout
    settled_until = None
    while True:
        method, properties, body = channel.basic_get(queue, auto_ack=True)
        if method is not None:
            received.append((json.loads(body), properties))
            continue
        now = time.monotonic()
        if len(received) >= expected:
            settled_until = settled_until or now + settle
            if now >= settled_until:
                return received
        elif now >= deadline:
            return received
        time.sleep(0.05)
