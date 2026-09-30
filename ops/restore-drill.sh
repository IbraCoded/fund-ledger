#!/usr/bin/env bash
# Restore a backup into a throwaway Postgres and prove the restored ledger reconciles.
set -euo pipefail
cd "$(dirname "$0")/.."
backup="$1"
: "${AGE_IDENTITY:?path to the age private key}"
image="${RESTORE_IMAGE:-$(grep '^IMAGE=' .env | cut -d= -f2):$(cat .image-tag)}"
name="ledger-restore-$$"

docker run -d --rm --name "$name" -e POSTGRES_USER=ledger -e POSTGRES_PASSWORD=restore \
  -e POSTGRES_DB=ledger postgres:16 >/dev/null
trap 'docker stop "$name" >/dev/null' EXIT
# Wait for TCP (the image's init phase only listens on a socket).
until docker exec "$name" psql -h 127.0.0.1 -U ledger -d ledger -c 'select 1' >/dev/null 2>&1; do sleep 1; done

age --decrypt -i "$AGE_IDENTITY" "$backup" \
  | docker exec -i "$name" pg_restore -U ledger -d ledger --no-owner --no-privileges

docker run --rm --network "container:$name" \
  -e POSTGRES_HOST=127.0.0.1 -e POSTGRES_USER=ledger -e POSTGRES_PASSWORD=restore \
  "$image" python manage.py reconcile
echo "Restore drill passed for $backup"
