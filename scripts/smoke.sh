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
# The token travels in a private file read by curl, not on a command line where `ps` would show it.
auth_header=$(mktemp)
printf 'Authorization: Bearer %s\n' "$token" > "$auth_header"
trap 'rm -f "$auth_header" "${scan:-}" "${pdf:-}" "${corrupt:-}" "${page_two:-}"' EXIT

status=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/catalog/ships" \
  -H 'Content-Type: application/json' -d '{"name":"Unauthorised"}')
[ "$status" = 401 ] || fail "creating a Ship without a token returned $status, expected 401"

name="Smoke $(date +%s)"
created=$(curl -sf -X POST "$BASE_URL/api/catalog/ships" \
  -H @"$auth_header" -H 'Content-Type: application/json' \
  -d "{\"name\":\"$name\"}") || fail "creating a Ship through the Ingress failed"
id=$(echo "$created" | jq -r .id)

read_back=$(curl -sf "$BASE_URL/api/catalog/ships/$id" -H @"$auth_header") \
  || fail "reading the Ship back failed"
[ "$(echo "$read_back" | jq -r .name)" = "$name" ] || fail "name did not round-trip: $read_back"
[ "$(echo "$read_back" | jq -r .created_by)" = "$staff_name" ] || fail "author not recorded: $read_back"

api() { # api METHOD PATH [JSON]: call catalog-api as Staff, fail on any non-2xx answer
  local method=$1 path=$2 body=${3:-}
  if [ -n "$body" ]; then
    curl -sf -X "$method" "$BASE_URL/api/catalog$path" -H @"$auth_header" \
      -H 'Content-Type: application/json' -d "$body"
  else
    curl -sf -X "$method" "$BASE_URL/api/catalog$path" -H @"$auth_header"
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
  -H @"$auth_header" -H 'Content-Type: application/json' \
  -d '{"name":"Inverted","launched":{"date_from":"1891-01-01","date_to":"1889-01-01"}}')
[ "$status" = 422 ] || fail "an inverted date range returned $status, expected 422"
api DELETE "/ships/$rebuilt" >/dev/null || fail "deleting a Ship failed"
status=$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/api/catalog/ships/$rebuilt" -H @"$auth_header")
[ "$status" = 404 ] || fail "a deleted Ship returned $status, expected 404"

# An Image is uploaded, stored in Garage, linked to the ship, and a re-upload is flagged.
# The page is typed Swedish text, so the OCR further down can be checked against what it says.
scan=$(mktemp); pdf=$(mktemp); corrupt=$(mktemp); page_two=$(mktemp)
expected_text=$(uv run --quiet --no-project --with pillow==11.3.0 python "$(dirname "$0")/make_scan.py" "$scan" "$run") \
  || fail "could not render the test scan (is uv installed?)"
