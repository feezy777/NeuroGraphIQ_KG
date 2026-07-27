"""Molecular Circuit Extraction v2 Pydantic schemas.

Defines request/response models for the Molecular-granularity circuit extraction
pipeline: graph engine, module classifier, DeepSeek semantic judgment, quality
gate, and candidate pool storage.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class MolecularCircuitExtractionRequest(BaseModel):
    """Request to start a molecular circuit extraction run."""

    provider: str = "deepseek"
    model_name: str = "deepseek-v4-pro"
    functional_modules: list[str] | None = Field(
        default=None,
        description="If set, only process candidates in these modules. None = all modules.",
    )
    motif_types: list[str] | None = Field(
        default=None,
        description="If set, only generate candidates of these motif types. None = all types.",
    )
    min_path_length: int = Field(
        default=3, ge=2, le=8, description="Minimum path length (nodes) for open pathways."
    )
    max_path_length: int = Field(
        default=8, ge=3, le=12, description="Maximum path length (nodes) for open pathways."
    )
    include_low_confidence: bool = Field(
        default=True,
        description="Include low-confidence candidates in the pool (above confidence_floor).",
    )
    confidence_floor: float = Field(
        default=0.05, ge=0.0, le=1.0,
        description="Minimum pre-score threshold below which raw topologies are dropped.",
    )
    pack_candidate_limit: int = Field(
        default=150, ge=50, le=500,
        description="Max candidates per pack sent to LLM.",
    )
    pack_edge_limit: int = Field(
        default=400, ge=100, le=2000,
        description="Max relevant edges per pack (for context).",
    )
    pack_concurrency: int = Field(
        default=2, ge=1, le=8,
        description="Number of packs to process in parallel (LLM calls).",
    )
    retry_failed_only: bool = Field(
        default=False,
        description="If True, only re-process packs that failed in the previous run.",
    )
    dry_run: bool = Field(
        default=False,
        description="If True, run graph engine + module classifier + packing only, skip LLM.",
    )


# ---------------------------------------------------------------------------
# Start Response
# ---------------------------------------------------------------------------


class MolecularCircuitStartResponse(BaseModel):
    """Response returned immediately after starting a molecular circuit extraction run."""

    run_id: uuid.UUID
    status: str = "pending"
    candidate_count: int = 0
    pack_count: int = 0
    estimated_candidates: int = 0


# ---------------------------------------------------------------------------
# Run Read
# ---------------------------------------------------------------------------


class MolecularCircuitRunRead(BaseModel):
    """Full read model for a molecular circuit candidate run (GET response)."""

    id: uuid.UUID
    status: str
    provider: str | None = None
    model_name: str | None = None
    candidate_count: int | None = None
    pack_count: int | None = None
    total_raw_topologies: int | None = None
    total_passed: int | None = None
    total_failed: int | None = None
    high_confidence: int = 0
    medium_confidence: int = 0
    low_confidence: int = 0
    progress_json: dict[str, Any] = Field(default_factory=dict)
    result_summary_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Run List Response
# ---------------------------------------------------------------------------


class MolecularCircuitRunListResponse(BaseModel):
    """Paginated list of molecular circuit candidate runs."""

    items: list[MolecularCircuitRunRead]
    total: int


# ---------------------------------------------------------------------------
# Progress Response
# ---------------------------------------------------------------------------


class MolecularCircuitProgressResponse(BaseModel):
    """Real-time progress of a running molecular circuit extraction."""

    run_id: uuid.UUID
    status: str
    phase: str = Field(
        description="Current phase: graph_build | motif_generation | packing | llm_judgment | quality_gate | done"
    )
    progress_percent: float = Field(
        default=0.0, ge=0.0, le=100.0,
        description="Overall progress in percent.",
    )
    phase_stats: dict[str, Any] = Field(
        default_factory=dict,
        description="Phase-specific statistics keyed by metric name.",
    )


# ---------------------------------------------------------------------------
# Cancel / Pause / Resume
# ---------------------------------------------------------------------------


class MolecularCircuitActionResponse(BaseModel):
    """Response for cancel/pause/resume actions on a molecular circuit run."""

    run_id: uuid.UUID
    status: str
    message: str = ""


# ---------------------------------------------------------------------------
# Candidate List
# ---------------------------------------------------------------------------


class MolecularCircuitCandidateRead(BaseModel):
    """A single candidate in the mirror molecular circuit candidate pool."""

    id: uuid.UUID
    extraction_run_id: uuid.UUID | None = None
    pack_id: int
    canonical_key: str
    topology_type: str | None = None
    anatomical_pattern: str | None = None
    closed_loop: bool | None = None
    node_count: int | None = None
    edge_count: int | None = None
    name_en: str | None = None
    name_cn: str | None = None
    functional_module: list[Any] = Field(default_factory=list)
    known_status: str | None = None
    overall_confidence: float | None = None
    confidence_level: str | None = None
    topology_score: float | None = None
    anatomical_score: float | None = None
    functional_score: float | None = None
    evidence_score: float | None = None
    pre_score: float | None = None
    nodes_json: list[Any]
    edges_json: list[Any]
    llm_raw_response_json: dict[str, Any] = Field(default_factory=dict)
    validation_result_json: dict[str, Any] = Field(default_factory=dict)
    review_status: str = "candidate"
    parent_circuit_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MolecularCircuitCandidateListResponse(BaseModel):
    """Paginated list of molecular circuit candidates."""

    items: list[MolecularCircuitCandidateRead]
    total: int
