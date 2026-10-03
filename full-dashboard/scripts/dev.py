"""Launch the local API and React dashboard without importing live channels."""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not python.exists() or npm is None or not (ROOT / "frontend/node_modules").is_dir():
        print("Install uv and Node.js 22.12+, then run make setup first.", file=sys.stderr)
        return 1
    for port in (8517, 8508):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                print(
                    f"Port {port} is already in use. Stop that local service first.",
                    file=sys.stderr,
                )
                return 1
    env = os.environ.copy()
    env.update(
        SEND_MODE="dry_run",
        ACTION_MODE="dry_run",
        SLACK_POST_MODE="dry_run",
        LLM_ENABLED="false",
        OPENAI_AGENTS_DISABLE_TRACING="1",
        PYTHONUNBUFFERED="1",
    )
    children: list[subprocess.Popen] = []

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    options = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    try:
        children.append(
            subprocess.Popen(
                [
                    str(python),
                    "-m",
                    "uvicorn",
                    "support.api:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8517",
                ],
                cwd=ROOT,
                env=env,
                **options,
            )
        )
        children.append(
            subprocess.Popen([npm, "run", "dev"], cwd=ROOT / "frontend", env=env, **options)
        )
        print(
            "Dashboard: http://127.0.0.1:8508/\nAPI: http://127.0.0.1:8517/health\nSafe mode is locked on; model calls are off. Ctrl+C stops both services.",
            flush=True,
        )
        while all(child.poll() is None for child in children):
            time.sleep(0.2)
        return (
            next((child.returncode for child in children if child.returncode is not None), 1) or 1
        )
    except KeyboardInterrupt:
        return 0
    finally:
        for child in children:
            try:
                if os.name == "nt" and child.poll() is None:
                    child.terminate()
                elif os.name != "nt":
                    os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    child.kill()
                else:
                    os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
