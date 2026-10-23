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

# The broker has one login for now, used by catalog-api and the worker; separate users per service
# are part of the security hardening. The worker acts on the API with a token of its own.
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

echo "Secrets are in place."
