# Ship Archive Lite

A microservice archive for scanned ship documents. See [GLOSSARY.md](GLOSSARY.md) for the vocabulary and [docs/adr](docs/adr) for the design decisions.

## Prerequisites

- Docker Desktop with Kubernetes enabled (at least 12 GB of memory recommended)
- `kubectl`, `helm`, `uv`, `jq`, `make`
- To run the worker tests locally: Tesseract with English and Swedish data (`brew install tesseract`, plus `swe.traineddata` from `tessdata_fast` in `~/.cache/tessdata`, or your package manager's Swedish pack)

## Running on Docker Desktop Kubernetes

```
make cluster-tools   # once per cluster: Traefik and metrics-server, versions pinned
make demo            # deploy, wait for readiness, load the demo data, check it: an empty cluster to a working demo
make deploy          # creates Secrets if missing, applies everything, waits for readiness
make smoke           # exercises the API through the Ingress, Garage, and the OCR worker behind it
make ocr-parallel    # three workers read ten uploaded pages at once, each exactly once
make resilience      # restarts RabbitMQ, kills catalog-api, deletes Meilisearch, and takes Wikidata away
make e2e             # drives the web UI in a real browser: the staff review flow, and public search and landing pages
make reindex         # rebuilds the whole search index from the catalog and waits for it
make iiif-limits     # hammers image tiles through the Ingress: cache headers, 429 when excessive, recovery
make scale-test      # every service at three replicas under real traffic: no restarts, peak memory printed
make rollout-test    # rolls every service while requests go through the Ingress: none may fail, no work lost
make persistence-test  # deletes the Postgres, Garage, Meilisearch and RabbitMQ pods: no data lost
make hpa-test        # loads the archive until an autoscaler adds replicas, then waits for it to settle back
make seed            # load the demo data only (safe to run again); make demo-check reads it back
make reset           # deletes the ship-archive namespace and ALL its data, after you type its name
```

`make deploy` runs two Jobs each time, both safe to repeat: the database migration, and `garage-init`, which prepares Garage (cluster layout, the `masters` and `derivatives` buckets, one access key per service with only the rights it needs). Garage keeps its data on a 5 Gi volume and runs as a single instance.

Uploading an Image queues an OCR job. catalog-api writes every event to an outbox table in the same transaction as the change, and each replica relays it to RabbitMQ (exchange `archive.events`, queues `ocr.requested` and `record.changed`, each with a dead-letter queue, all declared in `k8s/rabbitmq/definitions.json`). transcribe-worker takes one job at a time, reads the page with Tesseract (Swedish and English), and posts a Machine transcription back. A job is tried three times; after that the Image is marked `failed` and the message waits in `ocr.requested.dead`. Staff can read an Image again with `POST /api/catalog/images/{id}/ocr`. The message formats are JSON Schemas in `contracts/`, checked when an event is written and when a worker receives one.

The app is served on `http://localhost`. `make deploy` generates random Secrets on first run and adds any a newer slice needs; set `STAFF_NAMES="alice bob"` to choose the staff names the tokens belong to. Real Secrets are never committed, see `k8s/secrets.template.yaml` for their shape.

`http://localhost` is the public search page: free-text search with suggestions, filters and facets, highlighted results, and a verified or machine-transcribed badge on every Document. Its address holds the whole search, so reload and shared links give the same page. Every Ship, Organisation and Document has a permanent page (`/ships/{id}`, `/organisations/{id}`, `/documents/{id}`) showing names over time, relations, linked Documents, Rights and the text of each page; they are read from the search index through search-api, so no sign-in is needed and catalog-api stays private. The pages use only relative addresses, so they work behind any Ingress host. Staff sign in at `/review`. Open `http://localhost/review` and sign in with a staff token. Print yours with `kubectl -n ship-archive get secret catalog-api-secrets -o jsonpath='{.data.STAFF_TOKENS}' | base64 -d` (the format is `name=token`, comma-separated). Staff can upload a scan, wait for the machine's reading, correct it against the image, and save it as verified. The review queue lists every Document with a page nobody has verified yet, oldest first, 50 to a page. The scan is shown through a staff-only endpoint on catalog-api, because browsers cannot reach Garage; browsers cannot display TIFF, so a TIFF page offers a download instead. The staff token is kept in `sessionStorage`, so it is gone when the tab closes. For UI development, `cd services/web-ui && npm run dev` proxies `/api` to the cluster.

An image rebuilt under a tag that is already deployed is not picked up by `make deploy`, and the cluster node keeps its cached copy too. To use a local rebuild, remove the node's copy and restart: `docker exec desktop-control-plane crictl rmi docker.io/kiwijos/ship-archive-<service>:<tag>` then `kubectl -n ship-archive rollout restart deployment/<service>`. Build from the repository root, for example `docker build -f services/catalog-api/Dockerfile -t kiwijos/ship-archive-catalog-api:<tag> .`, because every image copies `contracts/`.

## Demo data

`make demo` takes an empty cluster (after `make cluster-tools`) to a working demo in about a minute and can be run again: the second run changes nothing. It deploys, waits until everything is ready, loads the data with `seed/`, and then runs a read-only check that it can be found, opened and zoomed into. `make reset` empties the cluster first if you want to see it from nothing (it asks you to type the namespace name; a script without a terminal can pass `CONFIRM=ship-archive`).

The data is a fictional fleet of 4 ships and 3 organisations (one ship has three names and was sold once, a rebuilt hull links back to it), 13 Swedish documents rendered as aged scans (clean, faded, skewed and speckled; PNG, JPEG and TIFF), some verified by a person, some machine-only and one half verified, and four real, public-domain Chapman ship plates from Wikimedia Commons to zoom into. The plates are fetched when seeding (about 30 MB, checked against recorded checksums, cached in `~/.cache/archive-seed/plates`, never committed); without a network they are skipped with a message. Everything, with its licence, is listed in [seed/SOURCES.md](seed/SOURCES.md), and the design is ADR 0008. Try searching for `Nordstjärnan`, a name the barque no longer has, or open the Hagbåt plate and zoom in.

The seed measures how well the OCR (Tesseract, Swedish and English, as run by the worker on the cluster) reads the scans it knows the text of, and prints it at the end of `make seed` and `make demo-check`. Character accuracy is 1 minus the edits needed to turn the reading into the true text, divided by its length:

| Scan | Pages | Accuracy |
|---|---|---|
| clean | 5 | 100.0 % |
| faded | 4 | 94.3 % |
| skewed | 2 | 100.0 % |
| speckled | 3 | 88.3 % |
| all | 14 | 96.3 % |

These are for these particular synthetic pages, with typed text; handwriting and real damaged scans would read worse. The plates are drawings and are not measured. `make demo` ends with the check, not `make smoke`: the smoke test leaves throwaway Documents behind, which a demo should not contain, so it stays a separate command.

## Search

Every change catalog-api writes also queues a `record.changed` event. The indexer fetches that record's indexing view from catalog-api and upserts it into Meilisearch (a Document with the text of its pages and a verified flag, a Ship or Organisation with every Name it has carried); a record catalog-api no longer has is removed. Handling an event twice leaves the index as it was. search-api answers the public from Meilisearch:

```
GET /api/search/documents?q=&verified_only=&ship_type=&builder=&place=&document_type=&year_from=&year_to=&page=&page_size=
GET /api/search/subjects?q=&kind=ship|organisation&ship_type=&builder=&place=&year_from=&year_to=&page=&page_size=
GET /api/search/suggest?q=
GET /api/search/facets?scope=documents|subjects&...
```

Unverified (machine-only) text is searched by default and every Document hit carries `verified`; `verified_only=true` keeps only Documents whose every page has been corrected. A Ship is found by any name it has carried and the hit says which name matched. Highlights come back as `{text, match}` parts, never as markup. Page size is capped at 50, identical queries are cached for 5 seconds (at most 32 MB), and each client address is limited to 120 requests a minute per pod (`429` with `Retry-After`; at most 10,000 addresses are tracked). Results include `facets` and, for years, `facet_stats` with the earliest and latest year on offer. Hits link to IIIF image addresses under `/iiif/3`, which Cantaloupe will serve. `GET /api/search/documents/{id}` and `GET /api/search/subjects/{id}` return a record's whole landing page (a Document's text and Rights per page, a Ship's names, relations and Documents); the indexer stores these fields in the index too, so after upgrading from an earlier version run `make reindex` once.

`make reindex` rebuilds both indexes from catalog-api (the token that protects `/reindex` stays inside the indexer pod; the endpoint is not exposed by the Ingress). It also re-creates the indexes and their settings if Meilisearch lost them, and removes anything the catalog no longer has. Run it after losing the Meilisearch volume, or to repair events that were dead-lettered. Three indexer replicas run but only one applies changes (see Scaling), and `make reindex` goes to that one; it holds back new events until it finishes. Index settings live in `contracts/search-index.settings.json` and are applied by the indexer at startup. See [ADR 0005](docs/adr/0005-derived-search-index-and-per-service-keys.md) for the keys: each service gets its own Meilisearch key, derived from the master key.

## Scaling and persistence

| Service | Replicas | How |
|---|---|---|
| catalog-api | 2 to 4 | HorizontalPodAutoscaler on CPU (70% of the request) |
| search-api | 2 to 4 | HPA. Its answer cache and its per-address rate limit are per replica |
| transcribe-worker | 1 to 4 | HPA. Each replica takes one OCR job at a time from the queue |
| Cantaloupe | 1 to 3 | HPA. Each replica uses up to 1.5 GiB while decoding large drawings, so the ceiling is low |
| web-ui | 3 | fixed: nearly idle, nothing to scale on |
| indexer | 3 | fixed, **one working and two on standby**: the `record.changed` queue allows one active consumer, so changes are applied in order and a replica that dies hands over at once |
| Postgres, Garage, Meilisearch, RabbitMQ | 1 | StatefulSets on volumes; see below |

Every Deployment has CPU and memory requests, a memory limit, readiness and liveness probes, and a rolling update with `maxUnavailable: 0` and `maxSurge: 1`: a new pod must be ready before an old one goes. The pods behind the Ingress also wait five seconds in a `preStop` hook, so a request already on its way to a pod that is leaving is answered. `make rollout-test` rolls each service while requests go through the Ingress, and none may fail (it caught 72 failures out of 144 when web-ui was switched to `Recreate`, which is how it was checked). Nothing is scaled by hand: `replicas` is left out of the manifests of the four autoscaled Deployments so `make deploy` does not undo the autoscalers.

**Persistence.** Postgres (2 Gi), Garage (the scans, 5 Gi), Meilisearch (the index) and RabbitMQ (queues and messages) each keep their data on a PersistentVolumeClaim from their StatefulSet. `make persistence-test` deletes each pod in turn and checks through the API that nothing is missing: a Ship by id, a stored scan byte for byte, a search that still finds a Ship with no reindex, and an OCR job that waited in the queue through the broker's restart and was read afterwards. The same volume must come back each time (the test compares the claim's UID). Recorded run, 2026-10-24, all four passing:

