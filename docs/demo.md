# Demo script

This is the script for showing Ship Archive Lite from an empty cluster to every acceptance criterion of the [spec](https://github.com/kiwijos/basic-archive/issues/1) and of the assignment. Every command is typed exactly as written, every click names the button as it appears on the screen, and under each step is what you should see. It takes about 40 minutes without pauses, and every step can be repeated. The design being shown is in [architecture.md](architecture.md); say what to pretend about the scale with the note in [discussion.md](discussion.md#what-to-pretend), and be direct that the demonstrations show mechanisms and not load.

| Step | Shows | Takes |
|---|---|---|
| [A1](#a1-one-command-brings-the-system-up) | One command brings the system up and seeds it | 1 min |
| [A2](#a2-ten-uploads-are-read-in-parallel) | Ten uploads are read in parallel by several workers | 1 min |
| [A3](#a3-a-verified-correction-appears-in-public-search-within-seconds) | A verified correction appears in public search within seconds | 4 min |
| [A4](#a4-a-misspelled-name-or-an-old-name-finds-the-ship) | A misspelled or old name finds the right ship | 2 min |
| [A5](#a5-a-blueprint-zooms-smoothly) | A blueprint zooms smoothly | 2 min |
| [A6](#a6-delete-the-postgres-pod-and-lose-nothing) | Deleting the Postgres pod loses no data | 3 min |
| [A7](#a7-a-reindex-rebuilds-the-search-index-from-nothing) | A reindex rebuilds the search index from nothing | 3 min |
| [A8](#a8-every-service-runs-at-three-replicas-without-errors) | Every service the project builds or serves runs at three replicas | 4 min |
| [A9](#a9-a-direct-connection-from-search-api-to-postgres-is-blocked) | A direct connection from search-api to Postgres is blocked | 2 min |
| [R1](#r1-at-least-two-self-created-services-with-rest-apis) to [R6](#r6-reachable-from-outside-the-cluster) | The assignment's own criteria | 15 min |
| [S1](#s1-secrets-containers-and-images) | Secrets, containers and images | 2 min |

## Before you start

The manifests pin an exact version of every image (`k8s/kustomization.yaml`), and the cluster pulls them from Docker Hub, so the release they name must have been published: CI does that when the version is tagged. You need Docker Desktop with Kubernetes enabled (a kind cluster, 16 GB), and `kubectl`, `helm`, `uv`, `jq` and `make` on the path ([README](../README.md#prerequisites)). Open two terminals in the repository, **A** for commands and **B** for watching, and a browser.

Start from nothing. On a cluster that has run the system before, wipe it (it asks you to type `ship-archive`); on a cluster that has never had the cluster tooling, install it once (a few minutes):

```
make reset
make cluster-tools
```

Set up what the steps share, once per terminal (the staff token goes into a private file, never onto a command line):

```
export NS=ship-archive
(umask 077; printf 'Authorization: Bearer %s' "$(kubectl -n $NS get secret catalog-api-secrets -o jsonpath='{.data.STAFF_TOKENS}' | base64 -d | cut -d, -f1 | cut -d= -f2)" > /tmp/demo-auth)
```

The Secrets do not exist yet on a fresh cluster, so run this after A1. To sign in on a web page you need the token itself; copy it with `cut -d' ' -f3 /tmp/demo-auth | pbcopy` (macOS) and paste it into the page.

## A1 One command brings the system up

*Shows:* "On a fresh cluster with tooling installed, one command brings the system up, waits for readiness and seeds it."

In terminal B, watch the pods appear:

```
kubectl get pods -n ship-archive -w
```

In terminal A, the one command:

```
make demo
```

**You should see**, in about a minute: the Secrets created, every workload reported as rolled out, then the seed (counts of what was made: 4 ships, 3 organisations, 13 Documents with 14 Images, 3 plate documents), the OCR accuracy table, and a demo check that ends with eight lines starting `ok` and no `FAIL`. Press Ctrl-C in terminal B. Then run the shared setup from [Before you start](#before-you-start) in terminal A.

Run it again to show that the seed is safe to repeat:

```
make demo
```

**You should see** every counter read `0 made`, and the same eight `ok` lines.

Now open **https://localhost** in the browser. The certificate is self-signed, so the browser warns once: accept it (R6 explains why). You see the public search page.

## A2 Ten uploads are read in parallel

*Shows:* "Ten uploads are all transcribed, visibly in parallel with several worker replicas" (competing consumers).

In terminal B, watch the worker pods:

```
kubectl -n ship-archive get pods -l app=transcribe-worker -w
```

In terminal A:

```
make ocr-parallel
```

**You should see** in terminal B two more workers appear and become `Running` within seconds (and disappear again when the script puts the deployment back). In terminal A: three workers made ready, ten Images uploaded at once, all ten reaching `ocr_done`, each with exactly one Machine transcription, and a count of how many each worker read, taken from their logs (for example 3, 4 and 3), ending `OK: 10 Images read by 3 workers in parallel, each exactly once`. Press Ctrl-C in terminal B.

## A3 A verified correction appears in public search within seconds

*Shows:* "A verified correction appears in public search within seconds" (eventual consistency, the outbox and the indexer).

In terminal A, make an Image to upload (a typed Swedish test Image) and copy the staff token:

```
uv run --quiet --no-project --with pillow==11.3.0 python scripts/make_scan.py /tmp/demo-letter.png demo1
cut -d' ' -f3 /tmp/demo-auth | pbcopy
```

In the browser:

1. Open **https://localhost/review**. In **Staff token**, paste the token and click **Sign in**. You see "Signed in as" and your name.
2. Click **Upload**. For **Scan**, choose `/tmp/demo-letter.png`. Fill **Title** with `Demo letter`, **Document type** with `letter`, **Date as written** with `ca 1891`. Click **Upload**.
3. The review screen opens with the Image on the left and the text on the right. After a few seconds the text under **Text on the page** appears: that is the Machine transcription, and the badge says it is not verified. (If it is empty, wait a moment and reload.)

In terminal B, start a timer that waits for the word to become searchable as verified, and leave it running:

```
time (until curl -skG https://localhost/api/search/documents --data-urlencode q=zebrafink --data-urlencode "_=$RANDOM" | jq -e '.hits[0].verified == true' >/dev/null; do sleep 0.5; done)
```

Back in the browser:

4. Click into **Text on the page**, go to the end of the text and add ` zebrafink`. Click **Save as verified**. You see "Saved. This page is now verified." and the Image leaves the review queue.

**You should see** terminal B finish within a few seconds (typically about a second), with `real` well under ten. Then open a private window at **https://localhost**, type `zebrafink` in **Search the archive** and click **Search**: the Document is found, `zebrafink` is highlighted, and its badge says it is verified by a person. Back in the review screen, click **History of this page's text**: the machine reading is still there beside your correction, with who and when (nothing is overwritten, [ADR 0001](adr/0001-append-only-transcriptions-with-source.md)).

## A4 A misspelled name or an old name finds the ship

*Shows:* "A misspelled ship or old-name query returns the right result."

In the browser, on **https://localhost**:

1. Click **Ships and organisations**. In **Search the archive** type `Nordstjarnan` (with an a, no dots) and click **Search**.
2. The result is the ship **Havsörnen**, and it says it matched the former name **Nordstjärnan** (the interface's own wording): the query was misspelled, and the Name is one the ship no longer has. Click the result.
3. The Ship page lists the ship's three names over time (Nordstjärnan, Sofia, Havsörnen), its builder and owners (Organisations), the sale in 1903, and a link to the Documents that are about it. The name that matched your search is marked.
4. Click **← Back to your search**: your search is as you left it, from its address.

Try `Havsornen` and `Sofia` as well: all three find the same ship. Then click the Ship **Älvdrottningen**: it is a new ship, rebuilt from Havsörnen's hull in 1933, and the two pages link to each other.

## A5 A blueprint zooms smoothly

*Shows:* "A blueprint zooms smoothly."

In the browser:

1. Clear the search, type `Hagbåt` and click **Search**. Click the result *Hagbåt: planscherna VIII och IX (Chapman, 1768)*: a public-domain drawing, about 9000 by 6500 pixels, with two sheets.
2. The viewer opens with the whole sheet. Open the browser's developer tools on the **Network** tab and filter on `iiif`.
3. Click **Zoom in** six times, or scroll. The picture sharpens in place as finer tiles arrive. In the Network tab each tile is a small request such as `.../512,512,.../default.jpg`, answered with `200` in milliseconds. Click **Reset view**, then **Page 2** to see the second sheet.

In terminal A, the same through the command line:

```
IMAGE=$(curl -skG https://localhost/api/search/documents --data-urlencode q=Hagbåt | jq -r '.hits[0].pages[0].id')
curl -sk "https://localhost/iiif/3/$IMAGE/info.json" | jq '{protocol, width, height}'
```

**You should see** `"width": 8928` and `"height": 6383`. The image server cut a 57-megapixel drawing into tiles on demand, from the original in object storage ([ADR 0006](adr/0006-cantaloupe-serves-originals-by-image-id.md)).

## A6 Delete the Postgres pod and lose nothing

*Shows:* "Deleting the Postgres pod loses no data."

In terminal A, count what is in the catalog, delete the database pod and count again:

```
curl -sk -H @/tmp/demo-auth "https://localhost/api/catalog/ships?source_system=seed" | jq length
kubectl -n $NS delete pod postgres-0
kubectl -n $NS wait --for=condition=Ready pod/postgres-0 --timeout=180s
curl -sk -H @/tmp/demo-auth "https://localhost/api/catalog/ships?source_system=seed" | jq length
```

**You should see** `4` before and `4` after. (For a moment after the pod is replaced the API answers with an error; repeat the last command if it does.) Reload the Ship page for Havsörnen in the browser: it is all still there, because the data is on a volume that outlives the pod.

To do it for all four stateful services, with a check of the data each time:

```
make persistence-test
```

**You should see** four lines, one each for `postgres-0`, `garage-0` (the stored Image is downloaded and its SHA-256 is unchanged), `meilisearch-0` and `rabbitmq-0` (a job that was waiting in the queue is still there and is read afterwards), ending `OK: no data was lost`.

## A7 A reindex rebuilds the search index from nothing

*Shows:* "A reindex rebuilds the index from scratch" (the index is derived and disposable, [ADR 0005](adr/0005-derived-search-index-and-per-service-keys.md)).

First show that search works, then destroy the index inside Meilisearch. The master key is read from the pod's own environment and handed to `curl` as a header on its standard input, so it is never in a process's arguments and never leaves the pod:

```
curl -skG https://localhost/api/search/subjects --data-urlencode q=Havsörnen | jq '.hits | length'
kubectl -n $NS exec meilisearch-0 -- sh -c 'for index in documents subjects; do printf "Authorization: Bearer %s" "$MEILI_MASTER_KEY" | curl -s -X DELETE -H @- http://localhost:7700/indexes/$index; done'
sleep 3
curl -skG https://localhost/api/search/subjects --data-urlencode q=Havsörnen --data-urlencode "_=$RANDOM" | jq '(.hits | length), (.error // .detail)'
```

**You should see** a hit before (Meilisearch prints two task acknowledgements for the deletion), and after it `0` and the message `Search is not available right now`: the public search is empty, while the catalog in Postgres is untouched. Now rebuild it:

```
make reindex
```

**You should see** a line that names the active indexer, then `{"state": "done", "indexed": ..., "removed": 0, "error": null}` with the number of Documents and Subjects indexed. Search again, and Havsörnen is back, as is everything else; reload **https://localhost** and search for `zebrafink`.

## A8 Every service runs at three replicas without errors

*Shows:* "Each custom service runs at three replicas without errors" and the autoscalers.

```
kubectl -n $NS get hpa
make scale-test
```

**You should see** the four autoscalers (catalog-api, search-api, transcribe-worker, Cantaloupe) with their minimum and maximum replicas and current CPU. `make scale-test` raises each autoscaler's minimum to three, waits until all six services (the five self-created ones, including web-ui and the indexer, and Cantaloupe) show `3/3`, runs the smoke test, ten uploads and a tile hammering against them, and ends with the peak memory of the pods and of the whole node out of the 16 GiB, and `OK: three replicas of every service, no restarts, nothing unready, no out-of-memory kills, no unhandled exceptions`. It puts the minimums back afterwards. This takes about three minutes.

## A9 A direct connection from search-api to Postgres is blocked

*Shows:* "A direct connection from search-api to Postgres is demonstrably blocked", with the allowed paths still working.

A hand-made attempt from inside the search-api pod, to Postgres (denied) and then to Meilisearch (allowed):

```
kubectl -n $NS exec deploy/search-api -- python -c "import socket; s=socket.socket(); s.settimeout(4); s.connect(('postgres', 5432))"
kubectl -n $NS exec deploy/search-api -- python -c "import socket; s=socket.socket(); s.settimeout(4); s.connect(('meilisearch', 7700)); print('connected to meilisearch')"
```

**You should see** the first fail with `TimeoutError: timed out` (the packets are dropped, not refused) and the second print `connected to meilisearch`. Then the whole picture:

```
make netpol-test
```

**You should see** a table of every pod against every internal port, each cell `ok`, ending `search-api -> postgres:5432 is blocked` and `OK: 16 allowed paths open and every other connection ... is blocked`. Show the policy that makes it so: `kubectl -n $NS get networkpolicy`, and the plain-language table of paths in the [README](../README.md#security).

## R1 At least two self-created services with REST APIs

*Shows:* "At least two self-created services that expose REST APIs."

In the browser open **https://localhost/api/catalog/docs** (catalog-api, the write side) and **https://localhost/api/search/docs** (search-api, the read side): both describe themselves with OpenAPI and can be tried from the page. From a terminal:

```
curl -sk https://localhost/api/search/openapi.json | jq '.paths | keys'
curl -sk https://localhost/api/catalog/openapi.json | jq '.paths | keys | length'
```

A third and fourth REST surface exist behind the scenes: the indexer's reindex endpoint and the health endpoints of all five services ([architecture.md](architecture.md#interfaces)).

## R2 Services scale independently

*Shows:* "Services that scale independently."

Different services grow on different load, with no change to the others. Run the autoscaler test, which loads two of them differently and prints each one's replicas at the start and at the peak:

```
make hpa-test
```

**You should see**, over about eight minutes (it first waits for every autoscaler to be at its minimum), lines of `catalog-api=… search-api=… transcribe-worker=… cantaloupe=…` with their CPU, a count of the tiles that were answered (thousands), then the replicas at the start and at the peak: in the recorded run `transcribe-worker 1 -> 2` and `cantaloupe 1 -> 3`, with search-api unchanged (its public rate limit keeps one client from loading it) and catalog-api at most a little higher. The numbers differ from run to run; what matters is that more than one autoscaler adds replicas under load, independently of the others, and that they settle back. To show the manual side, in terminal A: `kubectl -n $NS get deploy` before and after A2 (the worker deployment grew and shrank; the others did not).

## R3 The database survives restarts

*Shows:* "A database that survives restarts."

This is [A6]. To go further, restart all four stateful services at once, which is what a cluster restart does to them, and check that the data is all still there:

```
kubectl -n $NS rollout restart statefulset
for s in postgres garage meilisearch rabbitmq; do kubectl -n $NS rollout status statefulset/$s --timeout=300s; done
curl -sk -H @/tmp/demo-auth "https://localhost/api/catalog/ships?source_system=seed" | jq length
```

**You should see** each StatefulSet roll out in turn and `4` again (repeat the last command if the API still answers with an error for a moment). Reload the Ship page for Havsörnen: nothing is missing. Say plainly that the volumes survive a deleted pod, a restart and a rollout but **not a Kubernetes reset** ([discussion.md](discussion.md#challenges)), which is why `make demo` rebuilds the demo in a minute.

## R4 Images on Docker Hub

*Shows:* "Images pushed to Docker Hub."

Every pod runs an image published to Docker Hub, pinned to an exact version. Show the versions the cluster runs and that they are the published ones:

```
VERSION=$(grep -m1 newTag k8s/kustomization.yaml | awk '{print $2}'); echo "release $VERSION"
kubectl -n $NS get pods -o jsonpath='{range .items[*]}{.spec.containers[0].image}{"\n"}{end}' | sort -u | grep kiwijos
for s in catalog-api search-api indexer transcribe-worker web-ui cantaloupe; do
  pod=$(kubectl -n $NS get pod -l app=$s --field-selector=status.phase=Running -o jsonpath='{.items[0].status.containerStatuses[0].imageID}')
  reg=$(docker buildx imagetools inspect kiwijos/ship-archive-$s:$VERSION --format '{{.Manifest.Digest}}')
  [ "${pod##*@}" = "$reg" ] && echo "$s MATCH ${reg:7:12}" || echo "$s DIFFERENT"
done
```

**You should see** the six images `kiwijos/ship-archive-<service>:<version>` and `MATCH` six times: the digest the pod is running is the digest on Docker Hub. The images are built and pushed by GitHub Actions when a version is tagged, after the tests pass, for both architectures ([README](../README.md#releasing-images)), and the manifests never use `latest`.

## R5 An external REST API consumed programmatically

*Shows:* "At least one external REST API consumed programmatically": Wikidata.

In terminal A, make a ship worth finding (the seeded ones are invented, and Wikidata has nothing for them):

```
curl -sk -X POST -H @/tmp/demo-auth -H 'Content-Type: application/json' -d '{"name":"Vasa","ship_type":"warship"}' https://localhost/api/catalog/ships | jq -r '"https://localhost/ships/" + .id + "/edit"'
```

Open the address it prints (you are still signed in; otherwise sign in at **/review** first). In the browser:

1. The page says **No Wikidata match chosen yet**, and **Name to look for** is filled with `Vasa`. Click **Find on Wikidata**.
2. A list of possible matches for "Vasa" appears, each with Wikidata's description, and each with **Open on Wikidata**. When this was written the first hits were not the ship (a city, a family; Wikidata's results change, so yours may differ): this is why a person chooses, never the system ([ADR 0007](adr/0007-wikidata-matches-are-chosen-by-a-person-and-fetched-by-the-server.md)).
3. Click the button **Choose Vasa (Q…) for this ship** on the entry that describes the 17th-century warship. You see "Stored Vasa (Q…) from Wikidata."
4. Open the Ship's public page (**https://localhost/ships/…**, in a private window): a section **Elsewhere** links to the item, and the name, description and retrieval time are the ones Wikidata gave when the server asked.

To show that an outage does not break editing, in terminal A run `make resilience`: its last scenario points catalog-api at an address where Wikidata is not, and edits the ship anyway, with a clear message within a second.

## R6 Reachable from outside the cluster

*Shows:* "Reachable from outside the cluster", and that nothing else is.

Everything above was through one address, **https://localhost**, served by the Ingress controller (Traefik) with TLS. Show how it is exposed and that only the four public services are:

```
kubectl get ingress -n $NS
make exposure-test
make tls-test
```

**You should see** the Ingress with its routes, then `OK: only the four public-facing services are reachable from outside the cluster` (Postgres, RabbitMQ, Meilisearch and Garage have no route and no open port) and `OK: HTTPS works through the Ingress with the self-signed certificate`.

## S1 Secrets, containers and images

*Shows:* the rest of the spec's Security list: "secrets committed only as templates", "non-root containers with dropped capabilities and read-only root filesystems", "trivy scans recorded".

```
make secrets-scan
make audit
```

**You should see** `OK: no secret is in the repository, or ever was` after it searched for every live secret value in the working tree and in all of git's history, and `13 workloads audited, 0 finding(s), 2 stated exception(s)`: every container in the manifests runs non-root with every capability dropped, a read-only root filesystem and no Kubernetes API token, apart from one stated and explained exception ([security.md](security.md#threats-and-mitigations)). The image scans are recorded in [security/trivy.md](security/trivy.md), with every accepted finding explained; `make trivy VERSION=<release>` rescans the images and takes a few minutes.

## Afterwards

To run the proofs that this document did not (the full smoke test, the browser tests, the rollout and secret checks):

```
make smoke
make e2e
make rollout-test
make security-test
```

And to leave nothing behind: `make reset`.

## If a step does not go as written

| What you see | Why, and what to do |
|---|---|
| The browser warns about the certificate | It is self-signed (R6). Accept it, or use `http://localhost`, which is also served |
| The review screen has no text | The worker has not finished; wait a few seconds and reload. `kubectl -n ship-archive get pods -l app=transcribe-worker` should show it running |
| A search does not find a new word yet | The index follows the catalog by a second or two; the answer is also cached for five seconds. Search again |
| `make demo` stops at the plates | No network to Wikimedia: the plates are skipped with a message and everything else works. Run `make seed` when online |
| Pods are Pending | Docker Desktop has too little memory; give it 12 GB or more |
| A command run inside a pod times out just after you scaled or rolled something | A pod that was just created is learned by the policy enforcer a moment later ([security.md](security.md#known-limitations)). Wait ten seconds and repeat |
| A request stalls for a few seconds during a rollout or a load | A known limit of the policy enforcer on Docker Desktop ([security.md](security.md#known-limitations)). Repeat the step |
