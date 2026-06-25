"""Map semantic LLM outcomes to DB-persistent status values.

llm_extraction_runs.status CHECK (migration 021) allows only:
  created, running, succeeded, partially_succeeded, failed, cancelled

Semantic outcomes such as succeeded_no_edges or failed_parse_error must be stored
in scope_json / result_summary_json (outcome, semantic_status, display_status),
not in the status column.
"""

from __future__ import annotations

from typing import Any

from app.schemas.llm_extraction import LlmRunStatus

PERSISTENT_RUN_STATUSES = frozenset({
    LlmRunStatus.created,
    LlmRunStatus.running,
    LlmRunStatus.succeeded,
    LlmRunStatus.partially_succeeded,
    LlmRunStatus.failed,
    LlmRunStatus.cancelled,
})

PERSISTENT_ITEM_STATUSES = frozenset({
    "created",
    "running",
    "succeeded",
    "failed",
    "skipped",
    "needs_review",
})

SEMANTIC_FAILURE_OUTCOMES = frozenset({
    LlmRunStatus.failed,
    LlmRunStatus.failed_provider_not_called,
    LlmRunStatus.failed_provider_not_configured,
    LlmRunStatus.failed_provider_error,
    LlmRunStatus.failed_provider_empty_response,
    LlmRunStatus.failed_parse_error,
    LlmRunStatus.failed_empty_prompt,
    LlmRunStatus.failed_no_output,
})

SEMANTIC_NO_EDGE_OUTCOMES = frozenset({
    LlmRunStatus.succeeded_no_edges,
    "no_edges",
})


def map_semantic_outcome_to_persistent_run_status(semantic: str | None) -> str:
    if not semantic:
        return LlmRunStatus.succeeded
    if semantic in PERSISTENT_RUN_STATUSES:
        return semantic
    if semantic in SEMANTIC_NO_EDGE_OUTCOMES:
        return LlmRunStatus.succeeded
    if semantic == LlmRunStatus.partially_succeeded:
        return LlmRunStatus.partially_succeeded
    if semantic in SEMANTIC_FAILURE_OUTCOMES or str(semantic).startswith("failed"):
        return LlmRunStatus.failed
    if semantic == LlmRunStatus.cancelled:
        return LlmRunStatus.cancelled
    return LlmRunStatus.succeeded


def is_semantic_failure(semantic: str | None) -> bool:
    if not semantic:
        return False
    if semantic == LlmRunStatus.partially_succeeded:
        return False
    if semantic == LlmRunStatus.succeeded:
        return False
    if semantic in SEMANTIC_NO_EDGE_OUTCOMES:
        return False
    if semantic == LlmRunStatus.cancelled:
        return False
    if semantic in SEMANTIC_FAILURE_OUTCOMES:
        return True
    return semantic == LlmRunStatus.failed or str(semantic).startswith("failed")


def is_semantic_no_edges(semantic: str | None) -> bool:
    return semantic in SEMANTIC_NO_EDGE_OUTCOMES


def resolve_display_status(
    *,
    persistent_status: str | None = None,
    outcome: str | None = None,
    semantic_status: str | None = None,
) -> str:
    return outcome or semantic_status or persistent_status or LlmRunStatus.succeeded


def build_outcome_scope_payload(
    semantic_outcome: str,
    *,
    no_connection_count: int = 0,
    created_projection_count: int = 0,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "outcome": semantic_outcome,
        "semantic_status": semantic_outcome,
        "display_status": semantic_outcome,
        "has_edges": created_projection_count > 0,
        "no_connection_count": no_connection_count,
        "created_projection_count": created_projection_count,
    }
    if is_semantic_no_edges(semantic_outcome):
        payload["has_edges"] = False
    if extra:
        payload.update(extra)
    return payload


def apply_persistent_run_status(
    run: Any,
    semantic_outcome: str,
    *,
    no_connection_count: int = 0,
    created_projection_count: int = 0,
    extra_scope: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Write DB-legal run.status and semantic outcome into run.scope_json."""
    persistent = map_semantic_outcome_to_persistent_run_status(semantic_outcome)
    run.status = persistent
    outcome_payload = build_outcome_scope_payload(
        semantic_outcome,
        no_connection_count=no_connection_count,
        created_projection_count=created_projection_count,
        extra=extra_scope,
    )
    run.scope_json = {
        **(run.scope_json or {}),
        **outcome_payload,
    }
    return persistent, semantic_outcome
