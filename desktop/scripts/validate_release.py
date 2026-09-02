"""Validate that Electron Builder emitted the expected release assets."""

from __future__ import annotations

import sys
from pathlib import Path


EXPECTED = {"linux": (".AppImage", ".deb"), "macos": (".dmg",), "windows": (".exe",)}


def main() -> None:
    platform = sys.argv[1] if len(sys.argv) > 1 else ""
    if platform not in EXPECTED:
        raise SystemExit("usage: validate_release.py linux|macos|windows")
    root = Path(__file__).resolve().parent.parent / "dist"
    missing = []
    for suffix in EXPECTED[platform]:
        matches = [path for path in root.glob(f"*{suffix}") if path.is_file() and path.stat().st_size > 100_000]
        if not matches:
            missing.append(suffix)
    if missing:
        raise SystemExit(f"Missing or undersized {platform} release assets: {', '.join(missing)}")
    print(f"Validated {platform} release assets")


if __name__ == "__main__":
    main()
