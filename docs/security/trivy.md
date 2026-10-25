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

No image has a fixed-and-unapplied finding except Cantaloupe's, and none has a secret in a layer. What remains has no corrected package or release to move to.

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

These are libraries bundled inside `cantaloupe-5.0.7.jar` (Jackson, Netty, Jetty, Tika, Bouncy Castle, plexus-utils). 5.0.7 (March 2025) is the newest Cantaloupe release, and replacing libraries inside its jar would give an unsupported, untested build, so a fix is not available to this project until upstream releases one. Each CVE was not analysed one by one; the acceptance rests on what Cantaloupe exposes and what it can reach. Only the IIIF Image API 3 is served (the admin and management API are off, no delegate script is enabled), through the Ingress with a per-address rate limit. Its only source is the fixed `masters` bucket in Garage, read with a read-only key, so a caller cannot make it fetch a URL of their choosing. A NetworkPolicy lets it talk only to Garage. It runs non-root on a read-only filesystem with no capabilities and no Kubernetes API token, and holds no credential that can change data. The finding to watch is the remote-request path through Jetty and Netty: the mitigation is exposure, and the remedy is upgrading Cantaloupe when a release is made.

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

## What this does not show

A scan finds known vulnerabilities in what is installed. It does not show that the services themselves are free of faults, and a clean result today says nothing about tomorrow's database. Images are pinned to exact versions, so a rescan on release is the way to find out; CI does not rescan on a schedule.