upload() { # upload FILE_PATH TITLE: print the JSON answer, fail on any non-2xx status
  curl -sf -X POST "$BASE_URL/api/catalog/documents" -H @"$auth_header" \
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
refusal=$(curl -s -w '\n%{http_code}' -X POST "$BASE_URL/api/catalog/documents" -H @"$auth_header" \
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
wait_for_dead_letters() { # wait_for_dead_letters COUNT SECONDS: the Image is marked failed just before its message is dead-lettered
  local deadline=$((SECONDS + $2))
  while [ "$SECONDS" -lt "$deadline" ]; do
    [ "$(dead_letters)" = "$1" ] && return 0
    sleep 1
  done
  return 1
}
worker_restarts() { kubectl -n "$NAMESPACE" get pods -l app=transcribe-worker -o jsonpath='{.items[*].status.containerStatuses[0].restartCount}' | tr ' ' '\n' | awk '{s += $1} END {print s + 0}'; }
dead_before=$(dead_letters); restarts_before=$(worker_restarts)
printf '\x89PNG\r\n\x1a\n this is not really a png' > "$corrupt"
broken=$(upload "$corrupt" "Corrupt image $run" | jq -r '.images[0].id') || fail "uploading the corrupt image failed"
wait_for_status "$broken" failed 120 || fail "the corrupt Image never reached failed"
wait_for_dead_letters "$((dead_before + 1))" 30 || fail "the corrupt job is not in the dead-letter queue"
api POST "/images/$broken/ocr" >/dev/null || fail "reading the failed Image again was refused"
wait_for_status "$broken" failed 120 || fail "the re-run corrupt Image never reached failed again"
wait_for_dead_letters "$((dead_before + 2))" 30 || fail "reading again did not publish a new job"
[ "$(worker_restarts)" = "$restarts_before" ] || fail "the worker restarted while handling a corrupt image"

# A finished Image can be read again; both Machine transcriptions are kept.
api POST "/images/$image/ocr" >/dev/null || fail "reading a finished Image again was refused"
wait_for_status "$image" ocr_done 90 || fail "the re-read Image never reached ocr_done"
[ "$(api GET "/images/$image/transcriptions" | jq length)" = 2 ] || fail "the first reading was not kept"

# A person's correction is a Human transcription. It verifies its page and keeps the earlier readings,
# and a Document stays in the review queue, with a count, until every page is verified.
[ "$(api GET /me | jq -r .name)" = "$staff_name" ] || fail "/me does not say who the token belongs to"
queue_item() { # queue_item DOCUMENT_ID: print the Document's queue entry, or fail if it is not in the queue
  local offset=0 page
  while :; do
    page=$(api GET "/review-queue?limit=200&offset=$offset")
    echo "$page" | jq -ce --arg id "$1" '.[] | select(.id == $id)' && return 0
    [ "$(echo "$page" | jq length)" -lt 200 ] && return 1
    offset=$((offset + 200))
  done
}
machine_body='{"source":"machine","text":"x","engine":"e","engine_version":"1","language":"swe"}'
status=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/catalog/images/$image/transcriptions" \
  -H @"$auth_header" -H 'Content-Type: application/json' -d "$machine_body")
[ "$status" = 401 ] || fail "Staff posting a Machine transcription returned $status, expected 401"
status=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/catalog/images/$image/transcriptions" \
  -H 'Content-Type: application/json' -d '{"source":"human","text":"x"}')
[ "$status" = 401 ] || fail "a correction without a token returned $status, expected 401"

uv run --quiet --no-project --with pillow==11.3.0 python "$(dirname "$0")/make_scan.py" "$page_two" "$run-page-two" >/dev/null
added=$(curl -sf -X POST "$BASE_URL/api/catalog/documents/$document/images" -H @"$auth_header" \
  -F "file=@$page_two;type=image/png") || fail "adding a second page failed"
page2=$(echo "$added" | jq -r '.images[1].id')
[ "$(echo "$added" | jq -r '.images | map(.page_no) | join(",")')" = "1,2" ] || fail "the second page was not numbered 2: $added"

content_headers=$(mktemp)
served=$(curl -sf -D "$content_headers" "$BASE_URL/api/catalog/images/$image/content" -H @"$auth_header" | shasum -a 256 | cut -d' ' -f1)
[ "$served" = "$(shasum -a 256 < "$scan" | cut -d' ' -f1)" ] || fail "the served scan differs from the uploaded file"
grep -qi '^x-content-type-options: nosniff' "$content_headers" || fail "the scan is served without nosniff"
rm -f "$content_headers"
status=$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/api/catalog/images/$image/content")
[ "$status" = 401 ] || fail "the scan was served without a token ($status)"

corrected="Skeppet Vega lämnade Göteborg den 14 mars 1891. Ref zebrafink$run"
api POST "/images/$image/transcriptions" "{\"source\":\"human\",\"text\":\"$corrected\"}" >/dev/null || fail "saving a correction failed"
api GET "/images/$image" | jq -e --arg text "$corrected" '.verified and .review_status == "verified" and .text_source == "human" and .current_text == $text' >/dev/null \
  || fail "the corrected Image is not verified with the corrected text"
history=$(api GET "/images/$image/transcriptions")
[ "$(echo "$history" | jq 'map(.source) | join(",")' -r)" = "human,machine,machine" ] || fail "the earlier readings were not kept: $history"
[ "$(echo "$history" | jq -r '.[0].created_by')" = "$staff_name" ] || fail "the correction does not say who made it"

entry=$(queue_item "$document") || fail "a partly verified Document is not in the review queue"
echo "$entry" | jq -e '.verified_images == 1 and .image_count == 2' >/dev/null || fail "the queue entry has the wrong counts: $entry"
api GET "/documents/$document" | jq -e '(.verified | not) and .verified_images == 1 and .image_count == 2' >/dev/null \
  || fail "a half-verified Document is reported as verified"
status=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/catalog/images/$image/ocr" -H @"$auth_header")
[ "$status" = 409 ] || fail "reading a verified Image again returned $status, expected 409"

wait_for_status "$page2" ocr_done 90 || fail "the added page never reached ocr_done"
api POST "/images/$page2/transcriptions" '{"source":"human","text":"Sida två."}' >/dev/null || fail "correcting the second page failed"
api GET "/documents/$document" | jq -e '.verified and .verified_images == 2' >/dev/null || fail "the Document is not verified after both pages are"
queue_item "$document" >/dev/null && fail "a fully verified Document is still in the review queue"

# The web UI is served at the root, and an address inside it survives a reload.
[ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/")" = 200 ] || fail "the web UI is not served at the root"
deep=$(curl -s -o /dev/null -w '%{http_code} %{content_type}' "$BASE_URL/documents/$document/review")
[ "$deep" = "200 text/html" ] || fail "a deep UI address did not fall back to the app: $deep"

# Search: the corrected document is found, flagged verified, within seconds of its last correction.
# Every poll carries a changing parameter, so the 5 second answer cache cannot hide a stale index.
search_for() { # search_for PATH JQ_FILTER SECONDS [curl --data-urlencode args...]: succeed once the answer satisfies the filter
  local path=$1 filter=$2 seconds=$3; shift 3
  local deadline=$((SECONDS + seconds))
  while [ "$SECONDS" -lt "$deadline" ]; do
    curl -sfG "$BASE_URL/api/search$path" --data-urlencode "_=$SECONDS$RANDOM" "$@" | jq -e "$filter" >/dev/null && return 0
    sleep 1
  done
  return 1
}
yard=$(api POST /organisations "{\"name\":\"Yard $run\",\"place\":\"Lindholmen\"}" | jq -r .id)
api POST /relations "{\"from_subject_id\":\"$ship\",\"predicate\":\"built_by\",\"to_subject_id\":\"$yard\",\"date\":{\"date_from\":\"1889-06-01\",\"date_to\":\"1890-03-01\"}}" >/dev/null \
  || fail "recording the builder failed"
second_document=$(echo "$second" | jq -r .id)

search_for /documents "any(.hits[]; .id == \"$document\" and .verified == true and .verified_images == 2)" 30 --data-urlencode "q=$run" --data-urlencode page_size=50 \
  || fail "the corrected Document did not appear in search flagged verified"
search_for /documents "any(.hits[]; .id == \"$second_document\" and .verified == false)" 30 --data-urlencode "q=$run" --data-urlencode page_size=50 \
  || fail "the unverified Document is not returned by default with verified false"
search_for /documents "any(.hits[]; .id == \"$second_document\") | not" 5 --data-urlencode "q=$run" --data-urlencode page_size=50 --data-urlencode verified_only=true \
  || fail "the unverified Document is still returned under verified-only"
search_for /documents "any(.hits[]; .id == \"$document\")" 5 --data-urlencode "q=$run" --data-urlencode page_size=50 --data-urlencode verified_only=true \
  || fail "the verified Document is missing under verified-only"

# The words of the correction are what is searched, and the answer highlights them.
search_for /documents "any(.hits[]; .id == \"$document\" and any(.highlights.text[]; .match and (.text | ascii_downcase | contains(\"zebrafink$run\"))))" 30 \
  --data-urlencode "q=zebrafink$run" || fail "the corrected text was not searchable"

# A ship is found by an old name, and the answer says which name matched.
search_for /subjects "any(.hits[]; .id == \"$ship\" and .name == \"Nordstjernan\" and .matched_name == \"Vega $run\")" 30 --data-urlencode "q=Vega $run" \
  || fail "the ship was not found by its old name with the matching name shown"
# Builder and year come from the Relation: they filter the ship, and the document that shows it.
search_for /subjects "any(.hits[]; .id == \"$ship\" and .builders == [\"Yard $run\"] and .year_from == 1889)" 30 \
  --data-urlencode "q=Vega $run" --data-urlencode "builder=Yard $run" --data-urlencode year_from=1889 --data-urlencode year_to=1890 \
  || fail "the ship was not found by builder and year derived from its Relation"
search_for /documents "any(.hits[]; .id == \"$document\")" 30 --data-urlencode "q=$run" --data-urlencode "builder=Yard $run" --data-urlencode place=Lindholmen \
  || fail "the document was not found by the builder and place of the ship it shows"

# IIIF: the Image id is the public identifier, and Cantaloupe reads the original from Garage under that
# same id. Information, tiles and the links in search results all come through the Ingress.
info=$(curl -sf "$BASE_URL/iiif/3/$image/info.json") || fail "the IIIF information document for the uploaded Image is not served"
echo "$info" | jq -e --arg id "$image" '.protocol == "http://iiif.io/api/image" and .type == "ImageService3" and .width > 0 and .height > 0 and (.id | endswith("/iiif/3/" + $id)) and (.id | startswith("http"))' >/dev/null \
  || fail "the IIIF information document is wrong: $info"
tile=$(curl -s -o /dev/null -w '%{http_code} %{content_type}' "$BASE_URL/iiif/3/$image/full/!256,256/0/default.jpg")
[ "$tile" = "200 image/jpeg" ] || fail "a tile of the uploaded Image returned [$tile]"
[ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/iiif/3/00000000-0000-4000-8000-000000000000/info.json")" = 404 ] || fail "an unknown Image id did not give 404"
curl -sI "$BASE_URL/iiif/3/$image/full/!256,256/0/default.jpg" | tr -d '\r' | grep -iq '^cache-control: .*max-age=' || fail "tiles are served without cache headers"
thumbnail=$(curl -sfG "$BASE_URL/api/search/documents" --data-urlencode "q=$run" --data-urlencode page_size=50 --data-urlencode "n=$RANDOM" | jq -r --arg d "$document" '.hits[] | select(.id == $d) | .thumbnail')
info_link=$(curl -sfG "$BASE_URL/api/search/documents" --data-urlencode "q=$run" --data-urlencode page_size=50 --data-urlencode "n=$RANDOM" | jq -r --arg d "$document" '.hits[] | select(.id == $d) | .pages[0].iiif_info')
[ "$(curl -s -o /dev/null -w '%{http_code} %{content_type}' "$BASE_URL$thumbnail")" = "200 image/jpeg" ] || fail "the thumbnail link in the search result does not work: $thumbnail"
curl -sf "$BASE_URL$info_link" | jq -e '.width > 0' >/dev/null || fail "the information link in the search result does not work: $info_link"
# Garage and Cantaloupe's own endpoints are never reachable through the Ingress. Each of these addresses
# must give the app's own page or a refusal, never JSON, XML or an image from somewhere else. The dot
# segments are sent as they are, because curl would otherwise tidy them away before they reach the Ingress.
for path in "masters/$image" "api/garage/v1/status" "admin" "health" "iiif/3/$image/../../masters/$image" \
            "iiif/3/../health" "iiif/3/%2e%2e/health" "iiif/3/$image/..%2f..%2fadmin"; do
  answer=$(curl -s --path-as-is -o /dev/null -w '%{http_code} %{content_type}' "$BASE_URL/$path")
  case "$answer" in
    "200 text/html"* | 4* | 502*) ;;  # the app's own page, or the Ingress refusing the address
    *) fail "/$path answered [$answer], so something other than the app or the IIIF API may be reachable" ;;
  esac
