#!/usr/bin/env bash
# Forced command for the CI deploy key. The only thing that key can do is deploy a commit.
set -euo pipefail
sha="${SSH_ORIGINAL_COMMAND:-}"
if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "refused: expected a 40-character commit SHA" >&2
  exit 1
fi
cd "$HOME/fund-ledger"
git fetch --quiet origin
git checkout --quiet --detach "$sha"   # compose files, Caddyfile and scripts match the image
exec ops/deploy.sh "$sha"