| Pod deleted | Checked afterwards | Result |
|---|---|---|
| postgres-0 | a Ship created before is read back by id | kept |
| garage-0 | a stored scan downloaded, SHA-256 compared with the one recorded at upload | identical; the API answered 502 for 2 s after the pod reported ready |
| meilisearch-0 | the Ship is still found by search, with no reindex | kept |
| rabbitmq-0 | an OCR job waiting for a reader (workers scaled to 0), then read once a worker returned | 2 jobs queued before, 2 after, then read |

A single instance is unreachable for a moment after its pod is replaced (the Service needs a second or two to point at it again), which is why the download is retried for up to 30 s and the wait is part of the record. That blip is the cost of running these four as single instances, below.

**Why these four run as single instances, and the way out.** Each is a stateful system whose replication needs its own design, not a higher replica count; on one laptop node a second copy would add memory and no resilience. A pod that dies is replaced in seconds from its volume, and the services that use it reconnect (`make resilience` covers RabbitMQ and Meilisearch). Production paths: **Postgres** with streaming replication and automatic failover (an operator such as CloudNativePG, or a managed service) plus a connection pooler; **Meilisearch** is a single node by design, so for more capacity or availability shard or replicate with OpenSearch (the index is derived from the catalog and rebuilt by `make reindex`, so moving it is safe); **Garage** as a multi-node cluster with the replication factor raised from 1 to 3 across failure zones, or Ceph (RGW) for the same S3 API at larger scale; **RabbitMQ** as a cluster of three with quorum queues (the queues here are classic, which is fine on one node). Moving any of them is a connection-string change, since the services speak only the standard protocols: SQL, S3, AMQP and the Meilisearch API.

