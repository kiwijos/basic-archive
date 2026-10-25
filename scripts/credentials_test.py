"""Proves that each service's credentials open only what that service needs, using the credentials as they are in the pods.

Each check runs inside the pod that holds the credential, reading it from that pod's own environment, so nothing here
sees a secret except to compare it. The one exception is S3: Cantaloupe's image has no Python, so its read-only key is
tried from the catalog-api pod, which may reach Garage, and the key is passed on standard input, never on a command line.
"""

import base64
import json
import subprocess
import sys

NAMESPACE = "ship-archive"
failures: list[str] = []


def run_in(target: str, script: str, stdin: str = "") -> str:
    """Run a Python script inside a pod; the script arrives on stdin, with any input after a separator line."""
    payload = script + "\n#--input--\n" + stdin if stdin else script
    boot = "import sys;src=sys.stdin.read();code,_,data=src.partition('\\n#--input--\\n');sys.stdin=__import__('io').StringIO(data);exec(compile(code,'check','exec'))"
    done = subprocess.run(["kubectl", "-n", NAMESPACE, "exec", "-i", target, "--", "python", "-c", boot], input=payload, capture_output=True, text=True, timeout=120)
    return (done.stdout + done.stderr).strip()


def check(name: str, got: str, expected: str) -> None:
    ok = got == expected
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f": expected {expected!r}, got {got!r}"))
    if not ok:
        failures.append(name)


def check_answers(who: str, out: str, wants: dict[str, str]) -> None:
    """Compare a script's "what: answer" lines with what each action was expected to give."""
    got = dict(line.rsplit(": ", 1) for line in out.splitlines() if ": " in line)
    for action, want in wants.items():
        check(f"{who}: {action}", got.get(action, f"no answer ({out[-120:]})"), want)


def secret(name: str, key: str) -> str:
    out = subprocess.run(["kubectl", "-n", NAMESPACE, "get", "secret", name, "-o", f"jsonpath={{.data.{key}}}"], capture_output=True, text=True, check=True).stdout
    return base64.b64decode(out).decode()


# ---- RabbitMQ: each login can do only its own part of the work ----------------------------------------------------

PIKA = '''
import os, pika
def attempt(what):
    try:
        what(); return "allowed"
    except (pika.exceptions.ChannelClosedByBroker, pika.exceptions.ProbableAccessDeniedError, pika.exceptions.ConnectionClosedByBroker) as e:
        return "refused" if "ACCESS_REFUSED" in str(e) else "error: " + str(e)[:80]
def fresh():
    c = pika.BlockingConnection(pika.URLParameters(os.environ["RABBITMQ_URL"])); return c, c.channel()
def publish_events():
    c, ch = fresh(); ch.confirm_delivery(); ch.basic_publish("archive.events", "credentials.test", b"{}"); c.close()
def publish_direct():
    c, ch = fresh(); ch.confirm_delivery(); ch.basic_publish("", "ocr.requested", b"{}"); c.close()
def consume(q):
    def go():
        c, ch = fresh(); ch.basic_consume(q, lambda *a: None); c.close()
    return go
print("publish to the events exchange:", attempt(publish_events))
print("publish straight to the OCR queue:", attempt(publish_direct))
print("read record.changed:", attempt(consume("record.changed")))
print("read ocr.requested:", attempt(consume("ocr.requested")))
'''

AIO = '''
import asyncio, os, aio_pika
async def attempt(coro):
    try:
        await coro; return "allowed"
    except aio_pika.exceptions.ChannelClosed as e:
        return "refused" if "ACCESS_REFUSED" in str(e) else "error: " + str(e)[:80]
    except Exception as e:
        return "error: " + type(e).__name__ + str(e)[:80]
async def open_channel():
    c = await aio_pika.connect(os.environ["RABBITMQ_URL"]); return c, await c.channel()
async def publish(exchange_name, key):
    c, ch = await open_channel()
    try:
        ex = ch.default_exchange if exchange_name == "" else await ch.get_exchange(exchange_name, ensure=False)
        await ex.publish(aio_pika.Message(b"{}"), key, timeout=5)
        await ch.get_queue("record.changed", ensure=False)
    finally:
        await c.close()
async def consume(q):
    c, ch = await open_channel()
    try:
        queue = await ch.get_queue(q, ensure=False)
        tag = await queue.consume(lambda m: None)
        await asyncio.sleep(1)
        await queue.cancel(tag)
    finally:
        await c.close()
async def main():
    print("publish to the events exchange:", await attempt(publish("archive.events", "credentials.test")))
    print("publish straight to the OCR queue:", await attempt(publish("", "ocr.requested")))
    print("read record.changed:", await attempt(consume("record.changed")))
    print("read ocr.requested:", await attempt(consume("ocr.requested")))
asyncio.run(main())
'''

EXPECT_BROKER = {
    "catalog-api": (PIKA, {"publish to the events exchange": "allowed", "publish straight to the OCR queue": "refused", "read record.changed": "refused", "read ocr.requested": "refused"}),
    "transcribe-worker": (AIO, {"publish to the events exchange": "allowed", "publish straight to the OCR queue": "refused", "read record.changed": "refused", "read ocr.requested": "allowed"}),
    "indexer": (AIO, {"publish to the events exchange": "refused", "publish straight to the OCR queue": "refused", "read record.changed": "allowed", "read ocr.requested": "refused"}),
}


def broker() -> None:
    print("RabbitMQ: each service's own login, tried against what it should and should not do")
    for service, (script, expected) in EXPECT_BROKER.items():
        check_answers(service, run_in(f"deploy/{service}", script), expected)


# ---- Meilisearch: a search-only key and an index-only key, never the master key ----------------------------------

