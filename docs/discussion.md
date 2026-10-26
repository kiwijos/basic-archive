# Benefits, challenges and scale

This document weighs what the architecture in [architecture.md](architecture.md) bought and what it cost, says where the build is thin, and explains what to pretend when presenting it, because the application is far too small to need what it was built with. The design decisions it refers to are the [ADRs](adr/0001-append-only-transcriptions-with-source.md); the security side is in [security.md](security.md).

## Benefits

**Independent scaling.** The services scale on what each one is bound by. Reading Images is CPU-heavy, so transcribe-worker grows from one replica to four when eighty Images arrive at once (measured: 1 to 4 at 197% of its CPU request), and settles back afterwards. Serving tiles is CPU- and memory-heavy, so Cantaloupe grows on its own. Search and the catalog scale separately, and a monolith would have had to scale all of it to scale any of it.

**Fault isolation.** A failure stays where it happens. A corrupt file fails one job in the worker, the Image is marked failed and the rest of the queue goes on. If RabbitMQ restarts, uploads still work and the events wait in the outbox. If Meilisearch is deleted, editing continues and `make reindex` rebuilds the index. If Wikidata is down, staff are told so within a second and nothing else stops ([resilience.sh](../scripts/resilience.sh) demonstrates each of these). A rollout of any service drops no request, which `make rollout-test` checks.

**The right store for each question.** Transactions and history live in Postgres, large files in object storage, text search in a search engine, and none of them is bent into the others' job. The public search is allowed to be wrong by a second or two in exchange for being fast, forgiving of typos and shaped around what a visitor asks.

**A disposable read side.** Because the search index is derived from the catalog ([ADR 0005](adr/0005-derived-search-index-and-per-service-keys.md)), it can be rebuilt, moved or replaced without touching the data that matters.

**A small blast radius for a mistake in one service.** With default-deny networking and a credential per service, a compromised search-api cannot reach the database, and an indexer cannot publish events ([security.md](security.md)).

## Challenges

**Operational complexity.** The honest price of all of the above. Ten long-running workloads and three Jobs, two kinds of messages, a network policy for every path, per-service credentials, six images per release and a cluster that has to be told to wait for its own database. A single application with one database would be far simpler to build, run and debug. A fault that crosses services (a message that never arrives, an index that disagrees with the catalog) takes real effort to follow, which is why the services log JSON, carry health endpoints and why there are scripts that prove behaviour rather than hoping for it. The security work shows the cost directly: every new connection needs a rule on both ends.

**Eventual consistency.** A correction is saved in Postgres at once and appears in search a second or two later, so a person can save a Transcription and not yet find it. Delivery is at least once, so every consumer must tolerate seeing a message twice, and the indexer's ordering needed its own solution ([ADR 0009](adr/0009-the-indexer-runs-as-hot-standbys.md)). The outbox ([ADR 0003](adr/0003-transactional-outbox.md)) is what keeps the lag harmless: a change can be late but cannot be lost, and nothing is announced that did not commit. The interface says honestly which text is machine-read and which is verified, rather than hiding the delay.

