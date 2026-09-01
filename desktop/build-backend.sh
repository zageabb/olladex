#!/usr/bin/env bash
set -euo pipefail

desktop_root="$(cd "$(dirname "$0")" && pwd)"
project_root="$(cd "$desktop_root/.." && pwd)"
cd "$project_root"

.venv/bin/pip install "pyinstaller>=6,<7"
.venv/bin/pyinstaller --noconfirm --clean --onedir \
  --name olladex-api \
  --paths "$project_root" \
  --collect-all uvicorn \
  --collect-all tree_sitter_language_pack \
  --distpath "$desktop_root/dist-api" \
  --workpath "$desktop_root/build-api" \
  --specpath "$desktop_root" \
  backend/desktop_api.py
