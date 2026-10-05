#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /srv/homelab/ryot
image_archive="${1:?Pass the validated Personal Note image archive}"
candidate_image="${2:-ryot-personal-note:v10.5.0-kv.2}"
for name in kvh39-preflight-db kvh39-preflight-app; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Preflight container already exists: $name" >&2
        exit 1
    fi
done
if docker network inspect kvh39-preflight >/dev/null 2>&1; then
    echo 'Preflight network already exists' >&2
    exit 1
fi
./backup.sh
snapshot="$(find backups -maxdepth 1 -name 'ryot-*.dump' -printf '%f\n' | sort | tail -1)"
test -n "$snapshot"
postgres_image="$(docker inspect --format '{{.Config.Image}}' kvhome-ryot-db-1)"
docker load --input "$image_archive"
docker pull python:3.13-alpine >/dev/null
cleanup() {
    docker rm --force kvh39-preflight-app kvh39-preflight-db >/dev/null 2>&1 || true
    docker network rm kvh39-preflight >/dev/null 2>&1 || true
    rm -f backups/kvh39-preflight-recovery.dump
}
trap cleanup EXIT
docker network create --internal kvh39-preflight >/dev/null
docker run --detach --name kvh39-preflight-db --network kvh39-preflight \
    --memory 256m --cpus 0.5 --pids-limit 128 \
    --tmpfs /var/lib/postgresql:rw,size=512m \
    -e POSTGRES_USER=ryot -e POSTGRES_DB=ryot \
    -e POSTGRES_PASSWORD=preflight-local-only "$postgres_image" >/dev/null
ready=0
for attempt in $(seq 1 60); do
    if docker exec kvh39-preflight-db pg_isready -h 127.0.0.1 -U ryot -d ryot >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
done
test "$ready" = 1
docker exec -i kvh39-preflight-db pg_restore --exit-on-error -U ryot -d ryot < "backups/$snapshot"
docker run --detach --name kvh39-preflight-app --network kvh39-preflight \
    --memory 512m --cpus 1 --pids-limit 256 \
    -e DATABASE_URL=postgres://ryot:preflight-local-only@kvh39-preflight-db:5432/ryot \
    -e SERVER_ADMIN_ACCESS_TOKEN=preflight-local-only-admin-token \
    -e USERS_ALLOW_REGISTRATION=true -e DISABLE_TELEMETRY=true \
    -e FRONTEND_URL=http://localhost:18039 \
    "$candidate_image" >/dev/null
ready=0
for attempt in $(seq 1 90); do
    if docker exec kvh39-preflight-app curl --max-time 5 --fail --silent http://127.0.0.1:8000/health >/dev/null; then ready=1; break; fi
    if test "$(docker inspect --format '{{.State.Running}}' kvh39-preflight-app)" != true; then break; fi
    sleep 2
done
test "$ready" = 1
docker run --rm --network kvh39-preflight --memory 128m --cpus 0.5 \
    -v /srv/homelab/ryot/owner-session.json:/srv/homelab/ryot/owner-session.json:ro \
    -v /srv/homelab/ryot/verify-personal-notes.py:/verify.py:ro \
    -e RYOT_PREFLIGHT_ENDPOINT=http://kvh39-preflight-app:8000/backend/graphql \
    python:3.13-alpine python /verify.py
docker exec kvh39-preflight-db pg_dump -U ryot -d ryot -Fc > backups/kvh39-preflight-recovery.dump
docker exec kvh39-preflight-db createdb -U ryot note_recovery
docker exec -i kvh39-preflight-db pg_restore --exit-on-error -U ryot -d note_recovery < backups/kvh39-preflight-recovery.dump
restored_notes="$(docker exec kvh39-preflight-db psql -U ryot -d note_recovery -Atc "SELECT count(*) FROM personal_note WHERE text = 'personal-note-recovery-fixture'")"
test "$restored_notes" = 1
echo 'Personal Note recovery verified in a second isolated database'
echo 'Production database and running Ryot were not modified'
