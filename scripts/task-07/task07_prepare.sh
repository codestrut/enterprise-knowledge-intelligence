#!/bin/bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

IMAGE="ekip-api:task07"
CACHE="${HOME}/.cache/huggingface"
ENV_FILE=".env.task07"

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
pass() { printf 'PASS: %s\n' "$*"; }

command -v docker >/dev/null 2>&1 || fail "Docker CLI is not on PATH."
docker info >/dev/null 2>&1 || fail "Docker Desktop is not running or is not reachable."
docker image inspect "$IMAGE" >/dev/null 2>&1 || fail "Required image $IMAGE is missing. Build Dockerfile.task07 first."
[[ -d "$CACHE" ]] || fail "Hugging Face cache not found at $CACHE."
for model in models--sentence-transformers--all-MiniLM-L6-v2 models--cross-encoder--ms-marco-MiniLM-L-6-v2 models--cross-encoder--nli-deberta-v3-base; do
  [[ -d "$CACHE/hub/$model" ]] || fail "Expected cached model missing: $model"
done
pass "Docker, Task 07 image and three cached models are available."

if /usr/sbin/lsof -nP -iTCP:8004 -sTCP:LISTEN >/dev/null 2>&1; then
  fail "Host port 8004 is already in use. Do not stop the process; choose and consistently update another port."
fi
pass "Host port 8004 is available."

if [[ ! -f "$ENV_FILE" ]]; then
  umask 077
  python3 - <<'PY'
from pathlib import Path
import re, secrets
root = Path(".")
source = root / ".env"
api_key = ""
if source.exists():
    for line in source.read_text(errors="replace").splitlines():
        match = re.match(r"^\s*(?:export\s+)?OPENAI_API_KEY\s*=\s*(.*?)\s*$", line)
        if match:
            value = match.group(1).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            api_key = value
            break
db_user = "ekip_task07"
db_name = "ekip_task07"
db_password = secrets.token_hex(24)
token_secret = secrets.token_hex(32)
lines = [
    f"POSTGRES_DB={db_name}",
    f"POSTGRES_USER={db_user}",
    f"POSTGRES_PASSWORD={db_password}",
    f"EKIP_DATABASE_URL=postgresql+psycopg://{db_user}:{db_password}@ekip-task07-postgres:5432/{db_name}",
    f"EKIP_ACCESS_TOKEN_SECRET={token_secret}",
    "EKIP_TENANT_DATA_DIRECTORY=/app/data/tenants",
    "EKIP_ENABLE_API_DOCS=1",
    "HF_HOME=/models",
    "HF_HUB_OFFLINE=1",
    "TRANSFORMERS_OFFLINE=1",
    f"OPENAI_API_KEY={api_key}",
]
(root / ".env.task07").write_text("\n".join(lines) + "\n")
(root / ".env.task07").chmod(0o600)
print("Created .env.task07 with restrictive permissions.")
print("An existing OPENAI_API_KEY was copied from .env if one was present; its value was not displayed.")
if not api_key:
    print("OPENAI_API_KEY is empty. Add a valid key before the grounded-answer demonstration.")
PY
else
  chmod 600 "$ENV_FILE"
  pass "$ENV_FILE already exists; preserved it and tightened permissions."
fi

[[ "$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || stat -c '%a' "$ENV_FILE")" == "600" ]] || fail "$ENV_FILE permissions are not 600."
grep -q '^EKIP_DATABASE_URL=postgresql+psycopg://' "$ENV_FILE" || fail "EKIP_DATABASE_URL is missing or uses the wrong driver."
grep -q '^EKIP_ACCESS_TOKEN_SECRET=.\{32,\}$' "$ENV_FILE" || fail "EKIP_ACCESS_TOKEN_SECRET is missing or too short."
pass "Protected environment file is ready."
printf '\nMANUAL DOCKER DESKTOP RESOURCES REQUIRED:\n'
printf '  Network:   ekip-task07-net (bridge)\n'
printf '  Volume:    ekip-task07-postgres-data\n'
printf '  Container: ekip-task07-postgres (postgres:16-alpine)\n'
printf '  DB name/user/password: values are in .env.task07; do not paste them into chat.\n'
printf '\nTo copy a single value privately to the macOS clipboard, run one command at a time:\n'
printf "  /usr/bin/grep '^POSTGRES_DB=' .env.task07 | /usr/bin/cut -d= -f2- | /usr/bin/pbcopy\n"
printf "  /usr/bin/grep '^POSTGRES_USER=' .env.task07 | /usr/bin/cut -d= -f2- | /usr/bin/pbcopy\n"
printf "  /usr/bin/grep '^POSTGRES_PASSWORD=' .env.task07 | /usr/bin/cut -d= -f2- | /usr/bin/pbcopy\n"
printf '\nNo Docker resources were created or changed by this preparation script.\n'
