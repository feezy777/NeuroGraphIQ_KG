"""Final macro_clinical browser / query workbench schemas (Step 8.16)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FinalBrowserTargetType(str, Enum):
    region = "region"
    region_function = "region_function"
    circuit = "circuit"
    circuit_step = "circuit_step"
    circuit_function = "circuit_function"
    projection = "projection"
    projection_function = "projection_function"
    circuit_projection_membership = "circuit_projection_membership"
    triple = "triple"
    evidence = "evidence"


BROWSER_SEARCH_TARGET_TYPES = [
    FinalBrowserTargetType.circuit,
    FinalBrowserTargetType.circuit_step,
    FinalBrowserTargetType.projection,
    FinalBrowserTargetType.projection_function,
    FinalBrowserTargetType.circuit_projection_membership,
    FinalBrowserTargetType.region_function,
    FinalBrowserTargetType.circuit_function,
    FinalBrowserTargetType.triple,
    FinalBrowserTargetType.evidence,
]

OBJECT_DETAIL_TARGET_TYPES = [
    FinalBrowserTargetType.circuit,
    FinalBrowserTargetType.circuit_step,
    FinalBrowserTargetType.projection,
    FinalBrowserTargetType.projection_function,
    FinalBrowserTargetType.circuit_projection_membership,
    FinalBrowserTargetType.region_function,
    FinalBrowserTargetType.circuit_function,
    FinalBrowserTargetType.triple,
    FinalBrowserTargetType.evidence,
]


class FinalBrowserSearchRequest(BaseModel):
    query: str | None = None
    target_types: list[str] | None = None
    source_atlas: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    final_status: str | None = None
    region_candidate_id: uuid.UUID | None = None
    circuit_id: uuid.UUID | None = None
    projection_id: uuid.UUID | None = None
    include_inactive: bool = False
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class FinalBrowserSearchItem(BaseModel):
    target_type: str
    final_id: uuid.UUID
    final_uid: str | None = None
    label: str
    summary: str | None = None
    source_atlas: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    confidence: float | None = None
    final_status: str | None = None
    source_mirror_type: str | None = None
    source_mirror_id: uuid.UUID | None = None
    promotion_run_id: uuid.UUID | None = None
    created_at: datetime | None = None


class FinalBrowserSearchResponse(BaseModel):
    items: list[FinalBrowserSearchItem]
    total: int
    limit: int
    offset: int
    warnings: list[str] = Field(default_factory=list)


class FinalGraphNode(BaseModel):
    id: str
    type: str
    label: str
    final_id: uuid.UUID | None = None
    source_mirror_id: uuid.UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FinalGraphEdge(BaseModel):
    id: str
    type: str
    source: str
    target: str
    label: str | None = None
    predicate: str | None = None
    final_id: uuid.UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FinalGraphResponse(BaseModel):
    nodes: list[FinalGraphNode]
    edges: list[FinalGraphEdge]
    center_node_id: str | None = None
    warnings: list[str] = Field(default_factory=list)


class FinalProvenancePayload(BaseModel):
    source_mirror_type: str | None = None
    source_mirror_id: uuid.UUID | None = None
    promotion_run_id: uuid.UUID | None = None
    promotion_record_id: uuid.UUID | None = None
    promotion_record: dict[str, Any] | None = None
    validation_summary_json: dict[str, Any] = Field(default_factory=dict)
    review_summary_json: dict[str, Any] = Field(default_factory=dict)
    cross_validation_summary_json: dict[str, Any] = Field(default_factory=dict)
    dual_model_summary_json: dict[str, Any] = Field(default_factory=dict)
    provenance_json: dict[str, Any] = Field(default_factory=dict)
    final_status: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    mirror_link_available: bool = False


class FinalRegionNeighborhoodResponse(BaseModel):
    region_candidate_id: uuid.UUID
    region_label: str | None = None
    source_atlas: str | None = None
    granularity_level: str | None = None
    region_functions: list[dict[str, Any]] = Field(default_factory=list)
    circuits: list[dict[str, Any]] = Field(default_factory=list)
    circuit_steps: list[dict[str, Any]] = Field(default_factory=list)
    outgoing_projections: list[dict[str, Any]] = Field(default_factory=list)
    incoming_projections: list[dict[str, Any]] = Field(default_factory=list)
    undirected_projections: list[dict[str, Any]] = Field(default_factory=list)
    projection_functions: list[dict[str, Any]] = Field(default_factory=list)
    triples: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    graph: FinalGraphResponse = Field(default_factory=lambda: FinalGraphResponse(nodes=[], edges=[]))


class FinalCircuitDetailResponse(BaseModel):
    circuit: dict[str, Any]
    steps: list[dict[str, Any]] = Field(default_factory=list)
    memberships: list[dict[str, Any]] = Field(default_factory=list)
    projections: list[dict[str, Any]] = Field(default_factory=list)
    participant_regions: list[dict[str, Any]] = Field(default_factory=list)
    circuit_functions: list[dict[str, Any]] = Field(default_factory=list)
    projection_functions_summary: list[dict[str, Any]] = Field(default_factory=list)
    triples: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    provenance: FinalProvenancePayload
    graph: FinalGraphResponse = Field(default_factory=lambda: FinalGraphResponse(nodes=[], edges=[]))


class FinalProjectionDetailResponse(BaseModel):
    projection: dict[str, Any]
    source_region: dict[str, Any] | None = None
    target_region: dict[str, Any] | None = None
    memberships: list[dict[str, Any]] = Field(default_factory=list)
    circuits: list[dict[str, Any]] = Field(default_factory=list)
    projection_functions: list[dict[str, Any]] = Field(default_factory=list)
    triples: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    provenance: FinalProvenancePayload
    graph: FinalGraphResponse = Field(default_factory=lambda: FinalGraphResponse(nodes=[], edges=[]))


class FinalObjectDetailResponse(BaseModel):
    target_type: str
    final_id: uuid.UUID
    object: dict[str, Any]
    related_objects: list[dict[str, Any]] = Field(default_factory=list)
    triples: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    provenance: FinalProvenancePayload
    promotion_record: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
