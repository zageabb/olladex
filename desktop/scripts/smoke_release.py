"""Smoke-test the frozen API and standalone frontend on the build host."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


DESKTOP = Path(__file__).resolve().parent.parent
ROOT = DESKTOP.parent


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_json(url: str, attempts: int = 80) -> dict:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"Service did not become healthy: {url}")


def wait_page(url: str, attempts: int = 80) -> None:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200 and b"Olladex" in response.read():
                    return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"Frontend did not become healthy: {url}")


def stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version")
    args = parser.parse_args()
    expected_version = args.expected_version or json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))["version"]
    executable = DESKTOP / "dist-api" / "olladex-api" / ("olladex-api.exe" if sys.platform == "win32" else "olladex-api")
    server = ROOT / "frontend" / ".next" / "standalone" / "server.js"
    if not executable.is_file() or not server.is_file():
        raise SystemExit("Build the API and standalone frontend before running the smoke test")
    api_port, ui_port = free_port(), free_port()
    with tempfile.TemporaryDirectory(prefix="olladex-release-smoke-") as data_root:
        api_env = {**os.environ, "OLLADEX_DATA_ROOT": data_root, "OLLADEX_API_PORT": str(api_port)}
        ui_env = {**os.environ, "HOSTNAME": "127.0.0.1", "PORT": str(ui_port), "NODE_ENV": "production"}
        api = subprocess.Popen([str(executable)], cwd=ROOT, env=api_env)
        ui = subprocess.Popen(["node", str(server)], cwd=server.parent, env=ui_env)
        try:
            health = wait_json(f"http://127.0.0.1:{api_port}/health")
            if health.get("version") != expected_version:
                raise RuntimeError(f"Expected API {expected_version}, received {health.get('version')}")
            wait_page(f"http://127.0.0.1:{ui_port}")
            print(f"Olladex {expected_version} packaged services healthy")
        finally:
            stop(ui)
            stop(api)


if __name__ == "__main__":
    main()
