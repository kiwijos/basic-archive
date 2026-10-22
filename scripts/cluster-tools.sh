#!/usr/bin/env bash
# Installs the cluster tooling the app depends on: an ingress controller and metrics-server.
# Versions are pinned so a fresh cluster always gets the tooling the app was tested with.
set -euo pipefail

TRAEFIK_CHART_VERSION=42.1.2
METRICS_SERVER_CHART_VERSION=3.14.0

helm repo add traefik https://traefik.github.io/charts --force-update >/dev/null
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/ --force-update >/dev/null
helm repo update >/dev/null

helm upgrade --install traefik traefik/traefik \
  --version "$TRAEFIK_CHART_VERSION" \
  --namespace traefik --create-namespace \
  --set ingressClass.enabled=true \
  --wait

# kind's kubelets use self-signed certificates, so metrics-server must skip verifying them.
helm upgrade --install metrics-server metrics-server/metrics-server \
  --version "$METRICS_SERVER_CHART_VERSION" \
  --namespace kube-system \
  --set 'args={--kubelet-insecure-tls}' \
  --wait

echo "Cluster tooling is ready."
