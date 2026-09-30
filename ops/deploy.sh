#!/usr/bin/env bash
# Deploy an image tag (a commit SHA). Rollback = run this again with the previous SHA.
set -euo pipefail
cd "$(dirname "$0")/.."
sha="$1"
previous="$(cat .image-tag 2>/dev/null || echo none)"
export IMAGE_TAG="$sha"

ops/compose.sh pull migrate api
ops/compose.sh up -d        # runs the migrate job, then (re)starts api once it has succeeded

for _ in $(seq 1 30); do
  status="$(docker inspect --format '{{.State.Health.Status}}' "$(ops/compose.sh ps -q api)")"
  [[ "$status" == healthy ]] && break
  sleep 2
done
if [[ "$status" != healthy ]]; then
  echo "api is $status. Roll back with: ops/deploy.sh $previous" >&2
  exit 1
fi

ops/compose.sh exec -T api python manage.py reconcile
echo "$sha" > .image-tag
docker image prune -f --filter "until=168h" >/dev/null
echo "Deployed $sha (previous: $previous)"
