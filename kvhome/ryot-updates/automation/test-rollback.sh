#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /srv/homelab/ryot
project="kvh40-rollback-test-$(date +%s)"
trial="$(mktemp -d /srv/homelab/ryot/.rollback-test-XXXXXX)"
postgres_image="$(docker inspect --format '{{.Config.Image}}' kvhome-ryot-db-1)"
previous_image="$(docker inspect --format '{{.Config.Image}}' kvhome-ryot-ryot-1)"
cleanup() {
    docker compose --project-directory "$trial" down --volumes >/dev/null 2>&1 || true
    docker image rm "kvhome/ryot:$project-failed" >/dev/null 2>&1 || true
    rm -rf -- "$trial"
}
trap cleanup EXIT
mkdir "$trial/automation"
cp automation/deploy-candidate.sh automation/verify-live.py "$trial/automation/"
cp owner-session.json "$trial/owner-session.json"
cp backup.sh "$trial/backup.sh"
python3 - "$trial" <<'PY'
from pathlib import Path
import sys
root=Path(sys.argv[1]); p=root/'backup.sh'
p.write_text(p.read_text().replace('cd /srv/homelab/ryot', 'cd '+str(root)))
PY
cat > "$trial/compose.yaml" <<YAML
name: $project
services:
  db:
    image: $postgres_image
    environment:
      POSTGRES_USER: ryot
      POSTGRES_DB: ryot
      POSTGRES_PASSWORD: rollback-local-only
    tmpfs:
      - /var/lib/postgresql:rw,size=512m
    mem_limit: 256m
    cpus: 0.5
  ryot:
    image: $previous_image
    environment:
      DATABASE_URL: postgres://ryot:rollback-local-only@db:5432/ryot
      SERVER_ADMIN_ACCESS_TOKEN: rollback-local-only-admin
      DISABLE_TELEMETRY: 'true'
      USERS_ALLOW_REGISTRATION: 'false'
    mem_limit: 512m
    cpus: 1
networks:
  default:
    internal: true
YAML
docker compose --project-directory "$trial" up -d db >/dev/null
for attempt in $(seq 1 60); do
    if docker compose --project-directory "$trial" exec -T db pg_isready -h 127.0.0.1 -U ryot -d ryot >/dev/null 2>&1; then break; fi
    sleep 1
done
snapshot="$(find backups -maxdepth 1 -name 'ryot-*.dump' -printf '%p\n' | sort | tail -1)"
docker compose --project-directory "$trial" exec -T db pg_restore --exit-on-error -U ryot -d ryot < "$snapshot"
docker compose --project-directory "$trial" up -d ryot >/dev/null
ready=0
for attempt in $(seq 1 90); do
    if docker compose --project-directory "$trial" exec -T ryot curl --fail --silent --max-time 5 http://127.0.0.1:8000/health >/dev/null; then ready=1; break; fi
    sleep 2
done
test "$ready" = 1
python3 - "$trial" "$postgres_image" <<'PYTHON'
from pathlib import Path
import json, sys
command='psql "$DATABASE_URL" -c "CREATE TABLE rollback_failure_marker(id integer)" && exit 23'
(Path(sys.argv[1])/'Dockerfile.failure').write_text('FROM '+sys.argv[2]+'\nCMD '+json.dumps(['sh', '-c', command])+'\n')
PYTHON
docker build -q -t "kvhome/ryot:$project-failed" - < "$trial/Dockerfile.failure" >/dev/null
export RYOT_ROOT="$trial"
export RYOT_INTERNAL_HEALTH=true
export RYOT_SMOKE_NETWORK="$project"_default
if bash "$trial/automation/deploy-candidate.sh" "kvhome/ryot:$project-failed" forced-failure; then
    echo 'Expected failing candidate to be rejected' >&2
    exit 1
fi
test "$(cat "$trial/updates/forced-failure/result")" = rolled_back
test "$(cat "$trial/updates/forced-failure/failed-candidate-exit")" = 23
marker="$(docker compose --project-directory "$trial" exec -T db psql -U ryot -d ryot -Atc "SELECT count(*) FROM information_schema.tables WHERE table_name = 'rollback_failure_marker'")"
test "$marker" = 0
docker compose --project-directory "$trial" exec -T ryot curl --fail --silent http://127.0.0.1:8000/health >/dev/null
echo 'Rollback verified: failed candidate database changes removed, previous application healthy'
docker tag ryot-personal-note:v10.5.0-kv.2 kvhome/ryot:v10.5.0-kv.2
bash "$trial/automation/deploy-candidate.sh" kvhome/ryot:v10.5.0-kv.2 successful-candidate
test "$(cat "$trial/updates/successful-candidate/result")" = deployed
echo 'Successful update verified: migration, owner session and private note smoke checks passed'
