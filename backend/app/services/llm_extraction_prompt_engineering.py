"""Shared prompt engineering helpers for LLM extraction (connection / projection / function)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.schemas.mirror_kg import ConnectionType, Directionality
from app.services.field_completion_prompt_engineering import estimate_prompt_tokens

EXTRACTION_PROMPT_DISPLAY_NAMES: dict[str, str] = {
    "same_granularity_connection_completion_v1": (
        "同粒度脑区连接提取（Same-granularity Brain Region Projection Extraction）"
    ),
    "connection_with_function": (
        "连接与连接功能组合抽取（Projection and Projection Function Composite Extraction）"
    ),
    "projection_to_functions_v1": "连接功能抽取（Projection Function Extraction）",
    "circuit_to_functions_extraction_v1": "回路功能抽取（Circuit-to-Functions Extraction）",
}

VALID_EVIDENCE_LEVELS = frozenset({"low", "moderate", "high", "insufficient"})
VALID_PROJECTION_TYPES = frozenset({"anatomical", "functional", "structural", "unknown"})
VALID_DIRECTIONALITY = frozenset({"directed", "bidirectional", "unknown"})
DEFAULT_PAIRS_PER_PACK = 20

CONNECTION_FAILURE_STATUSES = frozenset({
    "failed",
    "failed_provider_not_called",
    "failed_provider_not_configured",
    "failed_provider_error",
    "failed_provider_empty_response",
    "failed_parse_error",
    "failed_empty_prompt",
    "failed_no_output",
})


@dataclass
class ConnectionExecutionAudit:
    pair_count: int = 0
    pack_count: int = 0
    provider_call_count: int = 0
    provider_success_count: int = 0
    provider_error_count: int = 0
    provider_empty_response_count: int = 0
    prompt_built_count: int = 0
    prompt_sent_count: int = 0
    parsed_projection_count: int = 0
    parsed_no_connection_count: int = 0
    created_projection_count: int = 0
    updated_projection_count: int = 0
    model_call_count: int = 0
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    parse_error_count: int = 0
    # Transport-level failures (HTTP/timeout/429/5xx/network). Distinct from parse errors.
    provider_transport_error_count: int = 0
    # JSON parsed OK but did not match the expected schema.
    schema_error_count: int = 0
    # Items dropped during normalization (unknown/mismatched pair_id, missing ids, ...).
    rejected_item_count: int = 0
    pack_summaries: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair_count": self.pair_count,
            "pack_count": self.pack_count,
            "provider_call_count": self.provider_call_count,
            "provider_success_count": self.provider_success_count,
            "provider_error_count": self.provider_error_count,
            "provider_transport_error_count": self.provider_transport_error_count,
            "provider_empty_response_count": self.provider_empty_response_count,
            "prompt_built_count": self.prompt_built_count,
            "prompt_sent_count": self.prompt_sent_count,
            "parsed_projection_count": self.parsed_projection_count,
            "parsed_no_connection_count": self.parsed_no_connection_count,
            "created_projection_count": self.created_projection_count,
            "updated_projection_count": self.updated_projection_count,
            "model_call_count": self.model_call_count,
            "estimated_input_tokens": self.estimated_input_tokens,
            "estimated_output_tokens": self.estimated_output_tokens,
            "parse_error_count": self.parse_error_count,
            "schema_error_count": self.schema_error_count,
            "rejected_item_count": self.rejected_item_count,
            "pack_summaries": self.pack_summaries,
            "failed_pack_count": sum(
                1
                for p in self.pack_summaries
                if p.get("parse_error")
                or p.get("parse_error_type") in {"json_decode_error", "schema_error"}
            ),
            "response_received_count": sum(
                1 for p in self.pack_summaries if p.get("response_received")
            ),
        }


def prompt_display_name(prompt_key: str) -> str | None:
    return EXTRACTION_PROMPT_DISPLAY_NAMES.get(prompt_key)


def make_pair_id(source_id: uuid.UUID, target_id: uuid.UUID) -> str:
    a, b = sorted((str(source_id), str(target_id)))
    return f"{a}::{b}"


def parse_pair_id(pair_id: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    parts = pair_id.split("::")
    if len(parts) != 2:
        return None
    try:
        return uuid.UUID(parts[0]), uuid.UUID(parts[1])
    except ValueError:
        return None


def _region_acronym(candidate: Any) -> str | None:
    for attr in ("acronym", "std_name", "raw_name"):
        val = getattr(candidate, attr, None)
        if val:
            return str(val)
    return None


def build_compact_pair_records(
    candidates: list[Any],
    pairs: list[tuple[uuid.UUID, uuid.UUID]],
) -> list[dict[str, Any]]:
    cand_map = {c.id: c for c in candidates}
    first = candidates[0]
    records: list[dict[str, Any]] = []
    for src, tgt in pairs:
        sc = cand_map[src]
        tc = cand_map[tgt]
        records.append({
            "pair_id": make_pair_id(src, tgt),
            "source_region_candidate_id": str(src),
            "target_region_candidate_id": str(tgt),
            "source_region_name_en": sc.en_name,
            "source_region_name_cn": sc.cn_name,
            "source_region_acronym": _region_acronym(sc),
            "target_region_name_en": tc.en_name,
            "target_region_name_cn": tc.cn_name,
            "target_region_acronym": _region_acronym(tc),
            "granularity_level": sc.granularity_level or first.granularity_level,
            "source_atlas": sc.source_atlas or first.source_atlas,
        })
    return records


def pack_pair_records(
    pair_records: list[dict[str, Any]],
    *,
    pairs_per_pack: int = DEFAULT_PAIRS_PER_PACK,
) -> list[list[dict[str, Any]]]:
    if not pair_records:
        return []
    size = max(1, pairs_per_pack)
    return [pair_records[i:i + size] for i in range(0, len(pair_records), size)]


def _normalize_evidence_level(value: Any) -> str:
    level = str(value or "insufficient").strip().lower()
    return level if level in VALID_EVIDENCE_LEVELS else "insufficient"


def _normalize_directionality(value: Any) -> str:
    raw = str(value or Directionality.unknown).strip().lower()
    if raw in VALID_DIRECTIONALITY:
        return raw
    if raw in {Directionality.undirected, "undirected"}:
        return Directionality.bidirectional
    return Directionality.unknown


def _map_projection_type(value: Any) -> str:
    raw = str(value or "unknown").strip().lower()
    mapping = {
        "anatomical": ConnectionType.structural_connection,
        "functional": ConnectionType.functional_connectivity,
        "structural": ConnectionType.structural_connection,
        "projection": ConnectionType.projection,
        "unknown": ConnectionType.uncertain_connection,
        # Model-friendly aliases — the model may output enum-style values
        "structural_connection": ConnectionType.structural_connection,
        "functional_connectivity": ConnectionType.functional_connectivity,
        "effective_connectivity": ConnectionType.effective_connectivity,
        "association": ConnectionType.association,
        "coactivation": ConnectionType.coactivation,
        "uncertain_connection": ConnectionType.uncertain_connection,
        "connectivity": ConnectionType.functional_connectivity,
    }
    return mapping.get(raw, ConnectionType.uncertain_connection)


def _clamp_score(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _projection_record_to_connection(
    proj: dict[str, Any],
    *,
    allowed_pair_ids: set[str],
    pair_id_to_endpoints: dict[str, tuple[uuid.UUID, uuid.UUID]],
) -> tuple[dict[str, Any] | None, str | None]:
    pair_id = str(proj.get("pair_id") or "").strip()
    if not pair_id:
        return None, "missing pair_id"
    if pair_id not in allowed_pair_ids:
        return None, f"unknown pair_id {pair_id}"

    endpoint_ids = _item_endpoint_ids(proj)
    src_raw = endpoint_ids[0] if endpoint_ids else proj.get("source_region_candidate_id")
    tgt_raw = endpoint_ids[1] if endpoint_ids else proj.get("target_region_candidate_id")
    expected = pair_id_to_endpoints.get(pair_id)
    if expected is None:
        return None, f"pair_id {pair_id} not in pack"
    exp_src, exp_tgt = expected

    try:
        src = uuid.UUID(str(src_raw)) if src_raw else exp_src
        tgt = uuid.UUID(str(tgt_raw)) if tgt_raw else exp_tgt
    except (ValueError, TypeError, AttributeError):
        return None, f"invalid candidate ids for pair_id {pair_id}"

    if {str(src), str(tgt)} != {str(exp_src), str(exp_tgt)}:
        return None, f"pair_id {pair_id} candidate ids mismatch"

    strength_val = proj.get("strength_score")
    if strength_val is None:
        strength_val = proj.get("strength") or proj.get("weight")

    confidence_val = proj.get("confidence_score")
    if confidence_val is None:
        confidence_val = proj.get("confidence") or proj.get("score")

    evidence_text = proj.get("evidence_text") or proj.get("evidence") or proj.get("evidence_source")
    uncertainty = proj.get("uncertainty_reason") or proj.get("uncertainty") or proj.get("reason_uncertain")

    return {
        "pair_id": pair_id,
        "source_candidate_id": str(src),
        "target_candidate_id": str(tgt),
        "connection_type": _map_projection_type(
            proj.get("projection_type") or proj.get("relation_type") or proj.get("connection_type")
        ),
        "directionality": _normalize_directionality(proj.get("directionality")),
        "strength": str(strength_val) if strength_val is not None else None,
        "modality": proj.get("modality"),
        "confidence": _clamp_score(confidence_val),
        "evidence_level": _normalize_evidence_level(proj.get("evidence_level")),
        "evidence_text": evidence_text,
        "uncertainty_reason": uncertainty,
        "description": proj.get("description"),
        "raw": proj,
    }, None


_PROJECTION_KEY_ALIASES = ("projections", "projection", "connections", "edges", "relations", "links")
_NO_CONNECTION_KEY_ALIASES = ("no_connections", "no_connection", "no_edges", "no_relations", "absent_connections")

_SOURCE_ID_KEYS = (
    "source_region_candidate_id",
    "source_candidate_id",
    "source_id",
    "source_region_id",
    "from_region_id",
)
_TARGET_ID_KEYS = (
    "target_region_candidate_id",
    "target_candidate_id",
    "target_id",
    "target_region_id",
    "to_region_id",
)


def _item_endpoint_ids(item: dict[str, Any]) -> tuple[Any, Any] | None:
    src = next((item.get(k) for k in _SOURCE_ID_KEYS if item.get(k)), None)
    tgt = next((item.get(k) for k in _TARGET_ID_KEYS if item.get(k)), None)
    if not src or not tgt:
        return None
    return src, tgt


def _coerce_pair_id_from_endpoints(
    item: dict[str, Any],
    pair_id_to_endpoints: dict[str, tuple[uuid.UUID, uuid.UUID]],
) -> str | None:
    """If an item lacks pair_id but carries source/target ids, recover the pair_id."""
    endpoints = _item_endpoint_ids(item)
    if not endpoints:
        return None
    src, tgt = endpoints
    try:
        want = {str(uuid.UUID(str(src))), str(uuid.UUID(str(tgt)))}
    except (ValueError, TypeError, AttributeError):
        return None
    for pid, (a, b) in pair_id_to_endpoints.items():
        if {str(a), str(b)} == want:
            return pid
    return None


def normalize_connection_extraction_payload(
    parsed: Any,
    *,
    pair_id_to_endpoints: dict[str, tuple[uuid.UUID, uuid.UUID]] | None = None,
) -> dict[str, Any]:
    """Normalize aliased / array-shaped provider payloads to the canonical
    ``{"projections": [...], "no_connections": [...], "warnings": [...]}`` schema.

    Handles:
      - top-level array (or our ``{"_array": [...]}`` wrapper) → projections;
      - singular/aliased keys (projection/connections/edges/relations);
      - no_connection/no_edges aliases;
      - recovering pair_id from source/target ids when missing.
    """
    endpoints = pair_id_to_endpoints or {}

    # Top-level array → treat each element as a projection.
    if isinstance(parsed, list):
        parsed = {"projections": parsed}
    elif isinstance(parsed, dict) and isinstance(parsed.get("_array"), list):
        parsed = {"projections": parsed["_array"]}
    elif not isinstance(parsed, dict):
        return {"projections": [], "no_connections": [], "warnings": ["payload is not an object/array"]}

    projections: list[Any] = []
    for key in _PROJECTION_KEY_ALIASES:
        val = parsed.get(key)
        if isinstance(val, list):
            projections = val
            break

    no_connections: list[Any] = []
    for key in _NO_CONNECTION_KEY_ALIASES:
        val = parsed.get(key)
        if isinstance(val, list):
            no_connections = val
            break

    # Recover missing pair_id from endpoints where possible.
    for item in projections:
        if isinstance(item, dict) and not item.get("pair_id"):
            recovered = _coerce_pair_id_from_endpoints(item, endpoints)
            if recovered:
                item["pair_id"] = recovered
    for item in no_connections:
        if isinstance(item, dict) and not item.get("pair_id"):
            recovered = _coerce_pair_id_from_endpoints(item, endpoints)
            if recovered:
                item["pair_id"] = recovered

    warnings = parsed.get("warnings")
    return {
        "projections": projections,
        "no_connections": no_connections,
        "warnings": warnings if isinstance(warnings, list) else [],
    }


def normalize_projection_extraction_response(
    parsed: dict[str, Any],
    *,
    allowed_pair_ids: set[str],
    pair_id_to_endpoints: dict[str, tuple[uuid.UUID, uuid.UUID]],
    allowed_connection_types: frozenset[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], set[str]]:
    """Return connections, no_connections, warnings, handled_pair_ids."""
    del allowed_connection_types  # legacy compat; mapping uses projection_type
    warnings: list[str] = []
    connections: list[dict[str, Any]] = []
    no_connections: list[dict[str, Any]] = []
    handled_pair_ids: set[str] = set()

    raw_projections = parsed.get("projections")
    if isinstance(raw_projections, list):
        for idx, proj in enumerate(raw_projections):
            if not isinstance(proj, dict):
                warnings.append(f"projections[{idx}] skipped: not an object")
                continue
            conn, err = _projection_record_to_connection(
                proj,
                allowed_pair_ids=allowed_pair_ids,
                pair_id_to_endpoints=pair_id_to_endpoints,
            )
            if err:
                warnings.append(f"projections[{idx}] rejected: {err}")
                continue
            pair_id = str(conn["pair_id"])
            if pair_id in handled_pair_ids:
                warnings.append(f"projections[{idx}] skipped: duplicate pair_id")
                continue
            handled_pair_ids.add(pair_id)
            connections.append(conn)

        raw_no = parsed.get("no_connections")
        if isinstance(raw_no, list):
            for idx, row in enumerate(raw_no):
                if not isinstance(row, dict):
                    warnings.append(f"no_connections[{idx}] skipped: not an object")
                    continue
                pair_id = str(row.get("pair_id") or "").strip()
                if not pair_id:
                    warnings.append(f"no_connections[{idx}] skipped: missing pair_id")
                    continue
                if pair_id not in allowed_pair_ids:
                    warnings.append(f"no_connections[{idx}] rejected: unknown pair_id")
                    continue
                if pair_id in handled_pair_ids:
                    warnings.append(f"no_connections[{idx}] skipped: duplicate pair_id")
                    continue
                handled_pair_ids.add(pair_id)
                no_connections.append({
                    "pair_id": pair_id,
                    "source_region_candidate_id": row.get("source_region_candidate_id"),
                    "target_region_candidate_id": row.get("target_region_candidate_id"),
                    "reason": row.get("reason"),
                })
        return connections, no_connections, warnings, handled_pair_ids

    # Legacy schema: connections[]
    raw_connections = parsed.get("connections")
    if raw_connections is None:
        return [], [], ["projections/no_connections and connections both missing; treating as empty"], set()
    if not isinstance(raw_connections, list):
        raise ValueError("connections must be an array")

    for idx, conn in enumerate(raw_connections):
        if not isinstance(conn, dict):
            warnings.append(f"connections[{idx}] skipped: not an object")
            continue
        try:
            src = uuid.UUID(str(conn.get("source_candidate_id")))
            tgt = uuid.UUID(str(conn.get("target_candidate_id")))
        except (ValueError, TypeError, AttributeError):
            warnings.append(f"connections[{idx}] skipped: invalid candidate ids")
            continue
        pair_id = make_pair_id(src, tgt)
        if pair_id not in allowed_pair_ids:
            warnings.append(f"connections[{idx}] skipped: pair not in current pack")
            continue
        if pair_id in handled_pair_ids:
            warnings.append(f"connections[{idx}] skipped: duplicate pair_id")
            continue
        handled_pair_ids.add(pair_id)
        connections.append({
            "pair_id": pair_id,
            "source_candidate_id": str(src),
            "target_candidate_id": str(tgt),
            "connection_type": str(conn.get("connection_type") or ConnectionType.unknown),
            "directionality": _normalize_directionality(conn.get("directionality")),
            "strength": conn.get("strength"),
            "modality": conn.get("modality"),
            "confidence": _clamp_score(conn.get("confidence")),
            "evidence_text": conn.get("evidence_text"),
            "uncertainty_reason": conn.get("uncertainty_reason"),
            "raw": conn,
        })
    return connections, no_connections, warnings, handled_pair_ids


def determine_connection_extraction_status(
    *,
    pair_count: int,
    connection_count: int,
    no_connection_count: int,
    unprocessed_pair_count: int,
    provider_failed: bool,
) -> str:
    """Legacy wrapper — prefer finalize_connection_extraction_status."""
    audit = ConnectionExecutionAudit(
        pair_count=pair_count,
        pack_count=1 if pair_count > 0 else 0,
        provider_call_count=1 if pair_count > 0 and not provider_failed else 0,
        prompt_sent_count=1 if pair_count > 0 and not provider_failed else 0,
        provider_success_count=1 if pair_count > 0 and not provider_failed else 0,
        parsed_projection_count=connection_count,
        parsed_no_connection_count=no_connection_count,
        provider_error_count=1 if provider_failed else 0,
        provider_transport_error_count=1 if provider_failed else 0,
    )
    status, _ = finalize_connection_extraction_status(
        dry_run=False,
        audit=audit,
        processed_pair_count=max(0, pair_count - unprocessed_pair_count),
        unprocessed_pair_count=unprocessed_pair_count,
        connection_count=connection_count,
        no_connection_count=no_connection_count,
        mirror_output_count=connection_count,
    )
    return status


def finalize_connection_extraction_status(
    *,
    dry_run: bool,
    audit: ConnectionExecutionAudit,
    processed_pair_count: int,
    unprocessed_pair_count: int,
    connection_count: int,
    no_connection_count: int,
    mirror_output_count: int,
) -> tuple[str, list[str]]:
    from app.schemas.llm_extraction import LlmRunStatus

    warnings: list[str] = []
    if dry_run:
        return LlmRunStatus.succeeded, warnings

    if audit.pair_count > 0 and audit.pack_count == 0:
        warnings.append("No prompt packs built although pair_count>0.")
        return LlmRunStatus.failed_empty_prompt, warnings

    if audit.pair_count > 0 and audit.provider_call_count == 0:
        warnings.append(
            "Provider was not called for connection extraction although dry_run=false and pair_count>0."
        )
        return LlmRunStatus.failed_provider_not_called, warnings

    if audit.pair_count > 0 and audit.prompt_sent_count == 0:
        warnings.append(
            "No prompts were sent to the provider although dry_run=false and pair_count>0."
        )
        return LlmRunStatus.failed_provider_not_called, warnings

    # Transport-level failure only counts when NO content ever came back.
    # provider_success_count is incremented whenever the wire returned content,
    # so pure parse failures (content received but unparseable) never land here.
    if audit.provider_transport_error_count > 0 and audit.provider_success_count == 0:
        return LlmRunStatus.failed_provider_error, warnings

    # Content was received but could not be parsed / did not match schema and
    # produced no usable output → parse error, NOT transport error.
    if (
        (audit.parse_error_count > 0 or audit.schema_error_count > 0)
        and audit.parsed_projection_count == 0
        and audit.parsed_no_connection_count == 0
    ):
        return LlmRunStatus.failed_parse_error, warnings

    if (
        audit.provider_empty_response_count > 0
        and audit.parsed_projection_count == 0
        and audit.parsed_no_connection_count == 0
        and processed_pair_count == 0
    ):
        return LlmRunStatus.failed_provider_empty_response, warnings

    if unprocessed_pair_count > 0:
        return LlmRunStatus.partially_succeeded, warnings

    all_no_connections = (
        connection_count == 0
        and no_connection_count >= audit.pair_count > 0
        and processed_pair_count >= audit.pair_count
    )
    if all_no_connections:
        return LlmRunStatus.succeeded_no_edges, warnings

    if mirror_output_count == 0 and connection_count == 0 and no_connection_count == 0:
        return LlmRunStatus.failed_no_output, warnings

    if mirror_output_count == 0 and connection_count == 0 and not all_no_connections:
        return LlmRunStatus.failed_no_output, warnings

    if connection_count > 0 and mirror_output_count == 0:
        return LlmRunStatus.partially_succeeded, warnings

    return LlmRunStatus.succeeded, warnings


def build_connection_prompt_preview(
    *,
    prompt_key: str,
    pair_count: int,
    packs: list[list[dict[str, Any]]],
    system_prompt: str,
    sample_user_prompt: str,
    processed_pair_count: int = 0,
    unprocessed_pair_count: int = 0,
    no_connection_count: int = 0,
    model_call_count: int | None = None,
    execution_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pack_summaries = []
    total_est_input = estimate_prompt_tokens(system_prompt)
    for idx, pack in enumerate(packs):
        pairs_json = json.dumps(pack, ensure_ascii=False)
        est = estimate_prompt_tokens(system_prompt) + estimate_prompt_tokens(sample_user_prompt.replace("{{pairs_json}}", pairs_json))
        pack_summaries.append({
            "pack_index": idx,
            "pair_count": len(pack),
            "estimated_input_tokens": est,
        })
        total_est_input += estimate_prompt_tokens(pairs_json)
    calls = model_call_count if model_call_count is not None else len(packs)
    preview: dict[str, Any] = {
        "prompt_key": prompt_key,
        "prompt_display_name": prompt_display_name(prompt_key),
        "pair_count": pair_count,
        "pack_count": len(packs),
        "processed_pair_count": processed_pair_count,
        "unprocessed_pair_count": unprocessed_pair_count,
        "no_connection_count": no_connection_count,
        "estimated_input_tokens": total_est_input,
        "estimated_output_tokens": max(256, pair_count * 48),
        "model_call_count": calls,
        "packs": pack_summaries,
        "compact_context_fields": [
            "pair_id",
            "source_region_candidate_id",
            "target_region_candidate_id",
            "source_region_name_en",
            "source_region_name_cn",
            "source_region_acronym",
            "target_region_name_en",
            "target_region_name_cn",
            "target_region_acronym",
            "granularity_level",
            "source_atlas",
        ],
    }
    if execution_summary:
        preview["execution_summary"] = execution_summary
        for key in (
            "provider_call_count",
            "provider_success_count",
            "provider_error_count",
            "provider_empty_response_count",
            "created_projection_count",
            "parsed_projection_count",
        ):
            if key in execution_summary:
                preview[key] = execution_summary[key]
    return preview
