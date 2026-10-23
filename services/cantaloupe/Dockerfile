# Cantaloupe has no official image, so this one is built from the official release, checked against its
# published checksum. Every setting is in cantaloupe.properties or passed in the environment.
FROM debian:bookworm-slim AS release
ARG CANTALOUPE_VERSION=5.0.7
ARG CANTALOUPE_SHA256=741ddee3f5284b179cd2555dc545a8afcb02534f03896cfa9235249fd66b0665
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl unzip && rm -rf /var/lib/apt/lists/*
WORKDIR /release
RUN curl -fsSL -o cantaloupe.zip "https://github.com/cantaloupe-project/cantaloupe/releases/download/v${CANTALOUPE_VERSION}/cantaloupe-${CANTALOUPE_VERSION}.zip" \
    && echo "${CANTALOUPE_SHA256}  cantaloupe.zip" | sha256sum -c - \
    && unzip -q cantaloupe.zip \
    && mv "cantaloupe-${CANTALOUPE_VERSION}/cantaloupe-${CANTALOUPE_VERSION}.jar" cantaloupe.jar

FROM eclipse-temurin:21.0.12.1_1-jre-noble
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /var/cache/cantaloupe && chown app /var/cache/cantaloupe
COPY --from=release /release/cantaloupe.jar /opt/cantaloupe/cantaloupe.jar
COPY services/cantaloupe/cantaloupe.properties /etc/cantaloupe/cantaloupe.properties
USER 10001
EXPOSE 8182
# The heap is a share of the container's memory, so the pod limit decides it.
ENTRYPOINT ["java", "-Djava.awt.headless=true", "-XX:MaxRAMPercentage=60", "-Dcantaloupe.config=/etc/cantaloupe/cantaloupe.properties", "-jar", "/opt/cantaloupe/cantaloupe.jar"]
