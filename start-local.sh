#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")" && pwd)"
cd "$project_root"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

.venv/bin/pip install -r backend/requirements.txt
npm_cache_dir="${OLLADEX_NPM_CACHE:-/tmp/olladex-npm-cache}"
npm --prefix frontend install --cache "$npm_cache_dir"
mkdir -p data

OLLADEX_DATA_ROOT="${OLLADEX_DATA_ROOT:-$project_root/data}" \
  .venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port "${OLLADEX_API_PORT:-8001}" &
backend_pid=$!
trap 'kill "$backend_pid" 2>/dev/null || true' EXIT

NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:${OLLADEX_API_PORT:-8001}/api}" \
  npm --prefix frontend run dev -- --hostname 0.0.0.0 --port "${OLLADEX_PORT:-5081}"