**The stateful services are single-instance.** Postgres, Garage, Meilisearch and RabbitMQ each run as one pod on one volume. A pod that is deleted comes back with all its data (`make persistence-test` proves it for each of the four), but it is unreachable for a moment and there is no failover or replica. This is a deliberate trade for a one-node laptop cluster, where a second copy would add memory and no resilience. Their production scaling paths are named in the [README](../README.md#scaling-and-persistence): replication with automatic failover for Postgres, a different engine (OpenSearch) for search beyond one node, a multi-node Garage or Ceph, and a RabbitMQ cluster with quorum queues.

**Files live in object storage, not in the database.** This keeps Postgres small and lets large drawings stream, but a catalog row and its file can disagree: an upload writes the file first and the row second, and a crash between them leaves an orphan file, which is harmless but never cleaned up, while a missing file would break a viewer. The two must be backed up together, and there is no backup in this build. Downloads use a short-lived signed address, so the files themselves never pass through an API.

**Handwriting accuracy.** The OCR is Tesseract, which reads typed text well and handwriting badly. On the seed's typed Swedish documents it measures 100% on clean and skewed Images, 94.3% on faded ones and 88.3% on speckled ones (96.3% overall; [README](../README.md#demo-data)), and on a real handwritten ship's letter it would be far lower, which is why every text carries a *verified* flag and why human correction is a first-class part of the design. For handwriting the production answer is a model trained for it, such as **Kraken** or the **eScriptorium** platform that is built on it, which can be trained on a collection's own hands and corrected by people. Because the worker only has to produce a Machine transcription, replacing the engine changes one service and nothing else.

**Local-path volumes survive a restart, not a reset.** On Docker Desktop the volumes are `local-path` directories inside the Kubernetes node. They survive a deleted pod, a rollout and a restart of the cluster, but **not a Kubernetes reset** (which `make reset` also is, for the namespace), because the volumes go with the cluster. That is acceptable for a demonstration and wrong for a real archive, where the volumes would be network or cloud disks with snapshots and backups. `make demo` rebuilds the demo data in about a minute, which is the answer for this build ([ADR 0008](adr/0008-the-demo-is-seeded-through-the-public-api-with-source-keys.md)).

**Memory on a laptop.** The cluster has 16 GiB. The measured peak with every service at three replicas is about 2 GiB for the archive and 4 GiB for the whole node, but if every pod reached its limit at the autoscalers' maximum the total would not fit, which is why the maxima are low and every container has a limit ([README](../README.md#scaling-and-persistence)).

**Testing across services.** The services are tested through their own HTTP interfaces against a real database, with fakes at the edge of each outside service; the proof that they work *together* is the smoke script and the browser tests run against a real cluster, and those are run by hand, not in CI.

## The application is too small to need any of this

Be direct about this when presenting it. Ship Archive Lite stores some tens of Documents and answers a handful of searches. A single Python process with a SQLite file would do all of it, with no cluster, no broker and no search engine. The architecture exists because the assignment asks for a microservice application on Kubernetes, and because building it this way shows how the pieces behave: scaling, failure, consistency and security are properties of *how the parts are connected*, and they only appear when there are parts. Say that the numbers shown (three replicas, ten uploads at once) are a demonstration of mechanisms, not a response to load.

### What to pretend

To make the design make sense, pretend the following, and say you are pretending it:

- **The public is large.** Imagine the archive is a national collection with **thousands of visitors at the same time**, most of them searching and zooming, a few of them reading the same famous ship. That is why search-api and Cantaloupe scale independently and are rate-limited, why search answers are cached for a few seconds and why tiles are cacheable.
- **Staff are many.** Imagine **hundreds of staff** reviewing text at once. That is why catalog-api is stateless and scales, why corrections are append-only rather than edits in place, and why attribution matters.
- **Scans arrive continuously.** Imagine a digitisation project delivering **thousands of Images a day**, in bursts, from a scanning line. That is why OCR is a queue with competing consumers instead of work done during the upload, why the worker scales on CPU, why a bad file is dead-lettered instead of blocking the line, and why events go through an outbox so none are lost while the broker is busy.
- **The collection is large.** Imagine **millions of Documents**. That is why the index is a separate, disposable read model and why the stores have named production scaling paths.
- **Downtime is expensive.** Imagine the archive must stay up during releases. That is why every rollout keeps a ready pod throughout and why the indexer has standbys.

Then show the mechanisms for real: ten uploads read in parallel by several workers, a load that makes an autoscaler add replicas, and a rollout with no failed request ([demo.md](demo.md) has the commands).

## What would come next

Nothing here is a surprise; the [security document](security.md#proposed-for-production) lists the production steps, and the rest follows the same pattern: an identity provider for Staff (OIDC), a handwriting engine (Kraken or eScriptorium), replicated stores, a delivery feed to national aggregators (which is also where the crew-data question in [ADR 0002](adr/0002-no-person-or-crew-data.md) returns), and a CSV import for existing catalogues, for which the source keys on every record already leave room.
