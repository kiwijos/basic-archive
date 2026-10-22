#!/usr/bin/env bash
# Creates the app's Secrets with random values unless they already exist.
# Real secrets never enter the repository; k8s/secrets.template.yaml documents their shape.
set -euo pipefail

NAMESPACE=ship-archive
STAFF_NAMES=${STAFF_NAMES:-"kiwijos"}

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

random() { openssl rand -hex 24; }

if ! kubectl -n "$NAMESPACE" get secret postgres-credentials >/dev/null 2>&1; then
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
else
  echo "Secrets already exist; leaving them unchanged."
fi
