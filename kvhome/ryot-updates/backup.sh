#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /srv/homelab/ryot
mkdir -p backups
snapshot="backups/ryot-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose exec -T db pg_dump -U ryot -d ryot -Fc > "${snapshot}.partial"
docker compose exec -T db pg_restore --list < "${snapshot}.partial" >/dev/null
mv -- "${snapshot}.partial" "${snapshot}"
sha256sum "${snapshot}" > "${snapshot}.sha256"
find backups -name 'ryot-*.dump*' -mtime +14 -delete
