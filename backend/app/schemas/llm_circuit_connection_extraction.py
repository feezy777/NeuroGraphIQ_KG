"""Pydantic schemas for Circuit -> Connection LLM extraction."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.llm_field_completion import RunStatus


class ExtractionMode:
    MULTI = "multi_connection"
    MAIN_PAIR = "main_pair"


class CircuitConnectionExtractionRequest(BaseModel):
    mode: str = Field(default=ExtractionMode.MULTI, description="multi_connection | main_pair")
    circuit_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=500)
    dry_run: bool = Field(default=False)
    provider: str = Field(default="deepseek")
    model_name: str | None = None
    temperature: float = Field(default=0.2, ge=0, le=2.0)
    max_tokens: int = Field(default=2000, ge=1, le=65536)
    create_mirror_updates: bool = Field(default=True)
    overwrite_policy: str = Field(default="fill_missing_only")


class ExtractionItemRead(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    circuit_id: uuid.UUID | None
    source_region_name: str | None
    target_region_name: str | None
    source_candidate_id: uuid.UUID | None
    target_candidate_id: uuid.UUID | None
    connection_type: str | None
    confidence: float | None
    evidence_text: str | None
    connection_id: uuid.UUID | None
    action: str
    action_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ExtractionRunRead(BaseModel):
    id: uuid.UUID
    provider: str
    model_name: str | None
    mode: str
    circuit_count: int
    dry_run: bool
    create_mirror_updates: bool
    status: str
    summary_json: dict[str, Any]
    warnings_json: list[Any]
    errors_json: list[Any]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class ExtractionRunDetail(ExtractionRunRead):
    items: list[ExtractionItemRead] = []


class ExtractionRunListResponse(BaseModel):
    items: list[ExtractionRunRead]
    total: int


class ExtractionStartResponse(BaseModel):
    run_id: uuid.UUID
    status: str
    provider: str
    model_name: str | None
    mode: str
    circuit_count: int
    dry_run: bool
    warnings: list[str] = []
