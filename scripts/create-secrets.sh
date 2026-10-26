#!/usr/bin/env bash
# Creates each app Secret with random values unless it already exists, so it is safe to run
# again and only adds what a newer slice needs.
# Secret values go to kubectl on stdin, never as arguments, so they do not show up in `ps`.
# Real secrets never enter the repository; k8s/secrets.template.yaml documents their shape.
set -euo pipefail

NAMESPACE=${NAMESPACE:-ship-archive}
STAFF_NAMES=${STAFF_NAMES:-"kiwijos"}

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

random() { openssl rand -hex 24; }
missing() { ! kubectl -n "$NAMESPACE" get secret "$1" >/dev/null 2>&1; }

# Garage access keys are "GK" and 24 hex characters, with a 64 hex character secret.
create_s3_secret() {
  kubectl -n "$NAMESPACE" create -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: $1
type: Opaque
stringData:
  S3_ACCESS_KEY_ID: "GK$(openssl rand -hex 12)"
  S3_SECRET_ACCESS_KEY: "$(openssl rand -hex 32)"
EOF
}

if missing postgres-credentials; then
  POSTGRES_PASSWORD=$(random)
  STAFF_TOKENS=""
  for name in $STAFF_NAMES; do
    STAFF_TOKENS="${STAFF_TOKENS:+$STAFF_TOKENS,}${name}=$(random)"
  done
  kubectl -n "$NAMESPACE" create -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: postgres-credentials
type: Opaque
stringData:
  POSTGRES_PASSWORD: "$POSTGRES_PASSWORD"
---
apiVersion: v1
kind: Secret
metadata:
  name: catalog-api-secrets
type: Opaque
stringData:
  DATABASE_URL: "postgresql+psycopg://postgres:${POSTGRES_PASSWORD}@postgres:5432/archive"
  STAFF_TOKENS: "$STAFF_TOKENS"
EOF
fi

if missing garage-secrets; then
  kubectl -n "$NAMESPACE" create -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: garage-secrets
type: Opaque
stringData:
  rpc-secret: "$(openssl rand -hex 32)"
  admin-token: "$(random)"
EOF
fi

# One key per service, so each can be given only the access it needs.
if missing catalog-api-s3; then
  create_s3_secret catalog-api-s3
fi
if missing cantaloupe-s3; then
  create_s3_secret cantaloupe-s3
fi

# A first login for the broker, used until the separate per-service logins below replace it in each service's URL (the
# broker's own login is then the administrator's and nothing connects as it). The worker acts on the API with a
# token of its own.
if missing rabbitmq-credentials; then
  BROKER_PASSWORD=$(random)
  WORKER_TOKEN=$(random)
  BROKER_URL="amqp://archive:${BROKER_PASSWORD}@rabbitmq:5672/%2F"
  kubectl -n "$NAMESPACE" create -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: rabbitmq-credentials
type: Opaque
stringData:
  RABBITMQ_DEFAULT_USER: "archive"
  RABBITMQ_DEFAULT_PASS: "$BROKER_PASSWORD"
---
apiVersion: v1
kind: Secret
metadata:
  name: catalog-api-amqp
type: Opaque
stringData:
  RABBITMQ_URL: "$BROKER_URL"
---
apiVersion: v1
kind: Secret
metadata:
  name: catalog-api-service-tokens
type: Opaque
stringData:
  SERVICE_TOKENS: "transcribe-worker=$WORKER_TOKEN"
---
apiVersion: v1
kind: Secret
metadata:
  name: transcribe-worker-env
type: Opaque
stringData:
  RABBITMQ_URL: "$BROKER_URL"
  CATALOG_API_TOKEN: "$WORKER_TOKEN"
EOF
fi

# Search: Meilisearch has a master key, and each service gets a key of its own that can do only what
# it needs (k8s/meilisearch/keys.json). A key is derived from the master key and the key's uid, so
# it can be worked out here, and a Job registers the same keys in Meilisearch.
meili_key() { # meili_key NAME: the key for that entry of keys.json; the master key is read from stdin
  local uid
  uid=$(jq -r --arg name "$1" '.[] | select(.name == $name) | .uid' "$(dirname "$0")/../k8s/meilisearch/keys.json")
  python3 -c 'import hashlib, hmac, sys; print(hmac.new(sys.stdin.read().strip().encode(), sys.argv[1].encode(), hashlib.sha256).hexdigest())' "$uid"
}
secret_value() { kubectl -n "$NAMESPACE" get secret "$1" -o jsonpath="{.data.$2}" | base64 -d; }

if missing meilisearch-secrets; then
  kubectl -n "$NAMESPACE" create -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: meilisearch-secrets
type: Opaque
stringData:
  MEILI_MASTER_KEY: "$(openssl rand -hex 32)"
EOF
fi