MEILI = '''
import json, os, urllib.error, urllib.request
def call(method, path, body=None):
    request = urllib.request.Request(os.environ["MEILI_URL"] + path, method=method, data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + os.environ["MEILI_KEY"], "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as r: return r.status
    except urllib.error.HTTPError as e: return e.code
tests = json.loads(__import__("sys").stdin.read())
for name, (method, path, body) in tests.items():
    print(name + ":", call(method, path, body))
'''


def meili() -> None:
    print("Meilisearch: the search key searches and nothing else; the indexer's key writes indexes and holds no administrator rights")
    probes = {
        "search the documents index": ("POST", "/indexes/documents/search", {"q": ""}),
        "add a document": ("POST", "/indexes/documents/documents", [{"id": "credentials-test"}]),
        "list the keys": ("GET", "/keys", None),
        "create a key": ("POST", "/keys", {"actions": ["*"], "indexes": ["*"], "expiresAt": None}),
        "delete an index": ("DELETE", "/indexes/documents", None),
        "read the tasks": ("GET", "/tasks", None),
    }
    expected = {
        "search-api": {"search the documents index": "200", "add a document": "403", "list the keys": "403", "create a key": "403", "delete an index": "403", "read the tasks": "403"},
        "indexer": {"list the keys": "403", "create a key": "403", "delete an index": "403"},
    }
    for service, wants in expected.items():
        # Only what this key is expected to be refused (or, for search, allowed): a write the indexer's key is
        # permitted to make would put a stray document in the real index.
        check_answers(service, run_in(f"deploy/{service}", MEILI, json.dumps({name: probes[name] for name in wants})), wants)


def master_key_only_with_meilisearch() -> None:
    print("The Meilisearch master key is in exactly one pod's environment, Meilisearch's own")
    master = secret("meilisearch-secrets", "MEILI_MASTER_KEY")
    pods = subprocess.run(["kubectl", "-n", NAMESPACE, "get", "pods", "-o", "jsonpath={range .items[?(@.status.phase=='Running')]}{.metadata.name}{'\\n'}{end}"], capture_output=True, text=True, check=True).stdout.split()
    holders, unreadable = [], []
    for pod in pods:
        done = subprocess.run(["kubectl", "-n", NAMESPACE, "exec", pod, "--", "sh", "-c", "cat /proc/1/environ | tr '\\0' '\\n'"], capture_output=True, text=True, timeout=60)
        if done.returncode != 0:
            unreadable.append(pod)
        elif master in done.stdout:
            holders.append(pod)
    check("pods whose environment holds the master key", ",".join(holders), "meilisearch-0")
    print(f"       ({len(pods) - len(unreadable)} pods read; no shell in: {', '.join(unreadable) or 'none'})")
    others = subprocess.run(["kubectl", "-n", NAMESPACE, "get", "pods", "-o", "json"], capture_output=True, text=True, check=True).stdout
    check("pod specs that spell the master key out", str(master in others), "False")


# ---- S3: the read-only key reads and cannot write ----------------------------------------------------------------

S3 = '''
import json, sys, boto3
from botocore.config import Config
from botocore.exceptions import ClientError
creds = json.loads(sys.stdin.read())
s3 = boto3.client("s3", endpoint_url="http://garage:3900", region_name="garage", aws_access_key_id=creds["id"], aws_secret_access_key=creds["secret"],
                  config=Config(signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 1}))
def attempt(what):
    try:
        what(); return "allowed"
    except ClientError as e:
        return "refused" if e.response["Error"]["Code"] in ("AccessDenied", "403") else "error: " + e.response["Error"]["Code"]
print("read the masters bucket:", attempt(lambda: s3.list_objects_v2(Bucket="masters", MaxKeys=1)))
print("write to the masters bucket:", attempt(lambda: s3.put_object(Bucket="masters", Key="credentials-test", Body=b"x")))
print("delete from the masters bucket:", attempt(lambda: s3.delete_object(Bucket="masters", Key="credentials-test")))
'''


def s3() -> None:
    print("S3 (Garage): Cantaloupe's key reads the originals and cannot change them; catalog-api's key can")
    for secret_name, wants in (
        ("cantaloupe-s3", {"read the masters bucket": "allowed", "write to the masters bucket": "refused", "delete from the masters bucket": "refused"}),
        ("catalog-api-s3", {"read the masters bucket": "allowed", "write to the masters bucket": "allowed", "delete from the masters bucket": "allowed"}),
    ):
        key = json.dumps({"id": secret(secret_name, "S3_ACCESS_KEY_ID"), "secret": secret(secret_name, "S3_SECRET_ACCESS_KEY")})
        check_answers(secret_name.removesuffix("-s3"), run_in("deploy/catalog-api", S3, key), wants)


# ---- Catalog tokens: the worker's service token is not a staff token ----------------------------------------------

TOKEN = '''
import os, urllib.error, urllib.request
def status(path):
    request = urllib.request.Request(os.environ["CATALOG_API_URL"] + path, headers={"Authorization": "Bearer " + os.environ["CATALOG_API_TOKEN"]})
    try:
        with urllib.request.urlopen(request, timeout=10) as r: return r.status
    except urllib.error.HTTPError as e: return e.code
print("staff documents list:", status("/api/catalog/documents?source_system=seed"))
print("review queue:", status("/api/catalog/review-queue"))
'''


def tokens() -> None:
    print("Catalog tokens: the worker's service token cannot do what staff can")
    for service in ("transcribe-worker", "indexer"):
        check_answers(service, run_in(f"deploy/{service}", TOKEN), {"staff documents list": "401", "review queue": "401"})


def main() -> int:
    for step in (broker, meili, master_key_only_with_meilisearch, s3, tokens):
        step()
        print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("OK: every service's credentials do only what that service needs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
