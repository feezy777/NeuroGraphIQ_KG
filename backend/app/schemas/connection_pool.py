"""Connection pool Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ConnectionPoolMembershipRead(BaseModel):
    id: uuid.UUID
    pool_id: uuid.UUID
    connection_id: uuid.UUID
    added_source: str = "manual"
    added_at: datetime

    model_config = {"from_attributes": True}


class ConnectionPoolRead(BaseModel):
    id: uuid.UUID
    name: str | None = None
    scope_atlas: str
    scope_granularity: str
    source: str = "manual"
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    connection_count: int = 0
    created_at: datetime
    updated_at: datetime
    memberships: list[ConnectionPoolMembershipRead] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ConnectionPoolListResponse(BaseModel):
    items: list[ConnectionPoolRead]
    total: int


class ConnectionPoolCreateRequest(BaseModel):
    name: str | None = None
    connection_ids: list[uuid.UUID]
    scope_atlas: str
    scope_granularity: str
    source: str = "manual"
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None


class ConnectionPoolReplaceRequest(BaseModel):
    name: str | None = None
    connection_ids: list[uuid.UUID]
    scope_atlas: str
    scope_granularity: str
    source: str = "manual"
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None


class ConnectionPoolMembersRequest(BaseModel):
    connection_ids: list[uuid.UUID]


class ConnectionPoolMembersDeleteRequest(BaseModel):
    connection_ids: list[uuid.UUID]
