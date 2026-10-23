#!/usr/bin/env bash
# Checks what protects the image decoder, through the real Ingress: tiles carry cache headers, and a
# client that hammers them is limited with 429 and then recovers. Kept apart from smoke because the limit
# is per client address, so hammering would starve any other script run at the same time.
set -euo pipefail

. "$(dirname "$0")/lib.sh"
trap 'rm -f "$auth_header"' EXIT

image=$(upload_scan "limits$(date +%s)") || fail "upload failed"
tile="$BASE_URL/iiif/3/$image/full/!256,256/0/default.jpg"
curl -sf -o /dev/null "$tile" || fail "the tile is not served at all"

headers=$(curl -sI "$tile" | tr -d '\r')
echo "$headers" | grep -iq '^cache-control: .*public' || fail "tiles are not marked public, so shared caches may not keep them"
echo "$headers" | grep -iq '^cache-control: .*max-age=[1-9]' || fail "tiles have no cache lifetime"
echo "tiles are cacheable: $(echo "$headers" | grep -i '^cache-control')"

python3 - "$tile" <<'PY'
import collections, concurrent.futures, sys, time, urllib.error, urllib.request

url = sys.argv[1]


def fetch(_):
    try:
        return urllib.request.urlopen(url, timeout=20).status
    except urllib.error.HTTPError as error:
        return error.code
    except OSError:
        return 0


started = time.time()
with concurrent.futures.ThreadPoolExecutor(64) as pool:
    codes = collections.Counter(pool.map(fetch, range(1500)))
took = time.time() - started
print(f"1500 requests in {took:.1f} s: {dict(sorted(codes.items()))}")
if codes.get(429, 0) == 0:
    sys.exit("FAILED: nothing was limited, so a client could keep the decoder busy")
if codes.get(200, 0) == 0:
    sys.exit("FAILED: everything was refused, the limit lets nobody through")
others = {code for code in codes if code not in (200, 429)}
if others:
    sys.exit(f"FAILED: unexpected answers {others}")
time.sleep(6)
after = urllib.request.urlopen(url, timeout=20).status
if after != 200:
    sys.exit(f"FAILED: the client was not let back in after a pause ({after})")
print("after a pause the same client is served again")
PY
echo "OK: tiles are cacheable, hammering is limited with 429, and a normal client is served"