done

# Landing pages: every record has an open page of its own, read from the index with no token.
sister=$(api POST /ships "{\"name\":\"Sister $run\"}" | jq -r .id)
api POST /relations "{\"from_subject_id\":\"$sister\",\"predicate\":\"rebuilt_from\",\"to_subject_id\":\"$ship\",\"date\":{\"date_text\":\"1912\"}}" >/dev/null \
  || fail "recording the rebuild failed"
search_for "/documents/$document" '.verified == true and .image_count == 2 and (.images | map(.rights) == ["PDM", "reserved"]) and (.images[0].verified and .images[0].text_source == "human") and (.images[0].text | contains("Göteborg")) and any(.subjects[]; .id == "'"$ship"'" and .role == "depicted")' 30 \
  || fail "the Document's landing record is missing its rights, verified state, text or subjects"
search_for "/subjects/$ship" '.entity == "ship" and .name == "Nordstjernan" and (.names | map(.name) | sort == ["Nordstjernan", "Sofia", "Vega '"$run"'"]) and any(.relations[]; .predicate == "built_by" and .direction == "from" and .other_name == "Yard '"$run"'") and any(.relations[]; .predicate == "rebuilt_from" and .direction == "to" and .other_id == "'"$sister"'") and any(.documents[]; .id == "'"$document"'" and .verified == true)' 30 \
  || fail "the Ship's landing record is missing its names, relations or documents"
