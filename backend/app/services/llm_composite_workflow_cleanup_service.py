"""Cleanup artifacts produced by a single composite workflow run."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_composite_workflow import LlmCompositeWorkflowRun, LlmCompositeWorkflowStep
from app.models.llm_extraction import LlmExtractionItem, LlmExtractionRun
from app.models.mirror_kg import (
    MirrorEvidenceRecord,
    MirrorKgTriple,
    MirrorRegionCircuit,
    MirrorRegionConnection,
    MirrorRegionFunction,
)
from app.models.mirror_macro_clinical import (
    MirrorCircuitFunction,
    MirrorCircuitProjectionMembership,
    MirrorCircuitStep,
    MirrorProjectionFunction,
)
from app.schemas.llm_composite_workflow import CompositeStepStatus, CompositeWorkflowStatus
from app.schemas.llm_extraction import LlmItemStatus, LlmRunStatus

logger = logging.getLogger(__name__)

WORKFLOW_ID_JSON_PATHS = (
    "attributes",
    "composite_workflow_run_id",
)


def _workflow_id_match(column, workflow_run_id: uuid.UUID):
    wf = str(workflow_run_id)
    return or_(
        column["attributes"]["composite_workflow_run_id"].astext == wf,
        column["composite_workflow_run_id"].astext == wf,
    )


async def _collect_llm_run_ids(
    session: AsyncSession,
    workflow_run_id: uuid.UUID,
    steps: list[LlmCompositeWorkflowStep],
) -> list[uuid.UUID]:
    ids: set[uuid.UUID] = set()
    for step in steps:
        if step.llm_run_id:
            ids.add(step.llm_run_id)
    extra_q = select(LlmExtractionRun.id).where(
        LlmExtractionRun.scope_json["composite_workflow_run_id"].astext == str(workflow_run_id)
    )
    for row in (await session.execute(extra_q)).scalars().all():
        ids.add(row)
    return list(ids)


async def cleanup_composite_workflow_artifacts(
    session: AsyncSession,
    workflow_run_id: uuid.UUID,
    *,
    steps: list[LlmCompositeWorkflowStep] | None = None,
) -> tuple[dict[str, int], list[str], list[str]]:
    """Delete mirror artifacts scoped to workflow_run_id. Returns (deleted_counts, warnings, errors)."""
    warnings: list[str] = []
    errors: list[str] = []
    deleted: dict[str, int] = {
        "mirror_projections": 0,
        "mirror_projection_functions": 0,
        "mirror_region_circuits": 0,
        "mirror_circuit_steps": 0,
        "mirror_circuit_functions": 0,
        "mirror_region_functions": 0,
        "mirror_kg_triples": 0,
        "mirror_evidence_records": 0,
        "mirror_circuit_projection_memberships": 0,
        "llm_extraction_items": 0,
        "llm_extraction_runs": 0,
        "llm_composite_workflow_steps": 0,
    }

    if steps is None:
        steps = list(
            (
                await session.execute(
                    select(LlmCompositeWorkflowStep).where(
                        LlmCompositeWorkflowStep.workflow_run_id == workflow_run_id
                    )
                )
            )
            .scalars()
            .all()
        )

    llm_run_ids = await _collect_llm_run_ids(session, workflow_run_id, steps)
    wf = str(workflow_run_id)
    tag_filter_conn = or_(
        MirrorRegionConnection.raw_payload_json["attributes"]["composite_workflow_run_id"].astext == wf,
        MirrorRegionConnection.normalized_payload_json["attributes"]["composite_workflow_run_id"].astext == wf,
    )
    if llm_run_ids:
        tag_filter_conn = or_(tag_filter_conn, MirrorRegionConnection.llm_run_id.in_(llm_run_ids))

    conn_ids_q = select(MirrorRegionConnection.id).where(tag_filter_conn)
    conn_ids = list((await session.execute(conn_ids_q)).scalars().all())

    circuit_tag = or_(
        MirrorRegionCircuit.raw_payload_json["attributes"]["composite_workflow_run_id"].astext == wf,
        MirrorRegionCircuit.normalized_payload_json["attributes"]["composite_workflow_run_id"].astext == wf,
    )
    if llm_run_ids:
        circuit_tag = or_(circuit_tag, MirrorRegionCircuit.llm_run_id.in_(llm_run_ids))
    circuit_ids = list((await session.execute(select(MirrorRegionCircuit.id).where(circuit_tag))).scalars().all())

    try:
        if llm_run_ids:
            r = await session.execute(delete(MirrorEvidenceRecord).where(MirrorEvidenceRecord.llm_run_id.in_(llm_run_ids)))
            deleted["mirror_evidence_records"] = r.rowcount or 0
            r = await session.execute(delete(MirrorKgTriple).where(MirrorKgTriple.llm_run_id.in_(llm_run_ids)))
            deleted["mirror_kg_triples"] = r.rowcount or 0

        pf_filter = MirrorProjectionFunction.raw_payload_json["attributes"]["composite_workflow_run_id"].astext == wf
        if conn_ids:
            pf_filter = or_(pf_filter, MirrorProjectionFunction.projection_id.in_(conn_ids))
        if llm_run_ids:
            pf_filter = or_(pf_filter, MirrorProjectionFunction.llm_run_id.in_(llm_run_ids))
        r = await session.execute(delete(MirrorProjectionFunction).where(pf_filter))
        deleted["mirror_projection_functions"] = r.rowcount or 0

        mem_parts: list[Any] = [
            MirrorCircuitProjectionMembership.raw_payload_json["attributes"]["composite_workflow_run_id"].astext == wf
        ]
        if circuit_ids:
            mem_parts.append(MirrorCircuitProjectionMembership.circuit_id.in_(circuit_ids))
        if conn_ids:
            mem_parts.append(MirrorCircuitProjectionMembership.projection_id.in_(conn_ids))
        if llm_run_ids:
            mem_parts.append(MirrorCircuitProjectionMembership.llm_run_id.in_(llm_run_ids))
        r = await session.execute(delete(MirrorCircuitProjectionMembership).where(or_(*mem_parts)))
        deleted["mirror_circuit_projection_memberships"] = r.rowcount or 0

        step_filter = MirrorCircuitStep.raw_payload_json["attributes"]["composite_workflow_run_id"].astext == wf
        if circuit_ids:
            step_filter = or_(step_filter, MirrorCircuitStep.circuit_id.in_(circuit_ids))
        if llm_run_ids:
            step_filter = or_(step_filter, MirrorCircuitStep.llm_run_id.in_(llm_run_ids))
        r = await session.execute(delete(MirrorCircuitStep).where(step_filter))
        deleted["mirror_circuit_steps"] = r.rowcount or 0

        fn_filter = MirrorCircuitFunction.attributes["composite_workflow_run_id"].astext == wf
        if circuit_ids:
            fn_filter = or_(fn_filter, MirrorCircuitFunction.circuit_id.in_(circuit_ids))
        if llm_run_ids:
            fn_filter = or_(fn_filter, MirrorCircuitFunction.llm_run_id.in_(llm_run_ids))
        r = await session.execute(delete(MirrorCircuitFunction).where(fn_filter))
        deleted["mirror_circuit_functions"] = r.rowcount or 0

        func_filter = or_(
            MirrorRegionFunction.raw_payload_json["attributes"]["composite_workflow_run_id"].astext == wf,
            MirrorRegionFunction.normalized_payload_json["attributes"]["composite_workflow_run_id"].astext == wf,
        )
        if llm_run_ids:
            func_filter = or_(func_filter, MirrorRegionFunction.llm_run_id.in_(llm_run_ids))
        r = await session.execute(delete(MirrorRegionFunction).where(func_filter))
        deleted["mirror_region_functions"] = r.rowcount or 0

        if conn_ids:
            r = await session.execute(delete(MirrorRegionConnection).where(MirrorRegionConnection.id.in_(conn_ids)))
            deleted["mirror_projections"] = r.rowcount or 0
        elif llm_run_ids:
            r = await session.execute(
                delete(MirrorRegionConnection).where(MirrorRegionConnection.llm_run_id.in_(llm_run_ids))
            )
            deleted["mirror_projections"] = r.rowcount or 0

        if circuit_ids:
            r = await session.execute(delete(MirrorRegionCircuit).where(MirrorRegionCircuit.id.in_(circuit_ids)))
            deleted["mirror_region_circuits"] = r.rowcount or 0
        elif llm_run_ids:
            r = await session.execute(
                delete(MirrorRegionCircuit).where(MirrorRegionCircuit.llm_run_id.in_(llm_run_ids))
            )
            deleted["mirror_region_circuits"] = r.rowcount or 0

        if llm_run_ids:
            # Trace layer: DO NOT physically delete llm_extraction_items while a
            # background provider task may still be flushing updates against them.
            # Physical deletion is what caused "expected to update 1 row(s); 0 were
            # matched" StaleDataError races. Instead we mark them cancelled so the
            # rows still exist (late ORM UPDATE will still match 1 row) and the
            # audit trail is preserved.
            r = await session.execute(
                update(LlmExtractionItem)
                .where(LlmExtractionItem.run_id.in_(llm_run_ids))
                .values(status=LlmItemStatus.cancelled)
            )
            deleted["llm_extraction_items"] = r.rowcount or 0
            r = await session.execute(
                update(LlmExtractionRun)
                .where(LlmExtractionRun.id.in_(llm_run_ids))
                .values(status=LlmRunStatus.cancelled, finished_at=datetime.now(timezone.utc))
            )
            deleted["llm_extraction_runs"] = r.rowcount or 0

        for step in steps:
            if step.status not in {
                CompositeStepStatus.cancelled.value,
                CompositeStepStatus.skipped.value,
                CompositeStepStatus.skipped_dependency_failed.value,
                CompositeStepStatus.skipped_no_projection.value,
            }:
                step.status = CompositeStepStatus.cancelled.value
                if not step.completed_at:
                    step.completed_at = datetime.now(timezone.utc)
                deleted["llm_composite_workflow_steps"] += 1

        await session.flush()
    except Exception as exc:
        logger.exception("[cleanup] failed workflow_run_id=%s", workflow_run_id)
        errors.append(str(exc))

    if not conn_ids and not circuit_ids and not llm_run_ids:
        warnings.append(
            "No mirror records matched workflow_run_id tag; cleanup relied on llm_run_id linkage only."
        )

    return deleted, warnings, errors


async def mark_workflow_cleanup_summary(
    session: AsyncSession,
    run: LlmCompositeWorkflowRun,
    *,
    deleted: dict[str, int],
    cancel_reason: str | None = None,
    cancel_meta: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    final_status: CompositeWorkflowStatus,
) -> None:
    summary = dict(run.result_summary_json or {})
    summary["cleanup"] = True
    summary["deleted"] = deleted
    summary["cancelled"] = True
    summary["cancelled_at"] = datetime.now(timezone.utc).isoformat()
    summary["cancelled_by"] = "user"
    if cancel_reason:
        summary["cancel_reason"] = cancel_reason
    if cancel_meta:
        summary.update(cancel_meta)
    if warnings:
        summary["cleanup_warnings"] = warnings
    if errors:
        summary["cleanup_errors"] = errors
    run.result_summary_json = summary
    run.status = final_status.value
    if not run.completed_at:
        run.completed_at = datetime.now(timezone.utc)
    await session.flush()