if missing indexer-env; then
  # The indexer reads catalog-api as a service of its own, so catalog-api must accept its token. If an
  # earlier run got as far as registering the token but not as far as writing indexer-env, reuse it.
  tokens=$(secret_value catalog-api-service-tokens SERVICE_TOKENS)
  existing=$(printf '%s' "$tokens" | tr ',' '\n' | grep '^indexer=' | head -1 || true)
  if [ -n "$existing" ]; then
    INDEXER_TOKEN=${existing#indexer=}
  else
    INDEXER_TOKEN=$(random)
    printf '%s' "${tokens},indexer=${INDEXER_TOKEN}" | kubectl -n "$NAMESPACE" create secret generic catalog-api-service-tokens \
      --from-file=SERVICE_TOKENS=/dev/stdin --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    # Pods read their tokens when they start.
    kubectl -n "$NAMESPACE" rollout restart deployment/catalog-api >/dev/null 2>&1 || true
  fi
  INDEXER_MEILI_KEY=$(secret_value meilisearch-secrets MEILI_MASTER_KEY | meili_key indexer)
  kubectl -n "$NAMESPACE" create -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: indexer-env
type: Opaque
stringData:
  RABBITMQ_URL: "$(secret_value catalog-api-amqp RABBITMQ_URL)"
  CATALOG_API_TOKEN: "$INDEXER_TOKEN"
  MEILI_KEY: "$INDEXER_MEILI_KEY"
  REINDEX_TOKEN: "$(random)"
EOF
fi

if missing search-api-env; then
  kubectl -n "$NAMESPACE" create -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: search-api-env
type: Opaque
stringData:
  MEILI_KEY: "$(secret_value meilisearch-secrets MEILI_MASTER_KEY | meili_key search)"
EOF
fi

# Separate broker logins: the broker's own login (rabbitmq-credentials) is the administrator and nothing connects as
# it. Each service gets a login and password of its own, created by the broker when it starts
# (k8s/rabbitmq/provision.sh), and its RABBITMQ_URL is rewritten to use it. This also moves a cluster from before
# slice 13, where all three shared the administrator's login, onto separate ones.
#
# The rabbitmq-users Secret is created LAST and marks the work as done: if this dies half way, a rerun finds it missing
# and starts again with fresh passwords, so the URLs and the broker's logins can never end up disagreeing. For a moment
# after the services are restarted with their new URLs the broker may not have created the logins yet (it does so when
# it restarts, which `make deploy` does next); the services retry their connection until it does.
if missing rabbitmq-users; then
  CATALOG_API_PASSWORD=$(random)
  TRANSCRIBE_WORKER_PASSWORD=$(random)
  INDEXER_PASSWORD=$(random)
  set_broker_login() { # set_broker_login SECRET LOGIN PASSWORD: point the secret's RABBITMQ_URL at that login
    kubectl -n "$NAMESPACE" patch secret "$1" --type merge --patch-file /dev/stdin >/dev/null <<EOF
{"stringData": {"RABBITMQ_URL": "amqp://$2:$3@rabbitmq:5672/%2F"}}
EOF
  }
  set_broker_login catalog-api-amqp catalog-api "$CATALOG_API_PASSWORD"
  set_broker_login transcribe-worker-env transcribe-worker "$TRANSCRIBE_WORKER_PASSWORD"
  set_broker_login indexer-env indexer "$INDEXER_PASSWORD"
  kubectl -n "$NAMESPACE" create -f - >/dev/null <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: rabbitmq-users
type: Opaque
stringData:
  CATALOG_API_PASSWORD: "$CATALOG_API_PASSWORD"
  TRANSCRIBE_WORKER_PASSWORD: "$TRANSCRIBE_WORKER_PASSWORD"
  INDEXER_PASSWORD: "$INDEXER_PASSWORD"
EOF
  for deployment in catalog-api transcribe-worker indexer; do
    kubectl -n "$NAMESPACE" rollout restart "deployment/$deployment" >/dev/null 2>&1 || true
  done
fi

# The Ingress's certificate: self-signed, for localhost, valid for a year. A browser warns about it once; a real
# deployment replaces it with a certificate from a CA (see the README). The key goes to kubectl on stdin.
if missing ship-archive-tls; then
  tls_dir=$(mktemp -d)
  trap 'rm -rf "$tls_dir"' EXIT
  ( umask 077
    openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
      -keyout "$tls_dir/tls.key" -out "$tls_dir/tls.crt" \
      -subj "/CN=localhost/O=Ship Archive Lite (self-signed)" \
      -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" 2>/dev/null )
  kubectl -n "$NAMESPACE" create -f - >/dev/null <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ship-archive-tls
type: kubernetes.io/tls
data:
  tls.crt: $(base64 < "$tls_dir/tls.crt" | tr -d '\n')
  tls.key: $(base64 < "$tls_dir/tls.key" | tr -d '\n')
EOF
  rm -rf "$tls_dir"
fi

echo "Secrets are in place."