**Memory.** Docker Desktop is given 16 GiB (15 970 MiB visible to the node). `make scale-test` runs every service at three replicas under the smoke test, ten scans read in parallel, a tile hammering through the Ingress and 75 seconds of 24 clients pulling random tiles out of a 58-megapixel plate from inside the cluster. The archive's pods peaked at 1 951 MiB of working set (sampled every 5 s) and the whole node, Kubernetes and Traefik included, at 4 210 MiB (26%); a run before the last change measured 1 970 and 4 084 MiB. So the demonstrated peak leaves most of the allocation free.

That is a measured peak, not a proof of the worst case, and it should not be read as one. Under this load a Cantaloupe pod stayed at about 240 MiB, though a single pod was seen at 1.1 to 1.2 GiB earlier, after it first decoded the large plates, so the figure depends on what has been served. The ceiling if every pod reached its limit at the autoscalers' maximum is 14.4 GiB (catalog-api 4 x 256 MiB, search-api 4 x 256, worker 4 x 1 GiB, Cantaloupe 3 x 1.5 GiB, web-ui 3 x 128, indexer 3 x 256, the four stateful pods 2.8 GiB), and with the roughly 2 GiB the node itself uses that would not fit in 16 GiB. Reaching it needs every service at its maximum and its limit at once, which no load here came near, but it is why the maxima are low and every container has a memory limit: a runaway pod is killed and restarted rather than starving the node. The requests, which is what the scheduler promises, total about 6.3 GiB at the maxima. There are no CPU limits, on purpose: the autoscalers scale on CPU relative to the request, and a limit would throttle a pod just as it needs to burst.

