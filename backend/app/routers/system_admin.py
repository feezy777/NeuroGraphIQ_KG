"""System administration API (dev-only).

Currently exposes a backend self-restart used by the Dashboard "Restart Backend"
button so local code changes are picked up without leaving the browser. NOT for
production deployment.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.services import server_restart_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/restart")
async def restart_backend():
    """Schedule a backend process restart and return immediately.

    The current process exits shortly after this response is flushed; a detached
    restarter relaunches ``run_server.py`` on the same port in a new console window.
    """
    try:
        info = server_restart_service.schedule_server_restart()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("[restart] failed to schedule restart")
        raise HTTPException(status_code=500, detail=f"restart failed: {exc}") from exc

    return {
        "status": "restarting",
        "pid": info["pid"],
        "port": info["port"],
        "launched_via": info.get("launched_via"),
        "message": (
            f"Backend restarting on port {info['port']} (worker via {info.get('launched_via')}); "
            "reconnect in a few seconds. Logs: backend/logs/restart_server.log"
        ),
    }
