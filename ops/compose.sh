#!/usr/bin/env bash
# docker compose with the production files and the deployed image tag.
set -euo pipefail
cd "$(dirname "$0")/.."
files=(-f docker-compose.yml -f docker-compose.prod.yml)
[[ -f .monitoring ]] && files+=(-f docker-compose.monitoring.yml)
IMAGE_TAG="${IMAGE_TAG:-$(cat .image-tag)}" exec docker compose "${files[@]}" "$@"
