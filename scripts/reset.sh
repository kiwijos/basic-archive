#!/usr/bin/env bash
# Deletes the whole ship-archive namespace, and with it every database row, stored file and search index: an empty
# cluster for `make demo` to start from. It asks first, since there is no way back.
set -euo pipefail

NAMESPACE=${NAMESPACE:-ship-archive}

if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
  echo "There is no namespace $NAMESPACE: nothing to reset."
  exit 0
fi

echo "This deletes the namespace $NAMESPACE and ALL the data in it (database, stored scans, search index, secrets)."
if [ -t 0 ]; then
  read -r -p "Type the namespace name to confirm: " answer
else
  answer=${CONFIRM:-}
fi
[ "$answer" = "$NAMESPACE" ] || { echo "Not confirmed. Nothing was deleted." >&2; exit 1; }

kubectl delete namespace "$NAMESPACE" --wait=true --timeout=300s
echo "Reset. Run 'make demo' to bring it up again with the demo data."
