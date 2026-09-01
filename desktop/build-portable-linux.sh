#!/usr/bin/env bash
set -euo pipefail

desktop_root="$(cd "$(dirname "$0")" && pwd)"
project_root="$(cd "$desktop_root/.." && pwd)"
version="$(node -p "require('$desktop_root/package.json').version")"
portable_stage="$(mktemp -d /tmp/olladex-portable.XXXXXX)"
portable_root="$portable_stage/Olladex-v${version}-linux-x64"
output_root="$desktop_root/dist"
trap 'rm -rf -- "$portable_stage"' EXIT

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
  echo "The portable Linux build must run on Linux x86_64." >&2
  exit 1
fi

"$desktop_root/build-backend.sh"
node "$desktop_root/scripts/prepare.mjs"
mkdir -p "$portable_root/resources/app" "$portable_root/resources/frontend" "$portable_root/resources/api" "$output_root"
cp -a "$desktop_root/node_modules/electron/dist/." "$portable_root/"
cp "$desktop_root/package.json" "$desktop_root/main.cjs" "$desktop_root/preload.cjs" "$portable_root/resources/app/"
cp -a "$project_root/frontend/.next/standalone/." "$portable_root/resources/frontend/"
cp -a "$desktop_root/dist-api/olladex-api/." "$portable_root/resources/api/"
mv "$portable_root/electron" "$portable_root/olladex"
chmod +x "$portable_root/olladex" "$portable_root/resources/api/olladex-api"
(cd "$portable_stage" && zip -qr "$output_root/Olladex-v${version}-linux-x64-portable.zip" "Olladex-v${version}-linux-x64")
echo "$output_root/Olladex-v${version}-linux-x64-portable.zip"
