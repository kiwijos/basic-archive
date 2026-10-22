#!/usr/bin/env bash
# Fails unless the manifests pin exactly the version being released, under the Docker Hub user
# that CI pushes to, so a tag can never publish images the manifests don't use.
set -euo pipefail

version=${1:?usage: check-release.sh <version> <dockerhub-user>}
user=${2:?usage: check-release.sh <version> <dockerhub-user>}
kustomization="$(dirname "$0")/../k8s/kustomization.yaml"

# Only the top-level `images:` block; generators and resources list names of their own.
images=$(awk '/^images:/ {in_images = 1; next} /^[^ #]/ {in_images = 0} in_images' "$kustomization")

pinned=$(echo "$images" | grep -E '^\s+newTag:' | awk '{print $2}' | sort -u)
if [ "$pinned" != "$version" ]; then
  echo "k8s/kustomization.yaml pins [$pinned] but the release is $version" >&2
  exit 1
fi

if echo "$images" | grep -E '^\s+- name: ' | grep -qv "name: $user/ship-archive-"; then
  echo "k8s/kustomization.yaml has an image that is not under $user/ship-archive-*" >&2
  exit 1
fi

echo "Manifests pin $version under $user."
