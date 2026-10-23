#!/usr/bin/env bash
# End-to-end check through the Ingress, as Staff: create and read back a Ship, rename it,
# sell it, rebuild its hull, and check validation and delete.
# Each slice extends this script, and a slice is accepted when it passes.
set -euo pipefail

BASE_URL=${BASE_URL:-http://localhost}
NAMESPACE=ship-archive

fail() { echo "SMOKE FAILED: $*" >&2; exit 1; }

first_pair=$(kubectl -n "$NAMESPACE" get secret catalog-api-secrets \
  -o jsonpath='{.data.STAFF_TOKENS}' | base64 -d | cut -d, -f1)
staff_name=${first_pair%%=*}
token=${first_pair#*=}

status=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/catalog/ships" \
  -H 'Content-Type: application/json' -d '{"name":"Unauthorised"}')
[ "$status" = 401 ] || fail "creating a Ship without a token returned $status, expected 401"

name="Smoke $(date +%s)"
created=$(curl -sf -X POST "$BASE_URL/api/catalog/ships" \
  -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  -d "{\"name\":\"$name\"}") || fail "creating a Ship through the Ingress failed"
id=$(echo "$created" | jq -r .id)

read_back=$(curl -sf "$BASE_URL/api/catalog/ships/$id" -H "Authorization: Bearer $token") \
  || fail "reading the Ship back failed"
[ "$(echo "$read_back" | jq -r .name)" = "$name" ] || fail "name did not round-trip: $read_back"
[ "$(echo "$read_back" | jq -r .created_by)" = "$staff_name" ] || fail "author not recorded: $read_back"

api() { # api METHOD PATH [JSON]: call catalog-api as Staff, fail on any non-2xx answer
  local method=$1 path=$2 body=${3:-}
  if [ -n "$body" ]; then
    curl -sf -X "$method" "$BASE_URL/api/catalog$path" -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' -d "$body"
  else
    curl -sf -X "$method" "$BASE_URL/api/catalog$path" -H "Authorization: Bearer $token"
  fi
}

run=$(date +%s)
ship=$(api POST /ships "{\"name\":\"Vega $run\",\"launched\":{\"date_text\":\"ca 1890\",\"date_from\":\"1889-01-01\",\"date_to\":\"1891-12-31\"}}" | jq -r .id) \
  || fail "creating a Ship with an uncertain launch date failed"

# A ship renamed twice is still one ship, with its whole name history.
api POST "/subjects/$ship/names" '{"name":"Sofia","date":{"date_from":"1905-03-01"}}' >/dev/null || fail "first rename failed"
api POST "/subjects/$ship/names" '{"name":"Nordstjernan","date":{"date_from":"1921-06-01"}}' >/dev/null || fail "second rename failed"
[ "$(api GET "/ships/$ship" | jq -r .name)" = "Nordstjernan" ] || fail "current name is not the latest"
[ "$(api GET "/subjects/$ship/names" | jq 'length')" = 3 ] || fail "name history should hold three names"

# A ship sold once has an ordered owner history.
owner_a=$(api POST /organisations '{"name":"Rederi A"}' | jq -r .id)
owner_b=$(api POST /organisations '{"name":"Rederi B"}' | jq -r .id)
sale=$(api POST /relations "{\"from_subject_id\":\"$ship\",\"predicate\":\"owned_by\",\"to_subject_id\":\"$owner_a\",\"date\":{\"date_from\":\"1890-05-01\"}}" | jq -r .id)
api PUT "/relations/$sale" '{"date":{"date_from":"1890-05-01","date_to":"1923-04-01"}}' >/dev/null || fail "closing the first ownership failed"
api POST /relations "{\"from_subject_id\":\"$ship\",\"predicate\":\"owned_by\",\"to_subject_id\":\"$owner_b\",\"date\":{\"date_from\":\"1923-04-01\"}}" >/dev/null || fail "second ownership failed"
owners=$(api GET "/subjects/$ship/relations?predicate=owned_by" | jq -r '[.[].to_name] | join(",")')
[ "$owners" = "Rederi A,Rederi B" ] || fail "owner history is [$owners]"

# A rebuilt hull is a new ship linked to the old one.
rebuilt=$(api POST /ships "{\"name\":\"Rebuilt $run\"}" | jq -r .id)
api POST /relations "{\"from_subject_id\":\"$rebuilt\",\"predicate\":\"rebuilt_from\",\"to_subject_id\":\"$ship\"}" >/dev/null || fail "rebuilt-from failed"
[ "$(api GET "/subjects/$ship/relations?predicate=rebuilt_from" | jq 'length')" = 1 ] || fail "old hull does not show the rebuild"

# An inverted date range is refused, and a deleted ship disappears.
status=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/catalog/ships" \
  -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  -d '{"name":"Inverted","launched":{"date_from":"1891-01-01","date_to":"1889-01-01"}}')
[ "$status" = 422 ] || fail "an inverted date range returned $status, expected 422"
api DELETE "/ships/$rebuilt" >/dev/null || fail "deleting a Ship failed"
status=$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/api/catalog/ships/$rebuilt" -H "Authorization: Bearer $token")
[ "$status" = 404 ] || fail "a deleted Ship returned $status, expected 404"

# An Image is uploaded, stored in Garage, linked to the ship, and a re-upload is flagged.
# The page is typed Swedish text, so the OCR further down can be checked against what it says.
scan=$(mktemp); pdf=$(mktemp); corrupt=$(mktemp)
trap 'rm -f "$scan" "$pdf" "$corrupt"' EXIT
expected_text=$(uv run --quiet --no-project --with pillow==11.3.0 python "$(dirname "$0")/make_scan.py" "$scan" "$run") \
  || fail "could not render the test scan (is uv installed?)"
upload() { # upload FILE_PATH TITLE: print the JSON answer, fail on any non-2xx status
  curl -sf -X POST "$BASE_URL/api/catalog/documents" -H "Authorization: Bearer $token" \
    -F "file=@$1;type=image/png" -F "title=$2" -F document_type=letter -F rights=PDM
}
first=$(upload "$scan" "Smoke image $run") || fail "uploading an Image failed"
read -r image document mime review_status duplicate < <(
  echo "$first" | jq -r '[.images[0].id, .id, .images[0].mime, .images[0].review_status, (.duplicate_of_image_id // "none")] | @tsv')
[ "$mime" = image/png ] || fail "mime not recorded: $first"
[ "$review_status" = pending ] || fail "a new Image is not pending"
[ "$duplicate" = none ] || fail "a new Image was flagged as a duplicate"
second=$(upload "$scan" "Smoke image again $run") || fail "uploading the same Image again failed"
[ "$(echo "$second" | jq -r .duplicate_of_image_id)" = "$image" ] || fail "duplicate not flagged: $second"

printf '%%PDF-1.7 not an image' > "$pdf"
refusal=$(curl -s -w '\n%{http_code}' -X POST "$BASE_URL/api/catalog/documents" -H "Authorization: Bearer $token" \
  -F "file=@$pdf;filename=scan.jpg;type=image/jpeg" -F "title=Not an image")
refusal_status=$(echo "$refusal" | tail -1)
refusal_detail=$(echo "$refusal" | head -1 | jq -r .detail)
[ "$refusal_status" = 415 ] || fail "a PDF named .jpg returned $refusal_status, expected 415"
{ echo "$refusal_detail" | grep -q PDF && echo "$refusal_detail" | grep -q HEIC; } || fail "the refusal does not mention PDF and HEIC: $refusal_detail"

api PUT "/documents/$document/subjects/$ship" '{"role":"depicted"}' >/dev/null || fail "linking the document to the ship failed"
[ "$(api GET "/documents/$document" | jq -r '.subjects[0].name')" = Nordstjernan ] || fail "the link did not read back"

# The download address works from inside the cluster, where Garage is reachable, and then expires.
fetch() { # fetch URL: print "<http status> <sha256 of the body>"
  kubectl -n "$NAMESPACE" exec deploy/catalog-api -- python -c '
import hashlib, sys, urllib.error, urllib.request
try:
    answer = urllib.request.urlopen(sys.argv[1], timeout=10)
    print(answer.status, hashlib.sha256(answer.read()).hexdigest())
except urllib.error.HTTPError as error:
    print(error.code, "-")' "$1"
}
address=$(api GET "/images/$image/download-url?expires_in=3" | jq -r .url)
expected=$(shasum -a 256 "$scan" | cut -d' ' -f1)
[ "$(fetch "$address")" = "200 $expected" ] || fail "the download address did not serve the uploaded bytes"
sleep 4
expired=$(fetch "$address" | cut -d' ' -f1)
case "$expired" in 4??) ;; *) fail "the download address returned $expired after it expired, expected a 4xx" ;; esac

