#!/usr/bin/env bash
# Proves the UI is served over HTTPS by the Ingress with the self-signed certificate, and that the certificate the
# Ingress presents is the one in the cluster's Secret, not the controller's default.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

work=$(mktemp -d)
trap 'rm -f "$auth_header"; rm -rf "$work"' EXIT
HTTPS=${HTTPS_URL:-https://localhost}
host_port=${HTTPS#https://} # host or host:port, for the handshake below
[[ $host_port == *:* ]] || host_port=$host_port:443

kubectl -n "$NAMESPACE" get secret ship-archive-tls -o jsonpath='{.data.tls\.crt}' | base64 -d > "$work/secret.crt"
echo | openssl s_client -connect "$host_port" -servername "${host_port%%:*}" 2>/dev/null | openssl x509 > "$work/served.crt"

secret_fp=$(openssl x509 -in "$work/secret.crt" -noout -fingerprint -sha256)
served_fp=$(openssl x509 -in "$work/served.crt" -noout -fingerprint -sha256)
[ "$secret_fp" = "$served_fp" ] || fail "the Ingress serves a different certificate from the one in the Secret"
echo "The certificate served on :443 is the one in the ship-archive-tls Secret"
echo "  $(openssl x509 -in "$work/served.crt" -noout -subject -enddate | tr '\n' ' ')"
openssl x509 -in "$work/served.crt" -noout -ext subjectAltName | grep -q "DNS:localhost" || fail "the certificate does not name localhost"
openssl x509 -in "$work/served.crt" -noout -checkend 604800 >/dev/null || fail "the certificate expires within a week"
echo "  names localhost, valid for at least another week"

# Trusting exactly that certificate makes the whole handshake verify: name, dates and signature.
code=$(curl -s -o /dev/null -w '%{http_code}' --cacert "$work/secret.crt" "$HTTPS/")
[ "$code" = 200 ] || fail "the UI is not served over HTTPS when the certificate is trusted (HTTP $code)"
echo "The UI is served over HTTPS and the handshake verifies when that certificate is trusted: HTTP $code"

# Without it the certificate is not trusted, which is what self-signed means.
if curl -s -o /dev/null "$HTTPS/" 2>/dev/null; then fail "a browser's default trust accepted a self-signed certificate"; fi
echo "Without trusting it, verification fails, as a self-signed certificate should"

# Old protocol versions are refused.
if curl -sk -o /dev/null --tls-max 1.1 "$HTTPS/" 2>/dev/null; then fail "TLS 1.1 or older was accepted"; fi
echo "TLS 1.1 and older are refused"

image=$(api GET "/documents?source_system=seed" | jq -r '.[0].images[0].id // empty')
echo "Every public route over HTTPS:"
for path in / /api/search/subjects?q=nordstjarnan ${image:+/iiif/3/$image/info.json}; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --cacert "$work/secret.crt" "$HTTPS$path")
  [ "$code" = 200 ] || fail "$path over HTTPS answered $code"
  printf '  %-60s %s\n' "$path" "$code"
done
code=$(curl -s -o /dev/null -w '%{http_code}' --cacert "$work/secret.crt" -H @"$auth_header" "$HTTPS/api/catalog/ships?source_system=seed")
[ "$code" = 200 ] || fail "the staff API over HTTPS answered $code"
printf '  %-60s %s\n' "/api/catalog/ships (staff)" "$code"
echo "OK: HTTPS works through the Ingress with the self-signed certificate"
