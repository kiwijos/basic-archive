#!/usr/bin/env bash
# Helpers for the scripts that exercise the running cluster. Source it: . scripts/lib.sh
NAMESPACE=${NAMESPACE:-ship-archive}
BASE_URL=${BASE_URL:-http://localhost}
SCRIPTS_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

fail() { echo "FAILED: $*" >&2; exit 1; }

# The first staff token, as name=token.
first_pair=$(kubectl -n "$NAMESPACE" get secret catalog-api-secrets -o jsonpath='{.data.STAFF_TOKENS}' | base64 -d | cut -d, -f1)
token=${first_pair#*=}
# The token travels in a private file read by curl, not on a command line where `ps` would show it.
# Scripts that source this file must not set their own EXIT trap without also removing this file.
auth_header=$(mktemp)
printf 'Authorization: Bearer %s\n' "$token" > "$auth_header"

api() { # api METHOD PATH [JSON]: call catalog-api as Staff, fail on any non-2xx answer
  local method=$1 path=$2 body=${3:-}
  if [ -n "$body" ]; then
    curl -sf -X "$method" "$BASE_URL/api/catalog$path" -H @"$auth_header" \
      -H 'Content-Type: application/json' -d "$body"
  else
    curl -sf -X "$method" "$BASE_URL/api/catalog$path" -H @"$auth_header"
  fi
}

upload_scan() { # upload_scan RUN_ID: render a Swedish test page, upload it, print the new Image id
  local file
  file=$(mktemp)
  uv run --quiet --no-project --with pillow==11.3.0 python "$SCRIPTS_DIR/make_scan.py" "$file" "$1" >/dev/null
  curl -sf -X POST "$BASE_URL/api/catalog/documents" -H @"$auth_header" \
    -F "file=@$file;type=image/png" -F "title=Test page $1" -F document_type=letter | jq -r '.images[0].id'
  rm -f "$file"
}

wait_for_status() { # wait_for_status IMAGE_ID STATUS SECONDS: succeed once the Image has that Review status
  local deadline=$((SECONDS + $3))
  while [ "$SECONDS" -lt "$deadline" ]; do
    [ "$(api GET "/images/$1" | jq -r .review_status)" = "$2" ] && return 0
    sleep 1
  done
  return 1
}

queue_messages() { # queue_messages QUEUE: how many messages are waiting in a RabbitMQ queue
  kubectl -n "$NAMESPACE" exec rabbitmq-0 -- rabbitmqctl -q list_queues name messages | awk -v queue="$1" '$1 == queue {print $2}'
}

unpublished_events() { # events still waiting in the outbox
  kubectl -n "$NAMESPACE" exec postgres-0 -- psql -U postgres -d archive -tAc "SELECT count(*) FROM outbox WHERE published_at IS NULL"
}
