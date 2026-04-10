from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class FileStatus(str, Enum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED_SUCCESS = "parsed_success"
    PARSED_FAILED = "parsed_failed"
    EXTRACTING_REGIONS = "extracting_regions"
    EXTRACTION_SUCCESS = "extraction_success"
    EXTRACTION_FAILED = "extraction_failed"
    PENDING_REVIEW = "pending_review"
    COMMITTED = "committed"
    DISCARDED = "discarded"


class TaskType(str, Enum):
    PARSE = "parse"
    EXTRACT_REGION = "extract_region"
    EXTRACT_CIRCUIT = "extract_circuit"
    EXTRACT_CONNECTION = "extract_connection"
    REVIEW_REGION = "review_region"
    REVIEW_CIRCUIT = "review_circuit"
    REVIEW_CONNECTION = "review_connection"
    STAGE_UNVERIFIED = "stage_unverified"
    STAGE_CIRCUIT_UNVERIFIED = "stage_circuit_unverified"
    STAGE_CONNECTION_UNVERIFIED = "stage_connection_unverified"
    VALIDATE_UNVERIFIED = "validate_unverified"
    VALIDATE_CIRCUIT_UNVERIFIED = "validate_circuit_unverified"
    VALIDATE_CONNECTION_UNVERIFIED = "validate_connection_unverified"
    PROMOTE_FINAL = "promote_final"
    PROMOTE_CIRCUIT_FINAL = "promote_circuit_final"
    PROMOTE_CONNECTION_FINAL = "promote_connection_final"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class FileRecord:
    file_id: str
    filename: str
    file_type: str
    size_bytes: int
    path: str
    created_at: str
    updated_at: str
    status: str = FileStatus.UPLOADED.value
    version: int = 1
    latest_parse_task_id: str = ""
    latest_extract_task_id: str = ""
    latest_commit_task_id: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentChunk:
    chunk_id: str
    file_id: str
    chunk_type: str
    chunk_index: int
    text_content: str
    page_no: int | None = None
    source_ref: str = ""
    extra_json: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    parsed_document_id: str
    file_id: str
    parse_status: str
    file_type: str
    title: str
    source: str
    authors: List[str]
    year: Optional[int]
    doi: str
    page_range: str
    raw_text: str = ""
    metadata_json: Dict[str, Any] = field(default_factory=dict)
    paragraphs: List[str] = field(default_factory=list)
    sentences: List[str] = field(default_factory=list)
    table_cells: List[Dict[str, Any]] = field(default_factory=list)
    figure_captions: List[str] = field(default_factory=list)
    heading_levels: List[Dict[str, Any]] = field(default_factory=list)
    ocr_blocks: List[Dict[str, Any]] = field(default_factory=list)
    parser_name: str = "parser_placeholder"
    parser_version: str = "v0"
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class CandidateEntity:
    entity_id: str
    name: str
    entity_type: str
    confidence: float
    source_chunk_ids: List[str]
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CandidateRelation:
    relation_id: str
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    confidence: float
    source_chunk_ids: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CandidateConnection:
    id: str
    file_id: str
    parsed_document_id: str
    source_text: str = ""
    en_name_candidate: str = ""
    cn_name_candidate: str = ""
    alias_candidates: List[str] = field(default_factory=list)
    description_candidate: str = ""
    granularity_candidate: str = "unknown"
    connection_modality_candidate: str = "unknown"
    source_region_ref_candidate: str = ""
    target_region_ref_candidate: str = ""
    confidence: float = 0.0
    direction_label: str = "unknown"
    extraction_method: str = "local_rule"
    llm_model: str = ""
    status: str = "pending_review"
    review_note: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class CandidateCircuit:
    id: str
    file_id: str
    parsed_document_id: str
    source_text: str = ""
    en_name_candidate: str = ""
    cn_name_candidate: str = ""
    alias_candidates: List[str] = field(default_factory=list)
    description_candidate: str = ""
    circuit_kind_candidate: str = "unknown"
    loop_type_candidate: str = "inferred"
    cycle_verified_candidate: bool = False
    confidence_circuit: float = 0.0
    granularity_candidate: str = "unknown"
    extraction_method: str = "local_rule"
    llm_model: str = ""
    status: str = "pending_review"
    review_note: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class CandidateCircuitNode:
    id: str
    candidate_circuit_id: str
    region_id_candidate: str
    granularity_candidate: str = "unknown"
    node_order: int = 1
    role_label: str = ""


@dataclass
class ValidationRun:
    run_id: str
    file_id: str
    structure_check: Dict[str, Any]
    ontology_rule_check: Dict[str, Any]
    model_coarse_check: Dict[str, Any]
    multi_model_review: Dict[str, Any]
    overall_label: str
    overall_score: float
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class GranularityMapping:
    mapping_id: str
    file_id: str
    major_regions: List[Dict[str, Any]] = field(default_factory=list)
    sub_regions: List[Dict[str, Any]] = field(default_factory=list)
    allen_regions: List[Dict[str, Any]] = field(default_factory=list)
    connections: List[Dict[str, Any]] = field(default_factory=list)
    circuits: List[Dict[str, Any]] = field(default_factory=list)
    functions: List[Dict[str, Any]] = field(default_factory=list)
    evidences: List[Dict[str, Any]] = field(default_factory=list)
    cross_granularity_edges: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class ModelConfig:
    config_id: str
    deepseek_enabled: bool
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    routing_policy: str = "single_model"
    param_version: str = "v0"
    deepseek_temperature: float = 0.2
    task_overrides: Dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class CandidateRegion:
    id: str
    file_id: str
    parsed_document_id: str
    chunk_id: str = ""
    source_text: str = ""
    en_name_candidate: str = ""
    cn_name_candidate: str = ""
    alias_candidates: List[str] = field(default_factory=list)
    laterality_candidate: str = ""
    region_category_candidate: str = ""
    granularity_candidate: str = "unknown"
    parent_region_candidate: str = ""
    ontology_source_candidate: str = ""
    confidence: float = 0.0
    extraction_method: str = "local_rule"
    llm_model: str = ""
    status: str = "pending_review"
    review_note: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class ReviewRecord:
    id: str
    candidate_region_id: str
    reviewer: str
    action: str
    before_json: Dict[str, Any]
    after_json: Dict[str, Any]
    note: str = ""
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class TaskRun:
    task_id: str
    task_type: str
    initiator: str
    input_objects: Dict[str, Any]
    model_or_rule_version: str
    parameters: Dict[str, Any]
    trigger_source: str = "ui"
    model_name: str = ""
    status: str = TaskStatus.QUEUED.value
    started_at: str = ""
    ended_at: str = ""
    error_reason: str = ""
    output_summary: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskLog:
    log_id: str
    run_id: str
    level: str
    event_type: str
    message: str
    module: str
    detail_json: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


def model_to_dict(model_obj: Any) -> Dict[str, Any]:
    return asdict(model_obj)