search_for "/subjects/$sister" 'any(.relations[]; .predicate == "rebuilt_from" and .direction == "from" and .other_id == "'"$ship"'" and .date_text == "1912")' 30 \
  || fail "the rebuilt Ship does not link back to the old one"
[ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/api/search/documents/$ship")" = 404 ] || fail "a Ship was served as a Document"
for page in "ships/$ship" "documents/$document" "ships/$sister"; do
  [ "$(curl -s -o /dev/null -w '%{http_code} %{content_type}' "$BASE_URL/$page")" = "200 text/html" ] || fail "the address /$page does not give the app, so reload and sharing would break"
done

# Wikidata: staff ask for candidates and choose one; nothing is stored by asking. Refusals need no internet.
unknown_ship=00000000-0000-4000-8000-000000000000
[ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/api/catalog/ships/$ship/wikidata-candidates")" = 401 ] || fail "asking Wikidata for candidates without a token was not refused"
[ "$(curl -s -o /dev/null -w '%{http_code}' -X PUT "$BASE_URL/api/catalog/ships/$ship/wikidata/Q219821")" = 401 ] || fail "choosing a Wikidata match without a token was not refused"
[ "$(curl -s -o /dev/null -w '%{http_code}' -X PUT "$BASE_URL/api/catalog/ships/$ship/wikidata/not-an-item" -H @"$auth_header")" = 422 ] || fail "a bad Wikidata identifier was not refused"
[ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/api/catalog/ships/$unknown_ship/wikidata-candidates" -H @"$auth_header")" = 404 ] || fail "candidates for an unknown ship were not refused"
# The real Wikidata is somebody else's service on the internet. If this machine cannot reach it the check
# is skipped and says so; it is never passed silently.
if curl -sf --max-time 8 -o /dev/null "https://www.wikidata.org/w/api.php?action=query&meta=siteinfo&format=json"; then
  [ "$(api GET "/ships/$ship" | jq '.external_refs | length')" = 0 ] || fail "the ship already had Wikidata matches"
  api GET "/ships/$ship/wikidata-candidates?q=Vasa" | jq -e 'any(.candidates[]; .id == "Q219821" and (.description | length > 0) and .url == "https://www.wikidata.org/wiki/Q219821")' >/dev/null \
    || fail "the real Wikidata did not list the Vasa among the candidates for Vasa"
  [ "$(api GET "/ships/$ship" | jq '.external_refs | length')" = 0 ] || fail "asking for candidates stored something"
  api PUT "/ships/$ship/wikidata/Q219821" | jq -e '.source == "wikidata" and .id == "Q219821" and .chosen_by == "'"$staff_name"'" and (.retrieved_at | length > 0)' >/dev/null \
    || fail "choosing a Wikidata match did not store its source, identifier and retrieval time"
  api GET "/ships/$ship" | jq -e '.external_refs | map(.id) == ["Q219821"]' >/dev/null || fail "the chosen match was not stored on the ship"
  search_for "/subjects/$ship" 'any(.external_refs[]; .source == "wikidata" and .id == "Q219821" and (.retrieved_at | length > 0))' 30 \
    || fail "the chosen Wikidata match did not reach search"
  api DELETE "/ships/$ship/wikidata/Q219821" >/dev/null || fail "removing the Wikidata match failed"
  search_for "/subjects/$ship" '.external_refs | length == 0' 30 || fail "the removed Wikidata match is still in search"
  wikidata_checked="Wikidata candidates listed, a match chosen with its source and retrieval time, found in search and removed"
