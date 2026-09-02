"""Build the Olladex API sidecar on the current desktop platform."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


DESKTOP = Path(__file__).resolve().parent.parent
ROOT = DESKTOP.parent


def main() -> None:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "olladex-api",
        "--paths",
        str(ROOT),
        "--collect-all",
        "uvicorn",
        "--collect-all",
        "tree_sitter_language_pack",
        "--distpath",
        str(DESKTOP / "dist-api"),
        "--workpath",
        str(DESKTOP / "build-api"),
        "--specpath",
        str(DESKTOP),
        str(ROOT / "backend" / "desktop_api.py"),
    ]
    if sys.platform == "win32":
        command[3:3] = ["--collect-all", "winpty"]
    subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
