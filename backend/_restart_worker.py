"""Detached restart worker for the NeuroGraphIQ backend (dev-only).

Launched by ``server_restart_service`` — ideally via WMI (Win32_Process.Create) so it
runs under WmiPrvSE and therefore escapes any kill-on-close job object the old server
belonged to. It waits for the old process to die and the port to free, then relaunches
``run_server.py`` with stdout/stderr redirected to a log file.

Argv: <old_pid> <port> <run_server_path> <backend_dir> <log_file>
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time


def _wait_port_free(port: int, attempts: int = 120, interval: float = 0.25) -> bool:
    for _ in range(attempts):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            return True
        except OSError:
            s.close()
            time.sleep(interval)
    return False


def main() -> None:
    if len(sys.argv) < 6:
        return
    old_pid = int(sys.argv[1])
    port = int(sys.argv[2])
    run_server = sys.argv[3]
    backend_dir = sys.argv[4]
    log_file = sys.argv[5]

    # Give the old server a moment to flush its HTTP response + self-exit.
    time.sleep(1.4)

    if sys.platform == "win32":
        os.system(f"taskkill /PID {old_pid} /F >NUL 2>&1")
    else:
        try:
            os.kill(old_pid, 15)
        except (ProcessLookupError, PermissionError):
            pass

    _wait_port_free(port)

    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
    except OSError:
        pass

    log = open(log_file, "ab", buffering=0)
    log.write(f"\n===== restart relaunch port={port} =====\n".encode())

    kwargs: dict = {"cwd": backend_dir, "stdout": log, "stderr": log, "stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP — no console; logs go to file.
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True

    subprocess.Popen([sys.executable, run_server, str(port)], **kwargs)


if __name__ == "__main__":
    main()
