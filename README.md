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
make reindex         # rebuilds the whole search index from the catalog and waits for it
```

`make deploy` runs two Jobs each time, both safe to repeat: the database migration, and `garage-init`, which prepares Garage (cluster layout, the `masters` and `derivatives` buckets, one access key per service with only the rights it needs). Garage keeps its data on a 5 Gi volume and runs as a single instance.

Uploading an Image queues an OCR job. catalog-api writes every event to an outbox table in the same transaction as the change, and each replica relays it to RabbitMQ (exchange `archive.events`, queues `ocr.requested` and `record.changed`, each with a dead-letter queue, all declared in `k8s/rabbitmq/definitions.json`). transcribe-worker takes one job at a time, reads the page with Tesseract (Swedish and English), and posts a Machine transcription back. A job is tried three times; after that the Image is marked `failed` and the message waits in `ocr.requested.dead`. Staff can read an Image again with `POST /api/catalog/images/{id}/ocr`. The message formats are JSON Schemas in `contracts/`, checked when an event is written and when a worker receives one.

The app is served on `http://localhost`. `make deploy` generates random Secrets on first run and adds any a newer slice needs; set `STAFF_NAMES="alice bob"` to choose the staff names the tokens belong to. Real Secrets are never committed, see `k8s/secrets.template.yaml` for their shape.

`http://localhost` is the public search page: free-text search with suggestions, filters and facets, highlighted results, and a verified or machine-transcribed badge on every Document. Its address holds the whole search, so reload and shared links give the same page. Every Ship, Organisation and Document has a permanent page (`/ships/{id}`, `/organisations/{id}`, `/documents/{id}`) showing names over time, relations, linked Documents, Rights and the text of each page; they are read from the search index through search-api, so no sign-in is needed and catalog-api stays private. The pages use only relative addresses, so they work behind any Ingress host. Staff sign in at `/review`. Open `http://localhost/review` and sign in with a staff token. Print yours with `kubectl -n ship-archive get secret catalog-api-secrets -o jsonpath='{.data.STAFF_TOKENS}' | base64 -d` (the format is `name=token`, comma-separated). Staff can upload a scan, wait for the machine's reading, correct it against the image, and save it as verified. The review queue lists every Document with a page nobody has verified yet, oldest first, 50 to a page. The scan is shown through a staff-only endpoint on catalog-api, because browsers cannot reach Garage; browsers cannot display TIFF, so a TIFF page offers a download instead. The staff token is kept in `sessionStorage`, so it is gone when the tab closes. For UI development, `cd services/web-ui && npm run dev` proxies `/api` to the cluster.

An image rebuilt under a tag that is already deployed is not picked up by `make deploy`, and the cluster node keeps its cached copy too. To use a local rebuild, remove the node's copy and restart: `docker exec desktop-control-plane crictl rmi docker.io/kiwijos/ship-archive-<service>:<tag>` then `kubectl -n ship-archive rollout restart deployment/<service>`. Build from the repository root, for example `docker build -f services/catalog-api/Dockerfile -t kiwijos/ship-archive-catalog-api:<tag> .`, because every image copies `contracts/`.

## Search

Every change catalog-api writes also queues a `record.changed` event. The indexer fetches that record's indexing view from catalog-api and upserts it into Meilisearch (a Document with the text of its pages and a verified flag, a Ship or Organisation with every Name it has carried); a record catalog-api no longer has is removed. Handling an event twice leaves the index as it was. search-api answers the public from Meilisearch:

```
GET /api/search/documents?q=&verified_only=&ship_type=&builder=&place=&document_type=&year_from=&year_to=&page=&page_size=
GET /api/search/subjects?q=&kind=ship|organisation&ship_type=&builder=&place=&year_from=&year_to=&page=&page_size=
GET /api/search/suggest?q=
GET /api/search/facets?scope=documents|subjects&...
```

Unverified (machine-only) text is searched by default and every Document hit carries `verified`; `verified_only=true` keeps only Documents whose every page has been corrected. A Ship is found by any name it has carried and the hit says which name matched. Highlights come back as `{text, match}` parts, never as markup. Page size is capped at 50, identical queries are cached for 5 seconds (at most 32 MB), and each client address is limited to 120 requests a minute per pod (`429` with `Retry-After`; at most 10,000 addresses are tracked). Results include `facets` and, for years, `facet_stats` with the earliest and latest year on offer. Hits link to IIIF image addresses under `/iiif/3`, which Cantaloupe will serve. `GET /api/search/documents/{id}` and `GET /api/search/subjects/{id}` return a record's whole landing page (a Document's text and Rights per page, a Ship's names, relations and Documents); the indexer stores these fields in the index too, so after upgrading from an earlier version run `make reindex` once.

`make reindex` rebuilds both indexes from catalog-api (the token that protects `/reindex` stays inside the indexer pod; the endpoint is not exposed by the Ingress). It also re-creates the indexes and their settings if Meilisearch lost them, and removes anything the catalog no longer has. Run it after losing the Meilisearch volume, or to repair events that were dead-lettered. The indexer is a single replica and a reindex holds back new events until it finishes. Index settings live in `contracts/search-index.settings.json` and are applied by the indexer at startup. See [ADR 0005](docs/adr/0005-derived-search-index-and-per-service-keys.md) for the keys: each service gets its own Meilisearch key, derived from the master key.

## Tests

```
make test-db   # throwaway Postgres (port 55432), RabbitMQ (port 56672) and Meilisearch (port 57700)
make test      # API, worker, indexer, search-api and web-ui tests; the worker tests run real Tesseract
```

## Releasing images

Push a git tag such as `v0.1.0`. CI tests, then builds the images for both architectures and pushes them to Docker Hub as `kiwijos/ship-archive-<service>:0.1.0`. Update the tag in `k8s/kustomization.yaml` to match; CI refuses to publish when the manifests pin a different version or a different Docker Hub user.
