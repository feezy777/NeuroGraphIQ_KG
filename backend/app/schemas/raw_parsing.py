"""Pydantic schemas for Raw Parsing for AAL3.

Raw labels are NOT candidate entities and NOT final brain regions.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ParserKey(str, Enum):
    aal3_xml = "aal3_xml"
    aal3_label_table = "aal3_label_table"
    macro96_xlsx = "macro96_xlsx"


class ParseRunStatus(str, Enum):
    created = "created"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class Laterality(str, Enum):
    left = "left"
    right = "right"
    bilateral = "bilateral"
    midline = "midline"
    unknown = "unknown"


class RawParseRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    batch_id: uuid.UUID
    resource_id: uuid.UUID
    parser_key: str
    parser_version: str
    status: ParseRunStatus
    input_file_ids: list[str]
    output_count: int
    warning_count: int
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RawAal3RegionLabelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parse_run_id: uuid.UUID
    batch_id: uuid.UUID
    resource_id: uuid.UUID
    source_file_id: uuid.UUID
    source_atlas: str
    source_version: str
    source_label_id: str | None
    label_value: int | None
    raw_name: str
    en_name: str | None
    cn_name: str | None
    laterality: Laterality
    region_base_name: str | None
    raw_payload: dict[str, Any]
    row_index: int
    created_at: datetime


class RawParsingOptionsResponse(BaseModel):
    parser_key: list[str]
    parse_run_status: list[str]
    laterality: list[str]


class ParseAal3Response(BaseModel):
    parse_run: RawParseRunRead
    output_count: int
    warning_count: int = 0


class RawParseRunListResponse(BaseModel):
    items: list[RawParseRunRead]
    total: int


class RawAal3LabelListResponse(BaseModel):
    items: list[RawAal3RegionLabelRead]
    total: int
    limit: int
    offset: int
