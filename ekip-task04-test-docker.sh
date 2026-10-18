#!/usr/bin/env bash
# Launch a disposable EKIP API test container without touching production data.
# Run from the EKIP project root, where .env is present.
set -Eeuo pipefail

ROOT_DIR="$(pwd)"
IMAGE="ekip-api:v1"
SOURCE_CONTAINER="ekip-api"
TEST_CONTAINER="ekip-api-test"
TEST_DATA_VOLUME="ekip_task04_test_data"
HF_CACHE_VOLUME="ekip_task04_test_hf_cache"
HOST_PORT="8001"
HEALTH_URL="http://127.0.0.1:${HOST_PORT}/health"
DOCS_URL="http://127.0.0.1:${HOST_PORT}/documents"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "Docker CLI not found. Run this on the Mac/Codex environment with Docker Desktop available."
[[ -f "$ROOT_DIR/.env" ]] || fail "No .env found in current directory. Run this from the EKIP project root."
docker image inspect "$IMAGE" >/dev/null 2>&1 || fail "Required image $IMAGE is not present locally."
[[ "$(docker inspect -f '{{.State.Running}}' "$SOURCE_CONTAINER" 2>/dev/null || true)" == "true" ]] || fail "$SOURCE_CONTAINER must be running so its verified Hugging Face cache can be copied."
if docker container inspect "$TEST_CONTAINER" >/dev/null 2>&1; then
  fail "Container $TEST_CONTAINER already exists. Inspect it first; this script will not replace or delete it."
fi
if docker container inspect "ekip-hf-cache-seed-helper" >/dev/null 2>&1; then
  fail "Cache-seeding helper already exists. Inspect it first; this script will not replace or delete it."
fi

# Create dedicated test data and model-cache volumes. Never mount ekip_data here.
docker volume create "$TEST_DATA_VOLUME" >/dev/null
docker volume create "$HF_CACHE_VOLUME" >/dev/null

printf 'Seeding dedicated Hugging Face cache volume from %s...\n' "$SOURCE_CONTAINER"
# Stream a tar archive so Hugging Face's snapshot symlinks and blobs remain intact.
# The helper uses the existing image; no new image pull is needed.
set -o pipefail
docker exec "$SOURCE_CONTAINER" tar -C /root/.cache/huggingface -cf - . \
  | docker run --name "ekip-hf-cache-seed-helper" -i -v "${HF_CACHE_VOLUME}:/target" --entrypoint sh "$IMAGE" \
      -c 'tar -xf - -C /target'

printf 'Starting isolated test API on 127.0.0.1:%s...\n' "$HOST_PORT"
docker run -d \
  --name "$TEST_CONTAINER" \
  --restart=no \
  -p "127.0.0.1:${HOST_PORT}:8000" \
  --env-file "$ROOT_DIR/.env" \
  -e HF_HUB_OFFLINE=1 \
  -e TRANSFORMERS_OFFLINE=1 \
  -v "${TEST_DATA_VOLUME}:/app/data" \
  -v "${HF_CACHE_VOLUME}:/root/.cache/huggingface" \
  "$IMAGE" >/dev/null

printf 'Waiting for health endpoint (up to 180 seconds)...\n'
HEALTH_TMP="$(mktemp)"
DOCS_TMP="$(mktemp)"
cleanup_tmp() { rm -f "$HEALTH_TMP" "$DOCS_TMP"; }
trap cleanup_tmp EXIT
healthy=false
for ((attempt=1; attempt<=90; attempt++)); do
  if curl --silent --show-error --fail --max-time 4 "$HEALTH_URL" >"$HEALTH_TMP" 2>/dev/null; then
    healthy=true
    break
  fi
  sleep 2
done
if [[ "$healthy" != "true" ]]; then
  printf 'Health check did not pass. The test container has been left running for inspection.\n' >&2
  printf 'Inspect with: docker logs --tail 100 %s\n' "$TEST_CONTAINER" >&2
  exit 1
fi

python3 - "$HEALTH_TMP" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
if data.get("status") != "ok":
    raise SystemExit(f"Health response is not OK: {data}")
if not data.get("manifest_exists"):
    raise SystemExit(f"Health response says manifest is missing: {data}")
print("TEST API HEALTH:", json.dumps(data, sort_keys=True))
PY

curl --silent --show-error --fail --max-time 10 "$DOCS_URL" >"$DOCS_TMP"
python3 - "$DOCS_TMP" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
docs = data.get("documents")
if not isinstance(docs, list) or data.get("count") != len(docs):
    raise SystemExit(f"Document-list response is inconsistent: {data}")
print(f"TEST API DOCUMENT LIST: OK (count={data['count']})")
PY

printf '\nIsolated test container is running: %s\n' "$TEST_CONTAINER"
printf 'Base URL: http://127.0.0.1:%s\n' "$HOST_PORT"
printf 'Test data volume: %s\n' "$TEST_DATA_VOLUME"
printf 'Model cache volume: %s\n' "$HF_CACHE_VOLUME"
printf 'Production container and ekip_data were not mounted or modified by this script.\n'
printf 'Stop test container when done: docker stop %s\n' "$TEST_CONTAINER"
printf 'Do not remove volumes until test results have been reviewed.\n'
