"""Start a frozen Olladex API and verify its health endpoint."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


DESKTOP = Path(__file__).resolve().parent.parent
EXECUTABLE = DESKTOP / "dist-api" / "olladex-api" / ("olladex-api.exe" if os.name == "nt" else "olladex-api")


def main() -> None:
    if not EXECUTABLE.is_file():
        raise SystemExit(f"Frozen API executable not found: {EXECUTABLE}")
    port = "18991"
    with tempfile.TemporaryDirectory(prefix="olladex-smoke-") as data_root:
        env = {**os.environ, "OLLADEX_DATA_ROOT": data_root, "OLLADEX_API_PORT": port}
        process = subprocess.Popen([str(EXECUTABLE)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            for _ in range(80):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                        payload = json.load(response)
                    if payload.get("status") == "ok" and payload.get("version"):
                        print(json.dumps(payload))
                        return
                except Exception:
                    time.sleep(0.25)
            output = process.stdout.read().decode("utf-8", errors="replace") if process.stdout else ""
            raise SystemExit(f"Frozen API health check failed\n{output[-4000:]}")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
