#!/usr/bin/env bash
# Encrypted, compressed logical backup. Kept 14 days locally, copied off-site.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${BACKUP_AGE_RECIPIENT:?age public key (age1...)}"
: "${BACKUP_REMOTE:?rclone destination, e.g. b2:fund-ledger-backups}"
mkdir -p backups
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
ops/compose.sh exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
  | age --recipient "$BACKUP_AGE_RECIPIENT" > "backups/ledger-$stamp.dump.age"
find backups -name 'ledger-*.dump.age' -mtime +14 -delete
rclone copy backups "$BACKUP_REMOTE"
echo "backup ledger-$stamp.dump.age done"
