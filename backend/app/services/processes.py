import os
import signal
import subprocess


def terminate(process, grace=1):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass
        # Descendants may survive after their shell exits.
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
