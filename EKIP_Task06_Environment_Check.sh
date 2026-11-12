#!/bin/bash
# EKIP Task 06 environment and dependency preflight for macOS.
# Read-only checks by default. Offers installation only after explicit confirmation.
# No sudo, process killing, destructive Git actions, migrations, or production API calls.
set -u

ROOT="/Users/joseph/enterprise-knowledge-intelligence"
FRONTEND="$ROOT/frontend"
BACKEND="$ROOT/backend"
STAMP="$(date '+%Y%m%d-%H%M%S')"
OUT="$ROOT/docs/task-06/environment-check-$STAMP"
mkdir -p "$OUT" || { echo "ERROR: Cannot create report folder: $OUT"; exit 2; }
REPORT="$OUT/environment-report.txt"
exec > >(tee -a "$REPORT") 2>&1

section() { printf '\n\n========== %s ==========\n' "$1"; }
status() { printf '[%s] %s\n' "$1" "$2"; }

echo "EKIP TASK 06 — ENVIRONMENT & DEPENDENCY CHECK"
echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "Host: $(scutil --get ComputerName 2>/dev/null || hostname)"
echo "Report: $REPORT"
echo "Policy: check first; skip satisfied dependencies; ask before installation."
echo "No sudo, destructive Git actions, process killing, migrations, or production API calls."

if [[ ! -d "$ROOT/.git" || ! -d "$FRONTEND" ]]; then
  status ERROR "Expected EKIP repository/frontend not found at $ROOT"
  echo "Edit ROOT in this script to match the project location, then rerun."
  exit 2
fi

section "1. Operating system and base tools"
sw_vers 2>/dev/null || true
for cmd in git node npm npx python3; do
  if command -v "$cmd" >/dev/null 2>&1; then
    status OK "$cmd: $(command -v "$cmd")"
    case "$cmd" in
      git) git --version ;;
      node) node --version ;;
      npm) npm --version ;;
      python3) python3 --version ;;
    esac
  else
    status MISSING "$cmd is not available on PATH"
  fi
done

section "2. Repository state"
cd "$ROOT" || exit 2
printf 'Repository: '; pwd
printf 'Branch: '; git branch --show-current
echo "Working tree:"
git status --short

section "3. Node dependencies"
if [[ -f "$FRONTEND/package.json" ]]; then
  echo "Found frontend/package.json"
  if [[ -d "$FRONTEND/node_modules" ]]; then
    status OK "frontend/node_modules exists"
  else
    status MISSING "frontend/node_modules is absent"
    read -r -p "Run 'npm ci' in frontend now? This installs lockfile dependencies and changes node_modules (y/N): " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
      if [[ -f "$FRONTEND/package-lock.json" ]]; then
        (cd "$FRONTEND" && npm ci)
      else
        echo "No package-lock.json found; not running npm ci. Review package manager/lockfile manually."
      fi
    else
      echo "Skipped Node dependency installation at user request."
    fi
  fi

  if [[ -x "$FRONTEND/node_modules/.bin/playwright" ]]; then
    status OK "Local Playwright CLI exists"
    (cd "$FRONTEND" && npx playwright --version)
  else
    status MISSING "Local Playwright CLI not found in frontend/node_modules/.bin"
    if [[ -d "$FRONTEND/node_modules" ]]; then
      echo "Not installing Playwright globally. First inspect package.json and lockfile for the intended project version."
      read -r -p "Show Playwright-related package entries now? (Y/n): " answer
      if [[ ! "$answer" =~ ^[Nn]$ ]]; then
        node -e "const p=require('$FRONTEND/package.json'); console.log(JSON.stringify({dependencies:p.dependencies||{},devDependencies:p.devDependencies||{}},null,2))" | grep -i -C 2 playwright || echo "No Playwright entry found in package.json dependencies."
      fi
    fi
  fi
else
  status ERROR "frontend/package.json is missing"
fi

section "4. Playwright browser availability"
if [[ -x "$FRONTEND/node_modules/.bin/playwright" ]]; then
  (cd "$FRONTEND" && npx playwright install --list)
  echo
  echo "If Chromium is missing, the project-scoped command is:"
  echo "  cd \"$FRONTEND\" && npx playwright install chromium"
  read -r -p "If Chromium is missing, install Playwright Chromium now? (y/N): " answer
  if [[ "$answer" =~ ^[Yy]$ ]]; then
    (cd "$FRONTEND" && npx playwright install chromium)
  else
    echo "Skipped browser installation."
  fi
else
  echo "Cannot check Playwright browser cache until the project Playwright CLI is available."
fi

section "5. Python and backend dependency discovery"
if ! command -v python3 >/dev/null 2>&1; then
  status MISSING "python3 is not available on PATH; Python/backend checks cannot run."
else
  python3 --version
fi

