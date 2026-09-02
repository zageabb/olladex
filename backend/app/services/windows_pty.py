from __future__ import annotations

import os
import subprocess


def available() -> bool:
    if os.name != "nt":
        return False
    try:
        import winpty  # noqa: F401
    except ImportError:
        return False
    return True


def spawn(args: list[str], cwd: str, env: dict[str, str], rows: int = 32, columns: int = 120):
    if not available():
        raise RuntimeError("ConPTY support is unavailable")
    from winpty import PtyProcess

    return PtyProcess.spawn(subprocess.list2cmdline(args), cwd=cwd, env=env, dimensions=(rows, columns))


def backend_name() -> str:
    if os.name != "nt":
        return "posix-pty"
    return "conpty" if available() else "windows-pipes"
