#!/usr/bin/env bash
set -euo pipefail

export DISABLE_TELEMETRY=true
export CARGO_BUILD_JOBS=${RYOT_CARGO_JOBS:-2}
export CARGO_PROFILE_DEV_DEBUG=0
export CARGO_PROFILE_DEV_INCREMENTAL=false
export CARGO_PROFILE_RELEASE_LTO=thin
export UNKEY_ROOT_KEY=dummy-root-key
export SERVER_ADMIN_ACCESS_TOKEN=test-admin-access-token-for-e2e-tests

candidate="${1:?Pass the prepared candidate directory}"
cd "$candidate/source"
git config --global --add safe.directory "$candidate/source"
yarn install --immutable

yarn turbo run build --filter=@ryot/transactional
yarn workspace @ryot/transactional copy-templates

cargo fmt --all
cargo clippy --locked

(
export DATABASE_URL=postgres://postgres:postgres@127.0.0.1:5432/postgres
cargo build --locked
docker run --detach --name note-codegen-db -e POSTGRES_PASSWORD=postgres -p 127.0.0.1:5432:5432 postgres:18-alpine
db_ready=0
for attempt in $(seq 1 60); do
  if docker exec note-codegen-db pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; then db_ready=1; break; fi
  sleep 1
done
test "$db_ready" = 1
cargo run > /tmp/note-codegen.log 2>&1 &
backend_pid=$!
trap 'kill "$backend_pid" || true; docker rm --force note-codegen-db; tail -30 /tmp/note-codegen.log' EXIT
ready=0
for attempt in $(seq 1 120); do
  if curl --fail --silent http://127.0.0.1:5000/config >/dev/null; then ready=1; break; fi
  kill -0 "$backend_pid" 2>/dev/null || break
  sleep 2
done
test "$ready" = 1
yarn turbo run backend-graphql --filter=@ryot/generated
)

node <<'JS'
const fs = require('fs');
for (const [path, command] of [['apps/frontend/package.json', 'react-router typegen'], ['apps/browser-extension/package.json', 'wxt prepare']]) {
  const value = JSON.parse(fs.readFileSync(path));
  value.scripts['prepare-types'] = command;
  fs.writeFileSync(path, JSON.stringify(value));
}
const turbo = JSON.parse(fs.readFileSync('turbo.json'));
turbo.tasks['prepare-types'] = { cache: false };
fs.writeFileSync('turbo.json', JSON.stringify(turbo));
JS
yarn turbo run prepare-types --filter=@ryot/frontend --filter=@ryot/browser-extension
git restore apps/frontend/package.json apps/browser-extension/package.json turbo.json
yarn turbo run typecheck
yarn turbo run build --filter=@ryot/frontend --filter=@ryot/docs

cargo build --release --locked

mkdir -p /tmp/note-minio
cat > /tmp/note-minio/Dockerfile <<'DOCKER'
FROM golang:1.24.8-bookworm AS build
ENV GOFLAGS=-p=2
RUN CGO_ENABLED=0 go install github.com/minio/minio@07c3a429bfed433e49018cb0f78a52145d4bedeb
FROM debian:bookworm-slim
COPY --from=build /go/bin/minio /usr/local/bin/minio
ENTRYPOINT ["minio"]
DOCKER
docker build -t minio/minio:latest /tmp/note-minio

docker create --name note-caddy caddy:2.9.1
docker cp note-caddy:/usr/bin/caddy /tmp/caddy
docker rm note-caddy
install /tmp/caddy /usr/local/bin/caddy
yarn turbo run test --filter=@ryot/tests --env-mode=loose

git add --all
git -c user.name='Ryot update builder' -c user.email='ryot-builder@users.noreply.github.com' commit -m 'Apply private media patches to upstream candidate [skip ci]'
mkdir -p artifact/backend-amd64
cp target/release/backend artifact/backend-amd64/backend
image_tag="ryot-update:local-${RYOT_BUILD_ID:?}"
docker build --build-arg TARGETARCH=amd64 --label org.opencontainers.image.source=https://github.com/kvaranovich/ryot --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" -t "$image_tag" .
mkdir -p "$candidate/artifact"
docker save "$image_tag" | gzip > "$candidate/artifact/image.tar.gz"
git bundle create "$candidate/artifact/source.bundle" HEAD
python3 - "$candidate" "$image_tag" <<'PYTHON'
import hashlib, json, os, pathlib, subprocess, sys
root=pathlib.Path(sys.argv[1])
manifest=json.loads((root/'integration.json').read_text())
with (root/'artifact/image.tar.gz').open('rb') as stream:
    digest=hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024*1024), b''):
        digest.update(chunk)
    checksum=digest.hexdigest()
manifest.update(status='built', repository='kvaranovich/ryot', image_tag=sys.argv[2], image_archive_sha256=checksum, executor='local-mac', build_id=int(os.environ['RYOT_BUILD_ID']), control_sha256=os.environ['RYOT_CONTROL_SHA256'], candidate_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip())
(root/'artifact/manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
PYTHON