**Load.** `make hpa-test` loads the archive until an autoscaler adds replicas. With 80 scans uploaded at once, transcribe-worker went from 1 to 4 replicas at 197% of its CPU request and settled back afterwards; under random tile requests from inside the cluster (past the Ingress limit, which exists to stop exactly this) Cantaloupe went from 1 to 2 at 94% and also settled back. catalog-api scaled from 2 to 4 on its own while the demo data was being seeded. search-api was not pushed past its target: its public rate limit keeps one client from loading it.

## Wikidata

Staff can match a Ship with its item on Wikidata, in two steps and never automatically: open a Ship's public page while signed in and follow "Staff: find this ship on Wikidata" (`/ships/{id}/edit`), look at the candidates and their descriptions, and press Choose. The match is stored on the Ship with its source, Wikidata identifier, label, description, the time catalog-api fetched it and who chose it; it is shown on the public Ship page and carried to search, and a wrong choice can be removed. The API is `GET /api/catalog/ships/{id}/wikidata-candidates?q=`, `PUT /api/catalog/ships/{id}/wikidata/{Q-id}` and `DELETE` on the same address. Wikidata calls time out after 4 seconds, are tried up to three times with a growing pause (timeouts, connection errors, 429 and 5xx only) and never take more than 10 seconds in all; when Wikidata is down staff get a message saying so and everything else keeps working. The address and limits can be changed with `WIKIDATA_API_URL`, `WIKIDATA_TIMEOUT_SECONDS`, `WIKIDATA_ATTEMPTS`, `WIKIDATA_BACKOFF_SECONDS` and `WIKIDATA_BUDGET_SECONDS`. The browser test and `make smoke` use the real Wikidata and are skipped with a message if the machine has no internet. After upgrading from an earlier version run `make reindex` once. See [ADR 0007](docs/adr/0007-wikidata-matches-are-chosen-by-a-person-and-fetched-by-the-server.md).

## Viewing scans

Every Document page has a deep-zoom viewer (OpenSeadragon) with labelled zoom, reset and full-screen buttons; hold `+`/`-` or use the arrow keys when the picture has focus. A Document with several pages gets a page selector, and `?page=2` in the address opens that page. The scans are served as IIIF Image API 3 by Cantaloupe at `/iiif/3/{image id}/info.json` and `/iiif/3/{image id}/{region}/{size}/0/default.jpg`, read from Garage with a key that can only read the originals; Garage itself is never exposed. Search results carry the same links (`pages[].iiif_info` and `thumbnail`). Requests for a whole large scan are refused (10-megapixel cap) and tile requests are rate limited per source address at the Ingress (shared behind Docker Desktop's network translation, see the ADR). `scripts/make_blueprint.py` draws a large CC0 test plan for trying zoom; the browser test uploads one and measures the tiles. Manual check for how zoom feels, which a script cannot judge: upload that plan (`uv run --with pillow python scripts/make_blueprint.py plan.tif`), open its Document page, and zoom with the mouse wheel, the buttons and the keys; the picture should sharpen steadily, without blank squares lingering, until the smallest labels are crisp. See [ADR 0006](docs/adr/0006-cantaloupe-serves-originals-by-image-id.md).

## Tests

```
make test-db   # throwaway Postgres (port 55432), RabbitMQ (port 56672) and Meilisearch (port 57700)
make test      # API, worker, indexer, search-api, seed and web-ui tests; the worker and seed tests run real Tesseract
```

## Releasing images

Push a git tag such as `v0.1.0`. CI tests, then builds the images for both architectures and pushes them to Docker Hub as `kiwijos/ship-archive-<service>:0.1.0`. Update the tag in `k8s/kustomization.yaml` to match; CI refuses to publish when the manifests pin a different version or a different Docker Hub user.
