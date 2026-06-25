"""Schemas for Workbench database administration (read/switch only).

Never exposes passwords or full DATABASE_URL to clients.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DatabaseSchemaStatus(str, Enum):
    mvp1_ready = "mvp1_ready"
    legacy = "legacy"
    partial = "partial"
    empty = "empty"
    unreachable = "unreachable"


class DatabaseConnectionInfo(BaseModel):
    host: str
    port: int
    user: str
    current_database: str
    connected: bool
    schema_status: DatabaseSchemaStatus
    missing_tables: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class DatabaseListItem(BaseModel):
    name: str
    schema_status: DatabaseSchemaStatus
    is_current: bool
    missing_tables: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class DatabaseListResponse(BaseModel):
    host: str
    port: int
    current_database: str
    items: list[DatabaseListItem]


class DatabaseValidationResponse(BaseModel):
    database: str
    schema_status: DatabaseSchemaStatus
    missing_tables: list[str] = Field(default_factory=list)
    present_tables: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class DatabaseSwitchRequest(BaseModel):
    database: str = Field(min_length=1, max_length=128)


class DatabaseSwitchResponse(BaseModel):
    ok: bool
    previous_database: str
    current_database: str
    schema_status: DatabaseSchemaStatus
    message: str
