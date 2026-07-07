"""Dev-only workbench utilities."""

from __future__ import annotations

from pydantic import BaseModel


class BackendRestartResponse(BaseModel):
    status: str
    message: str
    script: str | None = None
