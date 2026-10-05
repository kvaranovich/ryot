#!/usr/bin/env bash
set -euo pipefail
umask 077
root="${RYOT_ROOT:-/srv/homelab/ryot}"
cd "$root"
image="${1:?Pass the validated local image}"
deployment="${2:?Pass a unique deployment identifier}"
[[ "$image" =~ ^kvhome/ryot:[a-zA-Z0-9._-]+$ ]]
[[ "$deployment" =~ ^[a-zA-Z0-9._-]+$ ]]
exec 9>deployment.lock
flock -n 9
docker image inspect "$image" >/dev/null
docker compose config -q
state="updates/$deployment"
mkdir -p updates
test ! -e "$state"
mkdir "$state"
cp compose.yaml "$state/compose.before.yaml"
printf 'preparing\n' > "$state/result"
old_image="$(docker inspect --format '{{.Config.Image}}' "$(docker compose ps -q ryot)")"
changed_database=0
snapshot=''
recovery_database="kvh40_backup_check_$$"
wait_for_app() {
    for attempt in $(seq 1 90); do
        if test "${RYOT_INTERNAL_HEALTH:-false}" = true; then
            if docker compose exec -T ryot curl --fail --silent --max-time 5 http://127.0.0.1:8000/health >/dev/null; then return 0; fi
        elif curl --fail --silent --max-time 5 "${RYOT_HEALTH_URL:-http://127.0.0.1:18038/health}" >/dev/null; then
            return 0
        fi
        container="$(docker compose ps --all -q ryot)"
        if test -z "$container" || test "$(docker inspect --format '{{.State.Running}}' "$container")" != true; then return 1; fi
        sleep 2
    done
    return 1
}
restore_previous() {
    original_status="${1:-$?}"
    trap - ERR INT TERM
    set +e
    failed_container="$(docker compose ps --all -q ryot)"
    if test -n "$failed_container"; then
        docker inspect --format '{{.State.ExitCode}}' "$failed_container" > "$state/failed-candidate-exit" 2>/dev/null
    fi
    docker compose stop ryot >/dev/null 2>&1
    docker compose exec -T db dropdb --if-exists -U ryot "$recovery_database" >/dev/null 2>&1
    restored=1
    if test "$changed_database" = 1; then
        docker compose exec -T db dropdb --force --if-exists -U ryot ryot >/dev/null 2>&1 &&
        docker compose exec -T db createdb -U ryot -O ryot ryot >/dev/null 2>&1 &&
        docker compose exec -T db pg_restore --exit-on-error -U ryot -d ryot < "$snapshot" > "$state/restore.log" 2>&1
        restored=$?
    else
        restored=0
    fi
    cp "$state/compose.before.yaml" compose.yaml
    if test "$restored" = 0; then
        docker compose up -d --no-deps --no-build ryot >/dev/null 2>&1
        wait_for_app
        restored=$?
    fi
    if test "$restored" = 0; then
        echo 'Update failed; previous image and database restored' >&2
        printf 'rolled_back\n' > "$state/result"
    else
        docker compose stop ryot >/dev/null 2>&1
        echo 'Update failed; Ryot stopped. Preserve the backup and inspect local recovery logs.' >&2
        printf 'recovery_required\n' > "$state/result"
    fi
    exit "$original_status"
}
trap restore_previous ERR
trap 'restore_previous 130' INT
trap 'restore_previous 143' TERM
docker compose stop ryot >/dev/null
./backup.sh > "$state/backup.log" 2>&1
snapshot="$(find backups -maxdepth 1 -name 'ryot-*.dump' -printf '%p\n' | sort | tail -1)"
test -n "$snapshot"
printf '%s\n' "$snapshot" > "$state/snapshot"
sha256sum --check "$snapshot.sha256" > "$state/checksum.log"
docker compose exec -T db createdb -U ryot "$recovery_database"
docker compose exec -T db pg_restore --exit-on-error -U ryot -d "$recovery_database" < "$snapshot" > "$state/backup-restore-check.log" 2>&1
docker compose exec -T db dropdb -U ryot "$recovery_database"
python3 - "$image" <<'PY'
from pathlib import Path
import re, sys
path=Path('compose.yaml')
text=path.read_text()
text, count=re.subn(r'(?m)^    image: kvhome/ryot:[^\n]+$', '    image: '+sys.argv[1], text)
assert count==1, 'Expected exactly one Ryot image entry'
text=text.replace('    build: .\n', '')
path.write_text(text)
PY
docker compose config -q
changed_database=1
printf 'activating\n' > "$state/result"
docker compose up -d --no-deps --no-build ryot > "$state/deploy.log" 2>&1
wait_for_app
if test "${RYOT_INTERNAL_HEALTH:-false}" = true; then
    docker run --rm --network "${RYOT_SMOKE_NETWORK:?}" --memory 128m --cpus 0.5 \
        -v "$root/owner-session.json:/srv/homelab/ryot/owner-session.json:ro" \
        -v "$root/automation/verify-live.py:/verify-live.py:ro" \
        -e RYOT_GRAPHQL_URL=http://ryot:8000/backend/graphql \
        python:3.13-alpine python /verify-live.py > "$state/smoke.log" 2>&1
else
    python3 "$root/automation/verify-live.py" > "$state/smoke.log" 2>&1
    python3 "$root/verify-search.py" > "$state/provider-smoke.log" 2>&1
fi
trap - ERR INT TERM
python3 - "$image" "$old_image" "$snapshot" "$deployment" <<'PY'
from datetime import datetime, timezone
from pathlib import Path
import json, subprocess, sys
record=dict(new_image=sys.argv[1], previous_image=sys.argv[2], backup=sys.argv[3], deployment=sys.argv[4], deployed_at=datetime.now(timezone.utc).isoformat(), image_id=subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',sys.argv[1]],text=True).strip())
with Path('updates/deployments.jsonl').open('a') as stream:
    stream.write(json.dumps(record)+'\n')
Path('updates/'+sys.argv[4]+'/result').write_text('deployed\n')
PY
echo 'Validated Ryot update deployed; previous image and database backup retained'
