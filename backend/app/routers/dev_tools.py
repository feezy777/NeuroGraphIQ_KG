"""Dev-only workbench API (local development)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.schemas.dev_tools import BackendRestartResponse
from app.services import dev_tools_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/restart-backend", response_model=BackendRestartResponse)
async def restart_backend():
    settings = get_settings()
    if settings.app_env != "development":
        raise HTTPException(
            status_code=403,
            detail="Backend restart is only available when APP_ENV=development.",
        )
    try:
        data = dev_tools_service.schedule_backend_restart()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except OSError as exc:
        logger.exception("[dev-tools][restart-backend] failed to spawn script")
        raise HTTPException(status_code=500, detail=str(exc)[:500]) from exc
    return BackendRestartResponse.model_validate(data)