# Only catalog-api may write; Cantaloupe's key may only read the masters. The keys go to the
# probe on stdin, never on a command line where `ps` would show them.
key_of() { kubectl -n "$NAMESPACE" get secret "$1" -o jsonpath="{.data.$2}" | base64 -d; }
probe_script=$(cat "$(dirname "$0")/s3_probe.py")
probe() {
  printf '%s\n%s\n' "$(key_of "$1" S3_ACCESS_KEY_ID)" "$(key_of "$1" S3_SECRET_ACCESS_KEY)" \
    | kubectl -n "$NAMESPACE" exec -i deploy/catalog-api -- python -c "$probe_script"
}
catalog_rights=$(probe catalog-api-s3)
echo "$catalog_rights" | jq -e '. == {"read derivatives": "denied", "read masters": "allowed", "write derivatives": "denied", "write masters": "allowed"}' >/dev/null \
  || fail "catalog-api's key has the wrong rights: $catalog_rights"
cantaloupe_rights=$(probe cantaloupe-s3)
echo "$cantaloupe_rights" | jq -e '. == {"read derivatives": "denied", "read masters": "allowed", "write derivatives": "denied", "write masters": "denied"}' >/dev/null \
  || fail "Cantaloupe's key has the wrong rights: $cantaloupe_rights"

