# Security

This is the security design of Ship Archive Lite: what is protected, the threats considered, what was done about each, what is proposed for production and what is knowingly left open. The decisions behind it are in [ADR 0010](adr/0010-security-deny-by-default-with-proofs.md); the numbers and the recorded runs are in the [README's security section](../README.md#security). The architecture it protects is in [architecture.md](architecture.md).

Every claim marked *proved* has a check that fails when it stops being true, and `make security-test` runs them against the cluster (the static ones also run in CI). Nothing here is claimed that is not either checked or listed under [Known limitations](#known-limitations).

## What is protected, and where the boundaries are

- **The catalog** (Documents, Transcriptions, Ships, Organisations): only Staff change it, and nothing is ever overwritten, so a bad edit can be understood and undone.
- **The Images** in object storage: public by design to read through the viewer, changeable only by catalog-api.
- **The credentials** that let one service act on another.
- **Availability**: a visitor or a script must not be able to take the search or the viewer down.

There are three trust boundaries. The first is the Ingress: everything outside the cluster is untrusted, and only four services are reachable from it. The second is between services: each one is treated as something that may be compromised, so none can reach more than it needs. The third is uploaded files, which are untrusted input that a native library (Tesseract, libtiff) will parse.

## Threats and mitigations

| Threat | Mitigation done | Evidence or what is proposed |
|---|---|---|
| Someone writes to the catalog without being Staff | Every write needs a named bearer token; a missing or wrong token is a 401. Each token's name is recorded as the author of what it changes | Authentication tests across the endpoints; static tokens are a known limitation, OIDC is proposed below |
| A service's token is used for something it should not do | The worker and the indexer hold service tokens that reach only their own endpoints, and a staff token cannot post a Machine transcription | *Proved* by `make credentials-test`: the worker's and indexer's tokens get 401 on the staff endpoints |
| A staff token is stolen | The browser keeps it in `sessionStorage` (gone when the tab closes) and sends it only to the API; tokens live in a Secret and are rotated by replacing it | Short-lived tokens through OIDC are proposed |
| A malicious or broken file is uploaded | The type is checked from the file's own bytes, never its name, and only TIFF, JPEG and PNG are accepted; a size limit (100 MB) applies; the worker refuses an Image above 60 million pixels and gives each one 90 seconds; files are served back only as images with `nosniff` | Upload tests; the worker is contained (below) because the native libraries that parse a file are the weakest part |
| Injection: SQL, or script in a name or a Transcription | Queries are parameterised through SQLAlchemy; every body is validated by Pydantic; search highlights come back as data (`{"text", "match"}` pieces), never markup, so nothing from the archive can inject HTML; the UI's Content-Security-Policy allows only its own scripts | Tests of the highlighting and validation; CSP in `services/web-ui/nginx.conf` |
| A compromised service moves sideways | Default-deny NetworkPolicies allow only the agreed paths; every credential is separate; every container runs non-root with all capabilities dropped, a read-only filesystem, a seccomp profile and no Kubernetes API token | *Proved* by `make netpol-test` (16 allowed paths open, every other of 11 sources by 11 destinations blocked) and `make audit` |
| The public search service reaches the database | search-api has no database credential and no network path to Postgres; its Meilisearch key can only search | *Proved*: a direct connection from search-api to Postgres times out; `make credentials-test` shows the key cannot write |
| A credential from one service is used for another | A broker login per service, each with only the permissions that service uses; a search-only and an index-only Meilisearch key; a read-write and a read-only S3 key; the Meilisearch master key held only by Meilisearch and its init Job ([ADR 0005](adr/0005-derived-search-index-and-per-service-keys.md)) | *Proved* by `make credentials-test` (33 checks) and by the audit, which fails if a workload reads a Secret that is not its own |
| A secret reaches the repository | Only templates with placeholders are committed; the audit fails on anything else in `k8s/` | *Proved* by `make secrets-scan`: every live secret value, searched for in all history, found nowhere (and a planted one was found) |
| The databases and stores are reachable from outside | They have no route in the Ingress and no Service that leaves the cluster | *Proved* by `make exposure-test` |
| Traffic is read in transit | TLS at the Ingress with a certificate for `localhost` (self-signed locally) | *Proved* by `make tls-test`; traffic inside the cluster is not encrypted (a limitation); a CA certificate through cert-manager is described in [cloud-tls.md](security/cloud-tls.md) |
| A visitor or script overloads the service | A per-address limit and a capped page size on search, a short answer cache, a per-address rate limit on tiles at the Ingress, an upload size limit, memory limits and autoscaling on every service, and bounded retries and a total budget on every call to Wikidata | `make iiif-limits`, `make hpa-test`; the search limit is per replica, a known limitation |
| A hostile or slow outside service (Wikidata) | Timeouts, bounded retries, a total budget, a 502/504 with a plain message for staff only; the server fetches only a fixed host and validates the identifier, and a person chooses every match | Tests against a fake that can be slow or send broken bodies; `make resilience` |
| A wrong or malicious edit is hidden | Transcriptions are append-only and record who and when and which engine; deletes are soft; the Verified flag is derived from the rows, never set by hand ([ADR 0001](adr/0001-append-only-transcriptions-with-source.md)) | Tests; the history is visible to Staff |
| A vulnerable dependency or image | Versions are pinned exactly; every custom image is scanned with trivy and the results recorded; Pillow, FastAPI/Starlette and the base images were upgraded after the first scan | [trivy.md](security/trivy.md), regenerated by `make trivy`, which fails on a new fixable finding |
| The container is escaped | Non-root, no capabilities, no privilege escalation, read-only root, seccomp, and the Kubernetes API token not mounted | `make audit`; two stated exceptions, each with its reason |
| Personal data is published | None is held: the data is synthetic or public domain, and no person or crew record exists | [ADR 0002](adr/0002-no-person-or-crew-data.md) and the next section |

## Why there is no crew data: GDPR and CC0

The brief imagined records of the people who sailed on the ships. They are not built, and the reason is a conflict between two obligations.

**The metadata is published as CC0.** Metadata passed on to national and European aggregators (K-samsök, Europeana) must be CC0, which is a public-domain dedication and **cannot be taken back**. Once a record is published that way, it is copied beyond anyone's control.

**Records about people are governed by the GDPR.** Information about an identifiable living person is personal data: it needs a lawful basis, it can be corrected or erased on request, and it may be held no longer than needed. A record about a crew member who may still be alive, or whose close relatives are, cannot be both erasable on request and irrevocably in the public domain. Without a legal review of that conflict, publishing such data would be a mistake that cannot be reversed.

Two consequences follow. First, even synthetic persons would add a GDPR discussion and mapping work and help no assignment criterion, so the build contains none: its data is invented ships and organisations, plus public-domain drawings (see [seed/SOURCES.md](../seed/SOURCES.md)). Second, the model is ready for them without a migration: a Subject has a kind, so a person would be a third kind next to Ship and Organisation. **Future work:** crew registers could be added only together with a rule such as Riksarkivet's threshold (records about people are treated as personal until about 110 years have passed), a legal review of the CC0 delivery, and a way to withhold a record from the feed. [ADR 0002](adr/0002-no-person-or-crew-data.md) records the decision.

One kind of personal data does exist: the **names of Staff**, which are the author of every Human transcription. They are the token's name, so a pseudonym such as a work identifier is better than a full name, and they are not part of any published metadata.

## Proposed for production

- **OIDC for Staff.** The static named tokens are the weakest part of the design: they do not expire, cannot be revoked one by one without redeploying, and carry no roles. In production, staff sign in to an identity provider (Keycloak, Authentik or the organisation's Entra ID) with OpenID Connect; catalog-api validates the signed token (issuer, audience, expiry) and takes the author from a claim such as `preferred_username`, and a `role` claim separates reviewers from administrators, which the current design cannot do. The web-ui would use the authorization-code flow with PKCE and keep the token in memory. Tokens become short-lived and are revoked at the provider. Service-to-service credentials move the same way, to Kubernetes ServiceAccount tokens or workload identity instead of shared secrets.
- **Encrypt traffic inside the cluster** with a service mesh (mutual TLS between every pair of services), or at least for the paths that carry credentials.
- **A kernel-enforcing CNI** (Calico or Cilium), which also allows policies by host name, so catalog-api could be allowed to reach `wikidata.org` and nothing else instead of any public address on port 443.
- **A limited database role** for catalog-api (the schema owned by the migration Job, the service able only to read and write the catalog's tables), instead of the superuser.
- **A shared rate limiter** (a counter in Redis, or the limit at the Ingress) so that a limit holds across replicas.
- **Image digests and signatures** in the manifests (cosign), and trivy on a schedule, not only when a release is cut.
- **Backups** of Postgres and Garage, and a tested restore.
- **HTTP redirected to HTTPS**, and a certificate from a certificate authority.

## Known limitations

These are deliberate or unavoidable in this build, and each has an owner in the list above.

- **Rate limits are per-replica.** search-api counts requests per client address in memory, so the limit is 120 a minute on each replica, and with three replicas a client can make three times that. The tile limit at the Ingress is global but per address. A shared limiter is proposed.
- **The stateful services run as a single instance each:** Postgres, Garage, Meilisearch and RabbitMQ. A pod that dies is replaced from its volume in seconds, and nothing is lost ([README](../README.md#scaling-and-persistence)), but for those seconds the service is unavailable, and there is no failover. Their production scaling paths are in the README.
- **Staff tokens are static** and the Postgres role is the superuser (above).
- **Plain HTTP is still served beside HTTPS**, and the certificate is self-signed, so a browser warns once. Traffic between pods is not encrypted.
- **The policy enforcer on Docker Desktop (kindnet) is not reliable under bursts.** It has occasionally stalled connections for about five seconds right after a spike; the cause is not proved ([ADR 0010](adr/0010-security-deny-by-default-with-proofs.md)).
- **Cantaloupe carries 32 findings that have a fix but sit inside the upstream jar,** and they are an accepted risk; the HTTP-handling ones should be treated as reachable. **The worker parses untrusted files with native libraries** that have unfixed findings, accepted on containment. Both are explained in [trivy.md](security/trivy.md).
- **The `X-Forwarded-For` chain is trusted from the Ingress,** so the per-address limits are only as good as the proxy in front of them.
- **There is no backup**, no audit log of reads and no alerting.
- **Rights are informational.** An Image marked as reserved is still served, because the data is synthetic or public domain and access is not gated by Rights.
