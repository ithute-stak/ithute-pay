"""Run Ithute Pay Bridge API, web UI and background jobs in one container.

The database and Redis remain separate infrastructure services.  This module is
PID 1 and supervises the four application processes so container lifecycle and
signals remain predictable.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

APP_ROOT = Path("/app")
BACKEND_DIR = APP_ROOT / "backend"
FRONTEND_DIR = APP_ROOT / "frontend"


@dataclass(frozen=True)
class ProcessSpec:
    name: str
    command: Sequence[str]
    cwd: Path


def _run_migrations() -> None:
    if os.getenv("RUN_MIGRATIONS_ON_START", "true").lower() not in {"1", "true", "yes", "on"}:
        print("[supervisor] automatic Alembic migration disabled", flush=True)
        return

    print("[supervisor] applying Alembic migrations", flush=True)
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        check=True,
        env=os.environ.copy(),
    )
    print("[supervisor] migrations complete", flush=True)


def _specs() -> list[ProcessSpec]:
    return [
        ProcessSpec(
            "fastapi",
            [
                sys.executable,
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                os.getenv("BACKEND_HOST", "0.0.0.0"),
                "--port",
                os.getenv("BACKEND_PORT", "8001"),
                "--proxy-headers",
                "--forwarded-allow-ips",
                "*",
            ],
            BACKEND_DIR,
        ),
        ProcessSpec(
            "celery-worker",
            [
                "celery",
                "-A",
                "workers.celery_app.celery_app",
                "worker",
                "--loglevel=INFO",
            ],
            BACKEND_DIR,
        ),
        ProcessSpec(
            "celery-beat",
            [
                "celery",
                "-A",
                "workers.celery_app.celery_app",
                "beat",
                "--loglevel=INFO",
                "--schedule=/tmp/ithute-pay-bridge-celerybeat",
            ],
            BACKEND_DIR,
        ),
        ProcessSpec(
            "nextjs",
            ["node", "server.js"],
            FRONTEND_DIR,
        ),
    ]


def main() -> int:
    _run_migrations()

    processes: dict[str, subprocess.Popen[bytes]] = {}
    stopping = False

    def stop_all(signum: int | None = None, _frame: object | None = None) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        label = signal.Signals(signum).name if signum else "shutdown"
        print(f"[supervisor] {label}: stopping application processes", flush=True)
        for name, process in processes.items():
            if process.poll() is None:
                print(f"[supervisor] terminating {name} pid={process.pid}", flush=True)
                process.terminate()

    signal.signal(signal.SIGTERM, stop_all)
    signal.signal(signal.SIGINT, stop_all)

    try:
        for spec in _specs():
            print(f"[supervisor] starting {spec.name}: {' '.join(spec.command)}", flush=True)
            process = subprocess.Popen(
                list(spec.command),
                cwd=spec.cwd,
                env=os.environ.copy(),
            )
            processes[spec.name] = process

        while not stopping:
            for name, process in processes.items():
                code = process.poll()
                if code is not None:
                    print(f"[supervisor] {name} exited unexpectedly with code {code}", flush=True)
                    stop_all()
                    stopping = True
                    break
            if not stopping:
                time.sleep(1)
    finally:
        stop_all()
        deadline = time.monotonic() + 15
        for process in processes.values():
            if process.poll() is None:
                remaining = max(0.0, deadline - time.monotonic())
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    process.kill()
        for process in processes.values():
            if process.poll() is None:
                process.kill()
        for process in processes.values():
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    nonzero = [process.returncode for process in processes.values() if process.returncode not in (None, 0, -15)]
    return int(nonzero[0]) if nonzero else 0


if __name__ == "__main__":
    raise SystemExit(main())
