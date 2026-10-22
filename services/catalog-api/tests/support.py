"""Helpers shared by the upload tests."""

API = "/api/catalog"
PNG = b"\x89PNG\r\n\x1a\n" + b"pretend this is a scanned letter"


def upload(client, staff, content=PNG, filename="scan.png", **fields):
    data = {"title": "Letter from the yard", **fields}
    files = {"file": (filename, content, "application/octet-stream")}
    return client.post(f"{API}/documents", data=data, files=files, headers=staff)


def stored_objects(s3):
    return s3.list_objects_v2(Bucket="masters").get("KeyCount", 0)
