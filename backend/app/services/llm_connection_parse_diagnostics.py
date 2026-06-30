"""Connection extraction parse diagnostics, pack summaries, fail-fast, and replay."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app.services.llm_extraction_prompt_engineering import ConnectionExecutionAudit
from app.services.llm_json_utils import (
    LlmJsonParseError,
    parse_connection_completion_response,
    raw_response_preview,
)
from app.services.llm_extraction_prompt_engineering import (
    normalize_connection_extraction_payload,
    normalize_projection_extraction_response,
)

PROMPT_PREVIEW_MAX_CHARS = 1000
PACK_SUMMARY_MAX_RECENT = 20
PACK_SUMMARY_MIN_FAILED_KEEP = 3

FAIL_FAST_DEFAULT_ENABLED = True
FAIL_FAST_DEFAULT_THRESHOLD = 5
FAIL_FAST_DEFAULT_REASON = "first_3_packs_parse_error"

INVARIANT_PACK_SUMMARIES_MISSING = "PACK_SUMMARIES_MISSING_FOR_PARSE_ERRORS"
INVARIANT_PROVIDER_SUCCESS_INCONSISTENT = "PROVIDER_SUCCESS_COUNT_INCONSISTENT"
RAW_TEXT_MISSING_CODE = "raw_text_missing_after_provider_call"


def reassign_jsonb(obj: Any, attr: str, value: Any) -> Any:
    """Assign JSONB column via new dict/list and flag SQLAlchemy mutation."""
    setattr(obj, attr, value)
    flag_modified(obj, attr)
    return value


def upsert_pack_trace(pack_traces: list[dict[str, Any]], pack_summary: dict[str, Any]) -> list[dict[str, Any]]:
    finalized = finalize_pack_trace(pack_summary)
    pack_id = finalized.get("pack_id")
    for index, existing in enumerate(pack_traces):
        if existing.get("pack_id") == pack_id:
            pack_traces[index] = finalized
            return pack_traces
    pack_traces.append(finalized)
    return pack_traces


def build_initial_pack_summary(
    *,
    pack_id: int,
    pack_index: int,
    pack_count: int,
    pair_count: int,
    provider: str,
    model_name: str,
    prompt_key: str,
    prompt_display_name: str,
    prompt_preview_text: str = "",
    json_mode_enabled: Any = None,
) -> dict[str, Any]:
    return {
        "pack_id": pack_id,
        "pack_index": pack_index,
        "pack_count": pack_count,
        "pair_count": pair_count,
        "status": "started",
        "provider": provider,
        "model_name": model_name,
        "prompt_key": prompt_key,
        "prompt_display_name": prompt_display_name,
        "prompt_built": False,
        "prompt_sent": False,
        "provider_call_started": False,
        "provider_call_finished": False,
        "response_received": False,
        "response_char_count": 0,
        "raw_response_preview": None,
        "prompt_preview": prompt_preview(prompt_preview_text),
        "parse_error": None,
        "parse_error_type": None,
        "schema_error": None,
        "parsed_projection_count": 0,
        "parsed_no_connection_count": 0,
        "rejected_item_count": 0,
        "unprocessed_pair_count": pair_count,
        "retry_count": 0,
        "json_mode_enabled": json_mode_enabled,
    }


def validate_connection_progress_invariants(summary: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    parse_error_count = int(summary.get("parse_error_count") or 0)
    pack_summaries = summary.get("pack_summaries") or []
    provider_success_count = int(summary.get("provider_success_count") or 0)
    provider_empty_response_count = int(summary.get("provider_empty_response_count") or 0)
    transport_error_count = int(summary.get("provider_transport_error_count") or 0)

    if parse_error_count > 0 and not pack_summaries:
        errors.append({
            "code": INVARIANT_PACK_SUMMARIES_MISSING,
            "message": (
                "parse_error_count > 0 but pack_summaries is empty; "
                "raw response capture/persistence is broken."
            ),
        })
    if (
        parse_error_count > 0
        and provider_success_count == 0
        and provider_empty_response_count == 0
        and transport_error_count == 0
    ):
        errors.append({
            "code": INVARIANT_PROVIDER_SUCCESS_INCONSISTENT,
            "message": (
                "parse errors imply non-empty provider responses, but provider_success_count is 0."
            ),
        })
    return errors


def merge_provider_audit(summary: dict[str, Any]) -> dict[str, Any]:
    pack_summaries = summary.get("pack_summaries") or []
    audit = {
        "provider_call_count": summary.get("provider_call_count", 0),
        "provider_success_count": summary.get("provider_success_count", 0),
        "provider_transport_error_count": summary.get("provider_transport_error_count", 0),
        "provider_empty_response_count": summary.get("provider_empty_response_count", 0),
        "parse_error_count": summary.get("parse_error_count", 0),
        "schema_error_count": summary.get("schema_error_count", 0),
        "failed_pack_count": summary.get("failed_pack_count", 0),
        "pack_count": summary.get("pack_count", 0),
        "processed_pack_count": summary.get("processed_pack_count", 0),
        "in_flight_pack_count": summary.get("in_flight_pack_count", 0),
        "pack_progress_percent": summary.get("pack_progress_percent"),
        "processed_pair_count": summary.get("processed_pair_count", 0),
        "parsed_projection_count": summary.get("parsed_projection_count", 0),
        "parsed_no_connection_count": summary.get("parsed_no_connection_count", 0),
        "created_projection_count": summary.get("created_projection_count", 0),
        "no_connection_count": summary.get("no_connection_count", 0),
        "unprocessed_pair_count": summary.get("unprocessed_pair_count", 0),
        "rejected_item_count": summary.get("rejected_item_count", 0),
        "prompt_sent_count": summary.get("prompt_sent_count", 0),
        "response_received_count": summary.get("response_received_count", 0),
        "fail_fast_triggered": summary.get("fail_fast_triggered"),
        "remaining_pack_count_skipped": summary.get("remaining_pack_count_skipped"),
        "fail_fast_reason": summary.get("fail_fast_reason"),
        "debug_mode": summary.get("debug_mode"),
        "pack_summaries": pack_summaries,
        "errors": summary.get("errors") or [],
    }
    audit["errors"] = list(audit["errors"]) + validate_connection_progress_invariants(summary)
    return audit


def prompt_preview(text: str, *, limit: int = PROMPT_PREVIEW_MAX_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"…[truncated {len(text) - limit} chars]"


def pack_summary_status(trace: dict[str, Any]) -> str:
    if trace.get("status"):
        return str(trace["status"])
    err_type = trace.get("parse_error_type")
    if err_type == "transport_error":
        return "transport_error"
    if err_type == "empty_response":
        return "empty_response"
    if trace.get("schema_error") or err_type == "schema_error":
        return "schema_error"
    if trace.get("parse_error") or err_type in {"json_decode_error", "schema_error"}:
        return "parse_error"
    if trace.get("parsed_projection_count", 0) or trace.get("parsed_no_connection_count", 0):
        return "succeeded"
    if trace.get("response_received"):
        return "response_received"
    return "pending"


def finalize_pack_trace(trace: dict[str, Any]) -> dict[str, Any]:
    trace = dict(trace)
    trace["status"] = pack_summary_status(trace)
    if trace.get("raw_response_preview") is None and trace.get("raw_text"):
        trace["raw_response_preview"] = raw_response_preview(trace["raw_text"])
    preview = trace.get("raw_response_preview")
    if isinstance(preview, str) and len(preview) > 2000:
        trace["raw_response_preview"] = raw_response_preview(preview)
    return trace


def _strip_prompt_preview(trace: dict[str, Any]) -> dict[str, Any]:
    """Return trace without prompt_preview to reduce payload size."""
    return {k: v for k, v in trace.items() if k != "prompt_preview"}


def compact_pack_summaries(
    traces: list[dict[str, Any]],
    *,
    max_recent: int = PACK_SUMMARY_MAX_RECENT,
    min_failed_keep: int = PACK_SUMMARY_MIN_FAILED_KEEP,
) -> list[dict[str, Any]]:
    if not traces:
        return []
    finalized = [finalize_pack_trace(t) for t in traces]
    # Short-circuit: if all traces fit within max_recent, return as-is without filtering/merging
    if len(finalized) <= max_recent:
        return finalized
    failed = [t for t in finalized if t.get("status") in {"parse_error", "schema_error", "transport_error"}]
    keep_failed = failed[-min_failed_keep:] if failed else []
    recent = finalized[-max_recent:]
    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in keep_failed + recent:
        key = str(item.get("pack_id", id(item)))
        if key in seen_ids:
            continue
        seen_ids.add(key)
        merged.append(item)
    return merged[-max_recent:] if len(merged) > max_recent else merged


def build_debug_execution_extra(
    *,
    debug_mode: bool,
    debug_single_pack: bool,
    debug_max_packs: int | None,
    original_pack_count: int,
    executed_pack_count: int,
) -> dict[str, Any]:
    skipped = max(0, original_pack_count - executed_pack_count)
    return {
        "debug_mode": debug_mode,
        "debug_single_pack": debug_single_pack,
        "debug_max_packs": debug_max_packs if debug_mode else None,
        "planned_pack_count": original_pack_count,
        "executed_pack_count": executed_pack_count,
        "skipped_debug_pack_count": skipped,
        "original_pack_count": original_pack_count,
        "planned_model_call_count": original_pack_count,
    }


def build_execution_summary(
    audit: ConnectionExecutionAudit,
    pack_traces: list[dict[str, Any]],
    *,
    extra: dict[str, Any] | None = None,
    compact: bool = True,
) -> dict[str, Any]:
    if compact:
        pack_summaries = compact_pack_summaries(pack_traces)
    else:
        pack_summaries = [_strip_prompt_preview(finalize_pack_trace(t)) for t in pack_traces]
    audit.pack_summaries = pack_summaries
    summary = audit.to_dict()
    summary["pack_summaries"] = pack_summaries

    if compact:
        # Recalculate from pack_traces because pack_summaries may be truncated
        response_received = sum(1 for t in pack_traces if t.get("response_received"))
        summary["response_received_count"] = response_received
        if response_received > summary.get("provider_success_count", 0):
            summary["provider_success_count"] = response_received
        summary["failed_pack_count"] = sum(
            1
            for p in pack_summaries
            if p.get("status") in {"parse_error", "schema_error", "transport_error", "empty_response"}
            or p.get("parse_error")
            or p.get("parse_error_type") in {"json_decode_error", "schema_error", "transport_error", "empty_response"}
        )
        processed_traces = [t for t in pack_traces if t.get("provider_call_finished")]
        summary["processed_pack_count"] = len(processed_traces)
        summary["succeeded_pack_count"] = summary["processed_pack_count"] - summary["failed_pack_count"]
        summary["in_flight_pack_count"] = len([
            t for t in pack_traces
            if t.get("provider_call_started") and not t.get("provider_call_finished")
        ])
    else:
        # When not compacting, trust audit object fields directly (accurate after Task 1 fix)
        summary["response_received_count"] = sum(1 for t in pack_traces if t.get("response_received"))
        summary["in_flight_pack_count"] = len([
            t for t in pack_traces
            if t.get("provider_call_started") and not t.get("provider_call_finished")
        ])

    pack_count = int(summary.get("pack_count") or 0)
    if pack_count > 0:
        completed = int(summary.get("processed_pack_count") or 0)
        in_flight = int(summary.get("in_flight_pack_count") or 0)
        summary["pack_progress_percent"] = round(
            min(100.0, ((completed + in_flight) / pack_count) * 100.0),
            1,
        )
    summary["errors"] = validate_connection_progress_invariants(summary)
    if extra:
        summary.update(extra)
    summary["provider_audit"] = merge_provider_audit(summary)
    return summary


def should_trigger_parse_fail_fast(
    *,
    consecutive_parse_failures: int,
    parsed_projection_count: int,
    parsed_no_connection_count: int,
    enabled: bool = FAIL_FAST_DEFAULT_ENABLED,
    threshold: int = FAIL_FAST_DEFAULT_THRESHOLD,
) -> bool:
    if not enabled:
        return False
    if parsed_projection_count > 0 or parsed_no_connection_count > 0:
        return False
    return consecutive_parse_failures >= threshold


def replay_connection_parse_response(
    raw_text: str,
    pack_pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    allowed_pair_ids = {str(p["pair_id"]) for p in pack_pairs if p.get("pair_id")}
    pair_id_to_endpoints: dict[str, Any] = {}
    for row in pack_pairs:
        pid = str(row.get("pair_id") or "")
        if not pid:
            continue
        try:
            import uuid

            pair_id_to_endpoints[pid] = (
                uuid.UUID(str(row["source_region_candidate_id"])),
                uuid.UUID(str(row["target_region_candidate_id"])),
            )
        except (ValueError, TypeError, KeyError):
            continue

    errors: list[str] = []
    warnings: list[str] = []
    try:
        parsed = parse_connection_completion_response(raw_text)
        normalized = normalize_connection_extraction_payload(
            parsed,
            pair_id_to_endpoints=pair_id_to_endpoints,
        )
        connections, no_connections, norm_warnings, handled = normalize_projection_extraction_response(
            normalized,
            allowed_pair_ids=allowed_pair_ids,
            pair_id_to_endpoints=pair_id_to_endpoints,
        )
        warnings.extend(norm_warnings)
        unprocessed = len(allowed_pair_ids) - len(handled)
        return {
            "parsed": True,
            "parsed_projection_count": len(connections),
            "parsed_no_connection_count": len(no_connections),
            "rejected_item_count": sum(1 for w in norm_warnings if "rejected" in w),
            "unprocessed_pair_count": max(0, unprocessed),
            "normalized_payload": normalized,
            "errors": errors,
            "warnings": warnings,
        }
    except LlmJsonParseError as exc:
        errors.append(str(exc))
        return {
            "parsed": False,
            "parsed_projection_count": 0,
            "parsed_no_connection_count": 0,
            "rejected_item_count": 0,
            "unprocessed_pair_count": len(allowed_pair_ids),
            "normalized_payload": None,
            "errors": errors,
            "warnings": warnings,
            "parse_error_type": exc.error_type,
            "raw_response_preview": exc.preview or raw_response_preview(raw_text),
        }
    except ValueError as exc:
        errors.append(str(exc))
        return {
            "parsed": False,
            "parsed_projection_count": 0,
            "parsed_no_connection_count": 0,
            "rejected_item_count": 0,
            "unprocessed_pair_count": len(allowed_pair_ids),
            "normalized_payload": None,
            "errors": errors,
            "warnings": warnings,
            "parse_error_type": "schema_error",
            "raw_response_preview": raw_response_preview(raw_text),
        }
