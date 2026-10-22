# Ship Archive Lite

A microservice archive for scanned ship documents. See [GLOSSARY.md](GLOSSARY.md) for the vocabulary and [docs/adr](docs/adr) for the design decisions.

## Prerequisites

- Docker Desktop with Kubernetes enabled (at least 12 GB of memory recommended)
- `kubectl`, `helm`, `uv`, `jq`, `make`

## Running on Docker Desktop Kubernetes

```
make cluster-tools   # once per cluster: Traefik and metrics-server, versions pinned
make deploy          # creates Secrets if missing, applies everything, waits for readiness
make smoke           # exercises the API through the Ingress and the object storage behind it
```

`make deploy` runs two Jobs each time, both safe to repeat: the database migration, and `garage-init`, which prepares Garage (cluster layout, the `masters` and `derivatives` buckets, one access key per service with only the rights it needs). Garage keeps its data on a 5 Gi volume and runs as a single instance.

The app is served on `http://localhost`. `make deploy` generates random Secrets on first run and adds any a newer slice needs; set `STAFF_NAMES="alice bob"` to choose the staff names the tokens belong to. Real Secrets are never committed, see `k8s/secrets.template.yaml` for their shape.

An image rebuilt under a tag that is already deployed is not picked up by `make deploy`, and the cluster node keeps its cached copy too. To use a local rebuild, remove the node's copy and restart: `docker exec desktop-control-plane crictl rmi docker.io/kiwijos/ship-archive-catalog-api:<tag>` then `kubectl -n ship-archive rollout restart deployment/catalog-api`.

## Tests

```
make test-db   # throwaway Postgres on port 55432
make test      # API tests against that Postgres
```

## Releasing images

Push a git tag such as `v0.1.0`. CI tests, then builds the images for both architectures and pushes them to Docker Hub as `kiwijos/ship-archive-<service>:0.1.0`. Update the tag in `k8s/kustomization.yaml` to match; CI refuses to publish when the manifests pin a different version or a different Docker Hub user.