# The uploaded page is read without anyone asking: it reaches ocr_done, and the Machine
# transcription says what the page says.
wait_for_status() { # wait_for_status IMAGE_ID STATUS SECONDS: succeed once the Image has that Review status
  local deadline=$((SECONDS + $3))
  while [ "$SECONDS" -lt "$deadline" ]; do
    [ "$(api GET "/images/$1" | jq -r .review_status)" = "$2" ] && return 0
    sleep 1
  done
  return 1
}
wait_for_status "$image" ocr_done 90 || fail "the uploaded Image never reached ocr_done"
transcriptions=$(api GET "/images/$image/transcriptions")
[ "$(echo "$transcriptions" | jq length)" = 1 ] || fail "expected one Transcription: $transcriptions"
echo "$transcriptions" | jq -e '.[0] | .source == "machine" and .engine == "tesseract" and .language == "swe+eng"
  and (.engine_version | length > 0) and (.confidence > 0.8)' >/dev/null \
  || fail "the Machine transcription is incomplete: $transcriptions"
accuracy=$(python3 - "$expected_text" "$(echo "$transcriptions" | jq -r '.[0].text')" <<'PY'
import difflib, sys
expected, actual = (" ".join(text.split()) for text in sys.argv[1:3])
print(f"{difflib.SequenceMatcher(None, expected, actual).ratio():.3f}")
PY
)
awk -v accuracy="$accuracy" 'BEGIN { exit !(accuracy >= 0.95) }' || fail "OCR accuracy $accuracy is below 0.95"
echo "OCR accuracy on the Swedish test page: $accuracy"

# A corrupt image ends as failed after its bounded attempts, lands in the dead-letter queue, and the
# worker carries on; reading it again publishes a new job.
dead_letters() { kubectl -n "$NAMESPACE" exec rabbitmq-0 -- rabbitmqctl -q list_queues name messages | awk '$1 == "ocr.requested.dead" {print $2}'; }
worker_restarts() { kubectl -n "$NAMESPACE" get pods -l app=transcribe-worker -o jsonpath='{.items[*].status.containerStatuses[0].restartCount}' | tr ' ' '\n' | awk '{s += $1} END {print s + 0}'; }
dead_before=$(dead_letters); restarts_before=$(worker_restarts)
printf '\x89PNG\r\n\x1a\n this is not really a png' > "$corrupt"
broken=$(upload "$corrupt" "Corrupt image $run" | jq -r '.images[0].id') || fail "uploading the corrupt image failed"
wait_for_status "$broken" failed 120 || fail "the corrupt Image never reached failed"
[ "$(dead_letters)" = "$((dead_before + 1))" ] || fail "the corrupt job is not in the dead-letter queue"
api POST "/images/$broken/ocr" >/dev/null || fail "reading the failed Image again was refused"
wait_for_status "$broken" failed 120 || fail "the re-run corrupt Image never reached failed again"
[ "$(dead_letters)" = "$((dead_before + 2))" ] || fail "reading again did not publish a new job"
[ "$(worker_restarts)" = "$restarts_before" ] || fail "the worker restarted while handling a corrupt image"

# A finished Image can be read again; both Machine transcriptions are kept.
api POST "/images/$image/ocr" >/dev/null || fail "reading a finished Image again was refused"
wait_for_status "$image" ocr_done 90 || fail "the re-read Image never reached ocr_done"
[ "$(api GET "/images/$image/transcriptions" | jq length)" = 2 ] || fail "the first reading was not kept"

echo "SMOKE OK: ship $id created and read back as $staff_name; renames, sale, rebuild, validation and delete verified; Image uploaded to Garage, duplicate flagged, link read back, download address works and expires, key rights verified; page read automatically at $accuracy accuracy, corrupt image failed into the dead-letter queue, re-read works"
