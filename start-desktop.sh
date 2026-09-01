#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")" && pwd)"
cd "$project_root"

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -r backend/requirements.txt
npm_cache_dir="${OLLADEX_NPM_CACHE:-/tmp/olladex-npm-cache}"
npm --prefix frontend install --cache "$npm_cache_dir"
npm --prefix desktop install --cache "$npm_cache_dir"
npm --prefix desktop start
