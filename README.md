# Ship Archive Lite

A microservice archive for scanned ship documents. See [GLOSSARY.md](GLOSSARY.md) for the vocabulary and [docs/adr](docs/adr) for the design decisions.

## Prerequisites

- Docker Desktop with Kubernetes enabled (at least 12 GB of memory recommended)
- `kubectl`, `helm`, `uv`, `jq`, `make`
- To run the worker tests locally: Tesseract with English and Swedish data (`brew install tesseract`, plus `swe.traineddata` from `tessdata_fast` in `~/.cache/tessdata`, or your package manager's Swedish pack)

## Running on Docker Desktop Kubernetes

```
make cluster-tools   # once per cluster: Traefik and metrics-server, versions pinned
make deploy          # creates Secrets if missing, applies everything, waits for readiness
make smoke           # exercises the API through the Ingress, Garage, and the OCR worker behind it
make ocr-parallel    # three workers read ten uploaded pages at once, each exactly once
make resilience      # restarts RabbitMQ and kills catalog-api at awkward moments
make e2e             # drives the web UI in a real browser: sign in, upload, correct, leave the queue
```

`make deploy` runs two Jobs each time, both safe to repeat: the database migration, and `garage-init`, which prepares Garage (cluster layout, the `masters` and `derivatives` buckets, one access key per service with only the rights it needs). Garage keeps its data on a 5 Gi volume and runs as a single instance.

Uploading an Image queues an OCR job. catalog-api writes every event to an outbox table in the same transaction as the change, and each replica relays it to RabbitMQ (exchange `archive.events`, queues `ocr.requested` and `record.changed`, each with a dead-letter queue, all declared in `k8s/rabbitmq/definitions.json`). transcribe-worker takes one job at a time, reads the page with Tesseract (Swedish and English), and posts a Machine transcription back. A job is tried three times; after that the Image is marked `failed` and the message waits in `ocr.requested.dead`. Staff can read an Image again with `POST /api/catalog/images/{id}/ocr`. The message formats are JSON Schemas in `contracts/`, checked when an event is written and when a worker receives one.

The app is served on `http://localhost`. `make deploy` generates random Secrets on first run and adds any a newer slice needs; set `STAFF_NAMES="alice bob"` to choose the staff names the tokens belong to. Real Secrets are never committed, see `k8s/secrets.template.yaml` for their shape.

Open `http://localhost` and sign in with a staff token. Print yours with `kubectl -n ship-archive get secret catalog-api-secrets -o jsonpath='{.data.STAFF_TOKENS}' | base64 -d` (the format is `name=token`, comma-separated). Staff can upload a scan, wait for the machine's reading, correct it against the image, and save it as verified. The review queue lists every Document with a page nobody has verified yet, oldest first, 50 to a page. The scan is shown through a staff-only endpoint on catalog-api, because browsers cannot reach Garage; browsers cannot display TIFF, so a TIFF page offers a download instead. The staff token is kept in `sessionStorage`, so it is gone when the tab closes. For UI development, `cd services/web-ui && npm run dev` proxies `/api` to the cluster.

An image rebuilt under a tag that is already deployed is not picked up by `make deploy`, and the cluster node keeps its cached copy too. To use a local rebuild, remove the node's copy and restart: `docker exec desktop-control-plane crictl rmi docker.io/kiwijos/ship-archive-<service>:<tag>` then `kubectl -n ship-archive rollout restart deployment/<service>`. Build from the repository root, for example `docker build -f services/catalog-api/Dockerfile -t kiwijos/ship-archive-catalog-api:<tag> .`, because every image copies `contracts/`.

## Tests

```
make test-db   # throwaway Postgres (port 55432) and RabbitMQ (port 56672)
make test      # API, worker and web-ui unit tests; the worker tests run real Tesseract
```

## Releasing images

Push a git tag such as `v0.1.0`. CI tests, then builds the images for both architectures and pushes them to Docker Hub as `kiwijos/ship-archive-<service>:0.1.0`. Update the tag in `k8s/kustomization.yaml` to match; CI refuses to publish when the manifests pin a different version or a different Docker Hub user.
