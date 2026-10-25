#!/usr/bin/env bash
# Proves that the Ingress puts nothing but the four public-facing services on the network: no stateful service has a
# Service type that reaches outside the cluster, no pod listens on the host, no store's port answers from this machine,
# and none of their HTTP interfaces shows through the Ingress.
set -euo pipefail

NAMESPACE=${NAMESPACE:-ship-archive}
BASE_URL=${BASE_URL:-http://localhost}
fail() { echo "FAILED: $*" >&2; exit 1; }

echo "What the Ingress routes to:"
backends=$(kubectl -n "$NAMESPACE" get ingress -o json | jq -r '[.items[].spec.rules[].http.paths[].backend.service.name] | unique | join(" ")')
echo "  $backends"
[ "$backends" = "cantaloupe catalog-api search-api web-ui" ] || fail "the Ingress routes to something other than the four public-facing services"

echo "How Services are exposed:"
outside=$(kubectl get svc -A -o json | jq -r '[.items[] | select(.spec.type != "ClusterIP") | "\(.metadata.namespace)/\(.metadata.name) (\(.spec.type))"] | join(", ")')
echo "  reachable from outside the cluster: $outside"
[ "$outside" = "traefik/traefik (LoadBalancer)" ] || fail "a Service other than the Ingress controller is exposed: $outside"
host=$(kubectl -n "$NAMESPACE" get pods -o json | jq '[.items[].spec | select(.hostNetwork == true or any(.containers[]; .ports[]?.hostPort != null))] | length')
[ "$host" = 0 ] || fail "$host pod(s) listen on the host"
echo "  no pod uses the host network or a host port"

lb=$(kubectl -n traefik get svc traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
listens() { # listens HOST PORT: does anything accept a connection there? (bounded; nc -w is not honoured everywhere)
  python3 -c 'import socket,sys; s=socket.socket(); s.settimeout(2)
try: s.connect((sys.argv[1], int(sys.argv[2]))); sys.exit(0)
except OSError: sys.exit(1)' "$1" "$2"
}

echo "Ports of the stores, tried from this machine (localhost and the Ingress controller's address ${lb:-none}):"
for entry in postgres:5432 rabbitmq:5672 rabbitmq-management:15672 meilisearch:7700 garage-s3:3900 garage-rpc:3901 garage-admin:3903; do
  port=${entry#*:}
  for address in localhost ${lb:+$lb}; do
    if listens "$address" "$port"; then fail "${entry%%:*} answers on $address:$port"; fi
  done
  echo "  ${entry%%:*} :$port  closed"
done

echo "Their HTTP interfaces, asked for through the Ingress (everything unknown falls through to the web UI):"
check_path() { # check_path PATH FORBIDDEN_TEXT WHAT
  local body status
  body=$(curl -s -o - -w '\n%{http_code}' "$BASE_URL$1" --max-time 10)
  status=${body##*$'\n'}
  if grep -qF -- "$2" <<< "$body"; then fail "$1 answers like $3"; fi
  printf '  %-22s %s, nothing like %s\n' "$1" "$status" "$3"
}
check_path /health '"available"' Meilisearch
check_path /indexes 'missing_authorization_header' Meilisearch
check_path /keys 'missing_authorization_header' Meilisearch
check_path /v2/GetClusterStatus 'Forbidden' "Garage's admin API"
check_path /masters '<Error>' "Garage's S3 API"
check_path /api/overview 'management_version' "RabbitMQ's management API"
echo "OK: only the four public-facing services are reachable from outside the cluster"
