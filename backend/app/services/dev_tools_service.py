"""Local development utilities (restart backend, etc.)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESTART_SCRIPT = PROJECT_ROOT / "scripts" / "restart-backend.ps1"


def schedule_backend_restart() -> dict[str, str | None]:
    if sys.platform != "win32":
        raise RuntimeError("Backend restart is only supported on Windows in this workbench.")
    if not RESTART_SCRIPT.is_file():
        raise FileNotFoundError(f"Restart script not found: {RESTART_SCRIPT}")

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]

    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(RESTART_SCRIPT),
        ],
        cwd=str(PROJECT_ROOT),
        creationflags=creationflags,
        close_fds=True,
    )
    return {
        "status": "restarting",
        "message": "Backend restart scheduled. Expect ~5–10 seconds of downtime.",
        "script": str(RESTART_SCRIPT),
    }
