#!/usr/bin/env bash
set -euo pipefail

desktop_root="$(cd "$(dirname "$0")" && pwd)"
project_root="$(cd "$desktop_root/.." && pwd)"
cd "$project_root"

.venv/bin/pip install "pyinstaller>=6,<7"
.venv/bin/python desktop/scripts/build_backend.py