# Inspect common backend dependency manifests and virtual environments without assuming
# a single backend layout. This repo has used backend/ paths, but layouts can vary.
declare -a PY_PROJECT_DIRS=()
for dir in "$BACKEND" "$ROOT"; do
  [[ -d "$dir" ]] && PY_PROJECT_DIRS+=("$dir")
done

for dir in "${PY_PROJECT_DIRS[@]}"; do
  echo
  echo "--- Python project directory: $dir ---"
  found_manifest=0
  for manifest in requirements.txt pyproject.toml setup.py Pipfile poetry.lock; do
    if [[ -f "$dir/$manifest" ]]; then
      status FOUND "Dependency/project manifest: $dir/$manifest"
      found_manifest=1
    fi
  done
  if [[ "$found_manifest" -eq 0 ]]; then
    echo "No common Python dependency manifest found at this level."
  fi

  VENV_PY=""
  for candidate in "$dir/.venv/bin/python" "$dir/.venv/bin/python3" "$dir/venv/bin/python" "$dir/venv/bin/python3"; do
    if [[ -x "$candidate" ]]; then VENV_PY="$candidate"; break; fi
  done
  # Also allow a root .venv to serve the backend if no backend-local venv exists.
  if [[ -z "$VENV_PY" && -x "$ROOT/.venv/bin/python" ]]; then VENV_PY="$ROOT/.venv/bin/python"; fi
  if [[ -n "$VENV_PY" ]]; then
    status OK "Python environment detected: $VENV_PY"
    "$VENV_PY" --version
    "$VENV_PY" -m pip --version
    echo "Installed package consistency check:"
    "$VENV_PY" -m pip check
    echo "Key backend module checks:"
    "$VENV_PY" - <<'PY'
import importlib.util
for module in ("fastapi", "uvicorn", "pytest", "httpx", "sqlalchemy", "pydantic"):
    try:
        found = importlib.util.find_spec(module) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        found = False
    print(f"{module}: {'installed' if found else 'not detected'}")
PY
  else
    status REVIEW "No local virtual environment detected for $dir"
  fi

  if [[ -f "$dir/requirements.txt" && -z "$VENV_PY" ]]; then
    echo "A requirements.txt exists but no local/root .venv was detected."
    read -r -p "Create $dir/.venv and install this requirements.txt? (y/N): " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
      if ! command -v python3 >/dev/null 2>&1; then
        echo "Cannot create a virtual environment because python3 is missing."
      elif [[ -e "$dir/.venv" ]]; then
        echo "Refusing to overwrite existing $dir/.venv."
      else
        python3 -m venv "$dir/.venv" &&
        "$dir/.venv/bin/python" -m pip install --upgrade pip &&
        "$dir/.venv/bin/python" -m pip install -r "$dir/requirements.txt"
        if [[ $? -eq 0 ]]; then
          status OK "Installed requirements into $dir/.venv"
          "$dir/.venv/bin/python" -m pip check
        else
          status ERROR "Installation failed for $dir/requirements.txt; inspect the output above."
        fi
      fi
    else
      echo "Skipped installation for $dir."
    fi
  elif [[ -f "$dir/pyproject.toml" && -z "$VENV_PY" ]]; then
    echo "pyproject.toml detected without a local venv. The script will not guess between Poetry, uv, or pip; inspect its tool configuration and ask before installing."
  fi
done

if [[ -d "$BACKEND" ]]; then
  echo
  echo "Backend directory summary:"
  find "$BACKEND" -maxdepth 2 \( -name requirements.txt -o -name pyproject.toml -o -name setup.py -o -name Pipfile -o -name poetry.lock -o -name uv.lock -o -name .venv \) -print 2>/dev/null
else
  status REVIEW "No backend/ directory found at $BACKEND; backend dependency checks were limited to the repository root."
fi

section "6. Test ports"
for port in 5174 8003; do
  echo "--- PORT $port ---"
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null; then
    status REVIEW "Port $port is occupied; identify the owning process before running tests."
  else
    status OK "Port $port is free"
  fi
done

section "7. Playwright test discovery (non-destructive)"
if [[ -x "$FRONTEND/node_modules/.bin/playwright" ]]; then
  (cd "$FRONTEND" && npx playwright test --config=playwright.task06-smoke.config.ts --list)
else
  echo "Skipped: local Playwright CLI is not available."
fi

section "8. Summary"
echo "This report records detected environment state and installation attempts."
echo "A missing tool is not automatically a failure if it is not needed for the selected task."
echo "No automatic installation of Xcode Command Line Tools, Homebrew, Node, Python, or global packages is attempted."
echo "Backend discovery checks common manifests and local virtual environments; non-requirements manifests are reported for a deliberate package-manager-specific decision."
echo "Finished: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "Report saved to: $REPORT"
