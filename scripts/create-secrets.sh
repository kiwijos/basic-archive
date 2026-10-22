#!/usr/bin/env bash
# Creates each app Secret with random values unless it already exists, so it is safe to run
# again and only adds what a newer slice needs.
# Real secrets never enter the repository; k8s/secrets.template.yaml documents their shape.
set -euo pipefail

NAMESPACE=ship-archive
STAFF_NAMES=${STAFF_NAMES:-"kiwijos"}

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

random() { openssl rand -hex 24; }
missing() { ! kubectl -n "$NAMESPACE" get secret "$1" >/dev/null 2>&1; }
# Garage access keys are "GK" and 24 hex characters, with a 64 hex character secret.
create_s3_secret() {
  kubectl -n "$NAMESPACE" create secret generic "$1" \
    --from-literal=S3_ACCESS_KEY_ID="GK$(openssl rand -hex 12)" \
    --from-literal=S3_SECRET_ACCESS_KEY="$(openssl rand -hex 32)"
}

if missing postgres-credentials; then
  POSTGRES_PASSWORD=$(random)
  kubectl -n "$NAMESPACE" create secret generic postgres-credentials \
    --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASSWORD"
  DATABASE_URL="postgresql+psycopg://postgres:${POSTGRES_PASSWORD}@postgres:5432/archive"

  STAFF_TOKENS=""
  for name in $STAFF_NAMES; do
    STAFF_TOKENS="${STAFF_TOKENS:+$STAFF_TOKENS,}${name}=$(random)"
  done
  kubectl -n "$NAMESPACE" create secret generic catalog-api-secrets \
    --from-literal=DATABASE_URL="$DATABASE_URL" \
    --from-literal=STAFF_TOKENS="$STAFF_TOKENS"
fi

if missing garage-secrets; then
  kubectl -n "$NAMESPACE" create secret generic garage-secrets \
    --from-literal=rpc-secret="$(openssl rand -hex 32)" \
    --from-literal=admin-token="$(random)"
fi

# One key per service, so each can be given only the access it needs.
missing catalog-api-s3 && create_s3_secret catalog-api-s3
missing cantaloupe-s3 && create_s3_secret cantaloupe-s3

echo "Secrets are in place."