else
  echo "SKIPPED: Wikidata cannot be reached from this machine, so choosing a real match was not tried"
  wikidata_checked="Wikidata refusals checked (the real service was not reachable, so choosing a match was skipped)"
fi

# A deleted record leaves the index.
doomed=$(api POST /ships "{\"name\":\"Doomed $run\"}" | jq -r .id)
search_for /subjects "any(.hits[]; .id == \"$doomed\")" 30 --data-urlencode "q=Doomed $run" || fail "the new ship never reached search"
api DELETE "/ships/$doomed" >/dev/null || fail "deleting the ship failed"
search_for /subjects "any(.hits[]; .id == \"$doomed\") | not" 30 --data-urlencode "q=Doomed $run" || fail "the deleted ship is still searchable"
[ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/api/search/subjects/$doomed")" = 404 ] || fail "the deleted ship still has a landing record"

# Page size is capped and repeated queries are served from the cache.
[ "$(curl -sfG "$BASE_URL/api/search/documents" --data-urlencode page_size=5000 | jq '.page_size')" = 50 ] || fail "the page size was not capped at 50"
cache_probe="cache-$run"
# Each search-api replica has its own cache, so the same query is a MISS until a replica sees it twice: ask repeatedly.
cache_of() { curl -sG -D - -o /dev/null "$BASE_URL/api/search/documents" --data-urlencode "q=$cache_probe" | tr -d '\r' | awk -F': ' 'tolower($1) == "x-cache" {print $2}'; }
first_cache=$(cache_of)
second_cache=MISS
for _ in $(seq 1 20); do
  second_cache=$(cache_of)
  [ "$second_cache" = HIT ] && break
done
[ "$first_cache,$second_cache" = "MISS,HIT" ] || fail "repeated queries were not cached: $first_cache,$second_cache"

echo "SMOKE OK: ship $id created and read back as $staff_name; renames, sale, rebuild, validation and delete verified; Image uploaded to Garage, duplicate flagged, link read back, download address works and expires, key rights verified; page read automatically at $accuracy accuracy, corrupt image failed into the dead-letter queue, re-read works; page added, scan served, correction verified and kept beside the readings, review queue counts right, web UI served with deep links; search finds the corrected document verified, the unverified one only by default, a ship by its old name, builder and year from Relations, deletes leave the index, page size capped, cache hits; open landing records for a Document and for two Ships, with rights, verified state, names, relations and a rebuilt-from link, and their addresses reload; $wikidata_checked; IIIF information, a tile and the links in search results work through the Ingress and Garage is not exposed"
