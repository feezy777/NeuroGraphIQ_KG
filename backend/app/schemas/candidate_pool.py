"""Candidate Pool request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CandidatePoolCreate(BaseModel):
    name: str | None = None
    candidate_ids: list[uuid.UUID] = Field(..., min_length=2)
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str
    granularity_level: str
    granularity_family: str | None = None


class CandidatePoolReplace(CandidatePoolCreate):
    """Replace all members of the scope's active pool (create if missing). Idempotent."""


class CandidatePoolMembersAdd(BaseModel):
    candidate_ids: list[uuid.UUID] = Field(..., min_length=1)


class CandidatePoolMembersRemove(BaseModel):
    candidate_ids: list[uuid.UUID] = Field(..., min_length=1)


class CandidatePoolMembershipRead(BaseModel):
    id: uuid.UUID
    pool_id: uuid.UUID
    candidate_id: uuid.UUID
    added_at: datetime
    added_by: str | None = None

    model_config = {"from_attributes": True}


class CandidatePoolRead(BaseModel):
    id: uuid.UUID
    name: str | None = None
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str
    granularity_level: str
    granularity_family: str | None = None
    candidate_count: int
    pair_count: int
    status: str
    created_at: datetime
    updated_at: datetime
    memberships: list[CandidatePoolMembershipRead] = []

    model_config = {"from_attributes": True}
