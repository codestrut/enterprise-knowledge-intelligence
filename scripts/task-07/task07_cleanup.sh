#!/bin/bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [[ "${1:-}" != "--confirm" ]]; then
  printf 'This removes ONLY Task 07 runtime resources and .env.task07.\n'
  printf 'It retains images, build cache, Hugging Face cache, source, scripts and evidence.\n'
  printf 'Review the target names, then rerun with --confirm.\n'
  exit 2
fi

remove_container() {
  local name="$1"
  if docker inspect "$name" >/dev/null 2>&1; then
    docker rm -f "$name"
    printf 'Removed container: %s\n' "$name"
  else
    printf 'Already absent: container %s\n' "$name"
  fi
}
remove_volume() {
  local name="$1"
  if docker volume inspect "$name" >/dev/null 2>&1; then
    docker volume rm "$name"
    printf 'Removed volume: %s\n' "$name"
  else
    printf 'Already absent: volume %s\n' "$name"
  fi
}

remove_container ekip-task07-api
remove_container ekip-task07-postgres
remove_volume ekip-task07-tenant-data
remove_volume ekip-task07-postgres-data

if docker network inspect ekip-task07-net >/dev/null 2>&1; then
  docker network rm ekip-task07-net
  printf 'Removed network: ekip-task07-net\n'
else
  printf 'Already absent: network ekip-task07-net\n'
fi

if [[ -f .env.task07 ]]; then
  rm -f .env.task07
  printf 'Removed generated secret file: .env.task07\n'
fi

printf '\nCleanup complete. Retained: ekip-api:task07 image, all other images, Docker build cache,\n'
printf 'Hugging Face model cache, repository source, scripts, documentation and evidence.\n'
