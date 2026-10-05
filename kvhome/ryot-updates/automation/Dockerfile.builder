FROM node:24.4.0-bookworm-slim AS node
FROM docker:29.8.1-cli AS docker
FROM rust:1.93.1-bookworm
COPY --from=node /usr/local/ /usr/local/
COPY --from=docker /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker /usr/local/libexec/docker/cli-plugins/ /usr/local/libexec/docker/cli-plugins/
RUN apt-get update && apt-get install -y --no-install-recommends clang libssl-dev pkg-config python3 ca-certificates git curl && rm -rf /var/lib/apt/lists/*
RUN npm install --global corepack@0.34.0 && corepack enable
RUN rustup component add rustfmt clippy
CMD ["sleep", "infinity"]
