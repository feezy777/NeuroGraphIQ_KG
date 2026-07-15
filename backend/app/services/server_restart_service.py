"""Dev-only backend self-restart (Windows-first).

Launches a detached "restart worker" that waits for the current server to exit
(freeing its port), then relaunches ``run_server.py``. The current process exits
gracefully once the HTTP response has been flushed.

The worker is preferably launched via WMI (``Win32_Process.Create``): a WMI-created
process runs under ``WmiPrvSE`` and therefore **escapes any kill-on-close job object**
the server lived in (e.g. a supervisor / task wrapper). Fallbacks: spawn with
``CREATE_BREAKAWAY_FROM_JOB``, then a plain detached spawn.

NOT for production — this is a local developer convenience so code changes can be
picked up without leaving the browser (reload is off by default on Windows).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# backend/ directory — this file is backend/app/services/server_restart_service.py
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_RUN_SERVER = _BACKEND_DIR / "run_server.py"
_RESTART_WORKER = _BACKEND_DIR / "_restart_worker.py"
_RESTART_LOG = _BACKEND_DIR / "logs" / "restart_server.log"
_DEFAULT_PORT = 8002

# Windows process-creation flags
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def detect_server_port() -> int:
    """Best-effort detection of the port this server is bound to.

    Mirrors run_server.py: env override → first numeric argv → default 8002.
    """
    env = (os.environ.get("WORKBENCH_PORT") or "").strip()
    if env.isdigit():
        return int(env)
    for arg in sys.argv[1:]:
        if str(arg).strip().isdigit():
            return int(str(arg).strip())
    return _DEFAULT_PORT


def _worker_argv(pid: int, port: int) -> list[str]:
    return [
        sys.executable,
        str(_RESTART_WORKER),
        str(pid),
        str(port),
        str(_RUN_SERVER),
        str(_BACKEND_DIR),
        str(_RESTART_LOG),
    ]


def _launch_worker_via_wmi(argv: list[str]) -> bool:
    """Launch the worker under WmiPrvSE so it escapes the caller's job object.

    Returns True on success. Windows only.
    """
    if sys.platform != "win32":
        return False
    # Build a single command line with each arg double-quoted.
    command_line = " ".join(f'"{a}"' for a in argv)
    cwd = str(_BACKEND_DIR)
    # Escape single quotes for embedding inside a PowerShell single-quoted string.
    cl_ps = command_line.replace("'", "''")
    cwd_ps = cwd.replace("'", "''")
    ps_script = (
        "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
        f"-Arguments @{{ CommandLine = '{cl_ps}'; CurrentDirectory = '{cwd_ps}' }}; "
        "exit [int]$r.ReturnValue"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            timeout=20,
        )
    except Exception as exc:  # noqa: BLE001 - fall back on any launcher error
        logger.warning("[restart] WMI launch failed to run: %s", exc)
        return False
    # Win32_Process.Create ReturnValue 0 == success.
    if result.returncode == 0:
        return True
    logger.warning(
        "[restart] WMI Create returned %s stderr=%s",
        result.returncode, (result.stderr or b"").decode(errors="replace")[:200],
    )
    return False


def _launch_worker_detached(argv: list[str]) -> None:
    """Fallback: spawn the worker directly, trying job-breakaway first."""
    if sys.platform == "win32":
        base_flags = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
        try:
            subprocess.Popen(
                argv, cwd=str(_BACKEND_DIR),
                creationflags=base_flags | _CREATE_BREAKAWAY_FROM_JOB,
                close_fds=True,
            )
            return
        except OSError:
            subprocess.Popen(
                argv, cwd=str(_BACKEND_DIR), creationflags=base_flags, close_fds=True,
            )
    else:
        subprocess.Popen(argv, cwd=str(_BACKEND_DIR), start_new_session=True, close_fds=True)


def schedule_server_restart(*, exit_delay: float = 0.8) -> dict:
    """Spawn the detached restart worker, then schedule this process to exit.

    Raises FileNotFoundError if run_server.py / the worker is missing.
    """
    if not _RUN_SERVER.exists():
        raise FileNotFoundError(f"run_server.py not found at {_RUN_SERVER}")
    if not _RESTART_WORKER.exists():
        raise FileNotFoundError(f"restart worker not found at {_RESTART_WORKER}")

    port = detect_server_port()
    pid = os.getpid()
    argv = _worker_argv(pid, port)

    launched_via = "wmi"
    if not _launch_worker_via_wmi(argv):
        launched_via = "detached"
        _launch_worker_detached(argv)

    # Graceful self-exit AFTER the response is flushed; the worker's taskkill is a
    # belt-and-suspenders fallback in case this timer never fires.
    threading.Timer(exit_delay, lambda: os._exit(0)).start()
    logger.warning(
        "[restart] scheduled pid=%s port=%s via=%s exit_in=%.1fs platform=%s",
        pid, port, launched_via, exit_delay, sys.platform,
    )
    return {"pid": pid, "port": port, "launched_via": launched_via, "exit_delay": exit_delay}
