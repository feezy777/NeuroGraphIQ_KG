"""Pydantic schemas for Macro96 Raw Parsing.

Raw rows are NOT candidate entities and NOT final brain regions.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ParseMacro96Response(BaseModel):
    parse_run_id: uuid.UUID
    batch_id: uuid.UUID
    resource_id: uuid.UUID
    source_file_id: uuid.UUID
    intermediate_artifact_id: uuid.UUID | None
    parser_key: str
    parser_version: str
    row_count: int
    warning_count: int
    status: str


class RawMacro96RegionRowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parse_run_id: uuid.UUID
    resource_id: uuid.UUID
    batch_id: uuid.UUID
    source_file_id: uuid.UUID
    intermediate_artifact_id: uuid.UUID | None
    row_index: int
    region_index: int
    en_name: str
    cn_name: str | None
    source_sheet: str | None
    raw_payload: dict[str, Any]
    created_at: datetime


class RawMacro96RegionRowListResponse(BaseModel):
    items: list[RawMacro96RegionRowRead]
    total: int
    limit: int
    offset: int
