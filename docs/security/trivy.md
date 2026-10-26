# Image scans (trivy)

Every custom image of release 0.12.0, scanned on 2026-10-25 with trivy 0.58.0 (`aquasec/trivy:0.58.0`; the vulnerability database is the day's). Regenerate with `make trivy`, which fails on a HIGH or CRITICAL finding that has a fix available in an image that is not Cantaloupe. The scan covers operating-system packages, Python and Java libraries, secrets baked into layers, and Dockerfile misconfigurations.

| Image | Base | Critical | High | Medium | Low | High/critical with a fix | Secrets in layers | Was (critical/high) before this slice |
|---|---|---|---|---|---|---|---|---|
| catalog-api | debian 13.7 | 0 | 44 | 63 | 62 | 0 | 0 | 9 / 109 |
| transcribe-worker | debian 13.7 | 1 | 70 | 114 | 159 | 0 | 0 | 16 / 179 |
| indexer | debian 13.7 | 0 | 44 | 63 | 62 | 0 | 0 | 9 / 109 |
| search-api | debian 13.7 | 0 | 44 | 63 | 62 | 0 | 0 | 9 / 109 |
| web-ui | alpine 3.24.2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 45 |
| cantaloupe | ubuntu 24.04 | 4 | 28 | 69 | 11 | 32 | 0 | 4 / 28 |

## What was fixed

The first scan, of the 0.11.0 images, found 9 critical and 109 high findings in each Python image (16 and 179 in the worker). What changed:

- **Pillow 11.3.0 to 13.0.0** in the worker, the library that opens uploaded scans: 5 critical and dozens of high findings, all fixed in 12.x or 13.0.
- **FastAPI 0.115.6 to 0.162.0** in catalog-api, search-api and the indexer, which moved Starlette from 0.41.3 to 1.10.0 (3 high findings).
- **Base images**: `python:3.12.7-slim-bookworm` (Debian 12.8, October 2024) to `python:3.12.15-slim-trixie` (Debian 13), which has a newer Tesseract (5.5) and no longer carries most of the older findings; `nginx-unprivileged` 1.29.8 to 1.31.7 plus `apk upgrade`; the Cantaloupe image applies Ubuntu's security updates at build time.
- **web-ui** has no finding of any severity left.

All four service suites and the seed's suite pass on the new versions.

## What is accepted, and why

No image has a fixed-and-unapplied finding except Cantaloupe's, and none has a secret in a layer. Apart from Cantaloupe's, what remains is a finding Debian has chosen not to fix or has not yet fixed, so there is no corrected package to move to.

### catalog-api (0 critical, 44 high)

Debian lists these as `affected`, `fix_deferred` or `will_not_fix`: its security team has judged them minor or not yet fixable, and has published no corrected package, so there is nothing to upgrade to. Most are in base userland (util-linux, ncurses, gzip, perl, systemd libraries) that the service never runs: there is no shell reachable, nothing in the application starts these programs, and the container is non-root, read-only, has every capability dropped and a seccomp profile.

Status of these findings: 43 `affected`, 1 `fix_deferred`.

| Package | Version | Critical | High |
|---|---|---|---|
| bsdutils | 1:2.41.5-0+deb13u1 |  | 4 |
| libblkid1 | 2.41.5-0+deb13u1 |  | 4 |
| liblastlog2-2 | 2.41.5-0+deb13u1 |  | 4 |
| libmount1 | 2.41.5-0+deb13u1 |  | 4 |
| libsmartcols1 | 2.41.5-0+deb13u1 |  | 4 |
| libuuid1 | 2.41.5-0+deb13u1 |  | 4 |
| login | 1:4.16.0-2+really2.41.5-0+deb13u1 |  | 4 |
| mount | 2.41.5-0+deb13u1 |  | 4 |
| util-linux | 2.41.5-0+deb13u1 |  | 4 |
| libacl1 | 2.3.2-2+b1 |  | 1 |
| libncursesw6 | 6.5+20250216-2 |  | 1 |
| libsystemd0 | 257.13-1~deb13u1 |  | 1 |
| libtinfo6 | 6.5+20250216-2 |  | 1 |
| libudev1 | 257.13-1~deb13u1 |  | 1 |
| ncurses-base | 6.5+20250216-2 |  | 1 |
| ncurses-bin | 6.5+20250216-2 |  | 1 |
| perl-base | 5.40.1-6+deb13u1 |  | 1 |

### transcribe-worker (1 critical, 70 high)

Debian lists these as `affected`, `fix_deferred` or `will_not_fix`: its security team has judged them minor or not yet fixable, and has published no corrected package, so there is nothing to upgrade to. Most are in base userland (util-linux, ncurses, gzip, perl, systemd libraries) that the service never runs: there is no shell reachable, nothing in the application starts these programs, and the container is non-root, read-only, has every capability dropped and a seccomp profile. The worker is the one service that parses untrusted files with native libraries (Tesseract, Leptonica, libtiff, libxml2, glib), so its unfixed findings deserve more weight than the others'. They are accepted because the worker is contained rather than because they cannot be reached: a NetworkPolicy lets it talk only to RabbitMQ, catalog-api and Garage, it holds no database credentials and no keys other than its own broker login and service token, runs non-root on a read-only filesystem with no capabilities, has a 1 GiB memory limit, and handles one image at a time, so a crash loses one job, which the queue redelivers. It reads an image only after catalog-api has checked it.

Status of these findings: 69 `affected`, 1 `fix_deferred`, 1 `will_not_fix`.

| Package | Version | Critical | High |
|---|---|---|---|
| libxml2 | 2.12.7+dfsg+really2.9.14-2.1+deb13 | 1 | 7 |
| libtesseract5 | 5.5.0-1+b1 |  | 6 |
| tesseract-ocr | 5.5.0-1+b1 |  | 6 |
| bsdutils | 1:2.41.5-0+deb13u1 |  | 4 |
| libblkid1 | 2.41.5-0+deb13u1 |  | 4 |
| liblastlog2-2 | 2.41.5-0+deb13u1 |  | 4 |
| libmount1 | 2.41.5-0+deb13u1 |  | 4 |
| libsmartcols1 | 2.41.5-0+deb13u1 |  | 4 |
| libuuid1 | 2.41.5-0+deb13u1 |  | 4 |
| login | 1:4.16.0-2+really2.41.5-0+deb13u1 |  | 4 |
| mount | 2.41.5-0+deb13u1 |  | 4 |
| util-linux | 2.41.5-0+deb13u1 |  | 4 |
| libcurl4t64 | 8.14.1-2+deb13u7 |  | 2 |
| libtiff6 | 4.7.0-3+deb13u3 |  | 2 |
| libacl1 | 2.3.2-2+b1 |  | 1 |
| libncursesw6 | 6.5+20250216-2 |  | 1 |
| libsystemd0 | 257.13-1~deb13u1 |  | 1 |
| libtinfo6 | 6.5+20250216-2 |  | 1 |
| libudev1 | 257.13-1~deb13u1 |  | 1 |
| libx11-6 | 2:1.8.12-1 |  | 1 |
| libx11-data | 2:1.8.12-1 |  | 1 |
| libxrender1 | 1:0.9.12-1 |  | 1 |
| ncurses-base | 6.5+20250216-2 |  | 1 |
| ncurses-bin | 6.5+20250216-2 |  | 1 |
| perl-base | 5.40.1-6+deb13u1 |  | 1 |

### indexer (0 critical, 44 high)

Debian lists these as `affected`, `fix_deferred` or `will_not_fix`: its security team has judged them minor or not yet fixable, and has published no corrected package, so there is nothing to upgrade to. Most are in base userland (util-linux, ncurses, gzip, perl, systemd libraries) that the service never runs: there is no shell reachable, nothing in the application starts these programs, and the container is non-root, read-only, has every capability dropped and a seccomp profile.

Status of these findings: 43 `affected`, 1 `fix_deferred`.

| Package | Version | Critical | High |
|---|---|---|---|
| bsdutils | 1:2.41.5-0+deb13u1 |  | 4 |
| libblkid1 | 2.41.5-0+deb13u1 |  | 4 |
| liblastlog2-2 | 2.41.5-0+deb13u1 |  | 4 |
| libmount1 | 2.41.5-0+deb13u1 |  | 4 |
| libsmartcols1 | 2.41.5-0+deb13u1 |  | 4 |
| libuuid1 | 2.41.5-0+deb13u1 |  | 4 |
| login | 1:4.16.0-2+really2.41.5-0+deb13u1 |  | 4 |
| mount | 2.41.5-0+deb13u1 |  | 4 |
| util-linux | 2.41.5-0+deb13u1 |  | 4 |
| libacl1 | 2.3.2-2+b1 |  | 1 |
| libncursesw6 | 6.5+20250216-2 |  | 1 |
| libsystemd0 | 257.13-1~deb13u1 |  | 1 |
| libtinfo6 | 6.5+20250216-2 |  | 1 |
| libudev1 | 257.13-1~deb13u1 |  | 1 |
| ncurses-base | 6.5+20250216-2 |  | 1 |
| ncurses-bin | 6.5+20250216-2 |  | 1 |
| perl-base | 5.40.1-6+deb13u1 |  | 1 |

### search-api (0 critical, 44 high)

Debian lists these as `affected`, `fix_deferred` or `will_not_fix`: its security team has judged them minor or not yet fixable, and has published no corrected package, so there is nothing to upgrade to. Most are in base userland (util-linux, ncurses, gzip, perl, systemd libraries) that the service never runs: there is no shell reachable, nothing in the application starts these programs, and the container is non-root, read-only, has every capability dropped and a seccomp profile.

Status of these findings: 43 `affected`, 1 `fix_deferred`.

| Package | Version | Critical | High |
|---|---|---|---|
| bsdutils | 1:2.41.5-0+deb13u1 |  | 4 |
| libblkid1 | 2.41.5-0+deb13u1 |  | 4 |
| liblastlog2-2 | 2.41.5-0+deb13u1 |  | 4 |
| libmount1 | 2.41.5-0+deb13u1 |  | 4 |
| libsmartcols1 | 2.41.5-0+deb13u1 |  | 4 |
| libuuid1 | 2.41.5-0+deb13u1 |  | 4 |
| login | 1:4.16.0-2+really2.41.5-0+deb13u1 |  | 4 |
| mount | 2.41.5-0+deb13u1 |  | 4 |
| util-linux | 2.41.5-0+deb13u1 |  | 4 |
| libacl1 | 2.3.2-2+b1 |  | 1 |
| libncursesw6 | 6.5+20250216-2 |  | 1 |
| libsystemd0 | 257.13-1~deb13u1 |  | 1 |
| libtinfo6 | 6.5+20250216-2 |  | 1 |
| libudev1 | 257.13-1~deb13u1 |  | 1 |
| ncurses-base | 6.5+20250216-2 |  | 1 |
| ncurses-bin | 6.5+20250216-2 |  | 1 |
| perl-base | 5.40.1-6+deb13u1 |  | 1 |

### web-ui (0 critical, 0 high)

Nothing to accept.

### cantaloupe (4 critical, 28 high)

Unlike every other finding here, these are fixable: each has a corrected library version, but the libraries (Jackson, Netty, Jetty, Tika, Bouncy Castle, plexus-utils) are bundled inside `cantaloupe-5.0.7.jar`. 5.0.7 (March 2025) is the newest Cantaloupe release, and replacing libraries inside its jar would give an unsupported, untested build, so the remedy is a Cantaloupe release, and until then this is an accepted risk, not a resolved one. It is accepted on containment and on what is reachable, and the CVEs were not analysed one by one, so **the HTTP-handling ones (Jetty, Netty) should be treated as reachable by anyone who can reach the Ingress**: Traefik forwards only `/iiif/3`, but it does not make Jetty's request parsing safe. What limits the damage: only the IIIF Image API 3 is served (the admin and management API are off and no delegate script is enabled); its only source is the fixed `masters` bucket in Garage, read with a read-only key, so a caller cannot make it fetch a URL of their choosing; a NetworkPolicy lets it talk only to Garage; and it runs non-root on a read-only filesystem with no capabilities, no Kubernetes API token and no credential that can change data. The exact findings accepted are listed in `docs/security/cantaloupe-accepted.txt`, and `make trivy` fails if a new fixable one appears. The Bouncy Castle and Tika findings concern TLS and document parsing, which this configuration does not use (HTTPS is off in Cantaloupe, and no document format is read), but that was not verified at runtime.

Status of these findings: 32 `fixed`.

| Package | Version | Critical | High |
|---|---|---|---|
| org.bouncycastle:bcprov-jdk18on | 1.78 | 2 | 1 |
| io.netty:netty-handler | 4.1.101.Final | 1 | 4 |
| org.apache.tika:tika-core | 2.8.0 | 1 |  |
| io.netty:netty-codec-http | 4.1.100.Final |  | 6 |
| com.fasterxml.jackson.core:jackson-databind | 2.15.2 |  | 5 |
| io.netty:netty-codec-http2 | 4.1.100.Final |  | 4 |
| com.fasterxml.jackson.core:jackson-core | 2.15.2 |  | 2 |
| io.netty:netty-codec | 4.1.101.Final |  | 2 |
| org.codehaus.plexus:plexus-utils | 4.0.0 |  | 1 |
| org.eclipse.jetty.http2:http2-common | 11.0.24 |  | 1 |
| org.eclipse.jetty:jetty-http | 11.0.24 |  | 1 |
| org.eclipse.jetty:jetty-security | 11.0.24 |  | 1 |

## The other images the stack runs

Not ours, so not part of the acceptance, but they run in the same namespace, so they are scanned too and a fixable HIGH or CRITICAL finding in any of them fails `make trivy`. Postgres 16.4, which the first scan found with 7 critical and 82 high findings, all fixable, was moved to 16.15 (the same major version, so the data directory is unchanged), and the init Jobs' Python base from `python:3.12.7-slim-bookworm` to `3.12.15-slim-trixie`.

| Used for | Image | Base | Critical | High | High/critical with a fix |
|---|---|---|---|---|---|
| garage-init and meilisearch-init, one of which holds the Meilisearch master key | `python:3.12.15-slim-trixie` | debian 13.7 | 0 | 44 | 0 |
| the database, and the migration Job's readiness wait | `postgres:16.15-alpine` | alpine 3.24.3 | 1 | 25 | 26 |
| the broker | `rabbitmq:4.3.7-alpine` | alpine 3.23.7 | 0 | 0 | 0 |
| object storage | `dxflrs/garage:v2.4.1` | no OS packages | 0 | 0 | 0 |
| the search index | `getmeili/meilisearch:v1.55.0` | alpine 3.22.6 | 0 | 10 | 10 |
| Garage's one-time ownership fix | `busybox:1.37.0` | no OS packages | 0 | 0 | 0 |

**postgres.** Every remaining finding (1 critical, 25 high, all `stdlib` v1.24.6) is the Go standard library compiled into `gosu`, the helper the image's entrypoint uses to drop from root to the postgres user. This deployment starts as the postgres user (uid 70) from the first instruction, so `gosu` is never run; PostgreSQL itself and the Alpine packages have no fixable finding. A newer tag that rebuilds `gosu` removes them.

**meilisearch.** v1.55.0 is the newest Meilisearch release. Its ten HIGH findings are Alpine packages with a fix in a newer Alpine that this release has not been rebuilt on, so there is nothing to change here short of building our own Meilisearch image. Meilisearch is reachable only from search-api (search key) and the indexer (index key) and runs non-root on a read-only filesystem; its master key is held by nothing else.

## What this does not show

A scan finds known vulnerabilities in what is installed. It does not show that the services themselves are free of faults, and a clean result today says nothing about tomorrow's database. Images are pinned to exact versions, so a rescan on release is the way to find out; CI does not rescan on a schedule.
