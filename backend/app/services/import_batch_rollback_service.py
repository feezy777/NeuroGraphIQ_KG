"""Import batch rollback preview and execute."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion, CandidateGenerationRun
from app.models.human_review import CandidateReviewRecord
from app.models.import_batch import ImportBatch, ImportBatchEvent
from app.models.import_batch_rollback import ImportBatchRollbackRecord
from app.models.promotion import FinalBrainRegion, PromotionRecord
from app.models.raw_macro96 import RawMacro96RegionRow
from app.models.raw_parsing import RawAal3RegionLabel, RawParseRun
from app.models.rule_validation import CandidateRuleValidationResult, RuleValidationRun
from app.schemas.import_batch import BatchEventType
from app.schemas.import_batch_rollback import (
    RollbackExecuteRequest,
    RollbackExecuteResponse,
    RollbackPreviewResponse,
    RollbackRiskLevel,
    RollbackTargetStatus,
)
from app.services.import_batch_service import BatchNotFoundError, get_batch

# Pipeline rank for rollback layering (higher = more downstream).
STATUS_RANK: dict[str, int] = {
    "created": 0,
    "queued": 1,
    "running": 2,
    "parsed": 3,
    "candidate_generated": 4,
    "validated": 5,
    "validation_dispatched": 5,
    "reviewed": 6,
    "promoted": 7,
    "completed": 7,
}

TARGET_RANK: dict[str, int] = {e.value: STATUS_RANK[e.value] for e in RollbackTargetStatus}

PREVIEW_UNSUPPORTED_CURRENT = frozenset({"failed", "cancelled", "archived", "created", "queued"})

DISALLOWED_TARGETS = frozenset({"created", "queued"})

# Layer rank: data deleted when rolling back below this stage.
LAYER_RANK: dict[str, int] = {
    "raw_parse_runs": 3,
    "raw_aal3_region_labels": 3,
    "raw_macro96_region_rows": 3,
    "candidate_generation_runs": 4,
    "candidate_brain_regions": 4,
    "rule_validation_runs": 5,
    "candidate_rule_validation_results": 5,
    "candidate_review_records": 6,
    "promotion_records": 7,
    "final_brain_regions": 7,
}

PLAN_KEYS = tuple(LAYER_RANK.keys())

DELETE_ORDER = (
    "promotion_records",
    "final_brain_regions",
    "candidate_review_records",
    "candidate_rule_validation_results",
    "rule_validation_runs",
    "candidate_brain_regions",
    "candidate_generation_runs",
    "raw_macro96_region_rows",
    "raw_aal3_region_labels",
    "raw_parse_runs",
)

MODEL_BY_KEY: dict[str, type] = {
    "promotion_records": PromotionRecord,
    "final_brain_regions": FinalBrainRegion,
    "candidate_review_records": CandidateReviewRecord,
    "candidate_rule_validation_results": CandidateRuleValidationResult,
    "rule_validation_runs": RuleValidationRun,
    "candidate_brain_regions": CandidateBrainRegion,
    "candidate_generation_runs": CandidateGenerationRun,
    "raw_macro96_region_rows": RawMacro96RegionRow,
    "raw_aal3_region_labels": RawAal3RegionLabel,
    "raw_parse_runs": RawParseRun,
}

TARGET_TO_BATCH_STATUS: dict[str, str] = {
    "running": "running",
    "parsed": "parsed",
    "candidate_generated": "candidate_generated",
    "validated": "validation_dispatched",
    "reviewed": "validation_dispatched",
}


class RollbackPreviewNotSupportedError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class RollbackPreviewInvalidTargetError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class RollbackExecuteConfirmationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class RollbackExecuteStalePreviewError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class RollbackExecuteUnsafeScopeError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def normalize_status_rank(status: str) -> int:
    rank = STATUS_RANK.get(status)
    if rank is None:
        return -1
    return rank


def is_macro96_parser(parser_key: str | None) -> bool:
    return (parser_key or "").strip() == "macro96_xlsx"


def is_aal3_parser(parser_key: str | None) -> bool:
    return (parser_key or "").strip() in ("aal3_xml", "aal3_label_table")


def build_delete_keep_plans(
    dependency_counts: dict[str, int],
    target_rank: int,
) -> tuple[dict[str, int], dict[str, int]]:
    delete_plan: dict[str, int] = {}
    keep_plan: dict[str, int] = {}
    for key in PLAN_KEYS:
        count = dependency_counts.get(key, 0)
        layer = LAYER_RANK[key]
        if layer > target_rank:
            delete_plan[key] = count
            keep_plan[key] = 0
        else:
            delete_plan[key] = 0
            keep_plan[key] = count
    return delete_plan, keep_plan


def compute_risk_level(delete_plan: dict[str, int]) -> RollbackRiskLevel:
    if delete_plan.get("final_brain_regions", 0) > 0:
        return RollbackRiskLevel.critical
    if (
        delete_plan.get("promotion_records", 0) > 0
        or delete_plan.get("candidate_review_records", 0) > 0
    ):
        return RollbackRiskLevel.high
    if any(
        delete_plan.get(k, 0) > 0
        for k in (
            "raw_parse_runs",
            "raw_aal3_region_labels",
            "raw_macro96_region_rows",
        )
    ):
        return RollbackRiskLevel.high
    if any(
        delete_plan.get(k, 0) > 0
        for k in (
            "candidate_brain_regions",
            "candidate_generation_runs",
            "rule_validation_runs",
            "candidate_rule_validation_results",
        )
    ):
        return RollbackRiskLevel.medium
    return RollbackRiskLevel.low


def build_warnings(
    batch: ImportBatch,
    dependency_counts: dict[str, int],
    delete_plan: dict[str, int],
    *,
    for_execute: bool = False,
) -> list[str]:
    warnings: list[str] = []
    pk = batch.parser_key
    if not is_macro96_parser(pk) and not is_aal3_parser(pk):
        warnings.append(f"parser_key={pk!r} is unknown; raw counts include both AAL3 and Macro96 tables")
    if is_macro96_parser(pk) and dependency_counts.get("raw_aal3_region_labels", 0) > 0:
        warnings.append("AAL3 raw labels found on Macro96 batch; verify data lineage")
    if is_aal3_parser(pk) and dependency_counts.get("raw_macro96_region_rows", 0) > 0:
        warnings.append("Macro96 raw rows found on AAL3 batch; verify data lineage")
    if delete_plan.get("final_brain_regions", 0) > 0:
        warnings.append(
            "final_brain_regions will be deleted; this affects official promoted regions for this batch"
        )
    if sum(delete_plan.values()) == 0:
        warnings.append("no downstream data would be deleted for this target_status")
    if not for_execute:
        warnings.append("rollback preview is read-only; no data has been modified")
    if for_execute and delete_plan.get("final_brain_regions", 0) > 0:
        warnings.append("rollback execute will permanently delete final_brain_regions for this batch")
    return warnings


async def _count_by_batch(session: AsyncSession, model, batch_id: uuid.UUID) -> int:
    q = select(func.count()).select_from(model).where(model.batch_id == batch_id)
    return int((await session.execute(q)).scalar_one())


async def collect_dependency_counts(
    session: AsyncSession, batch_id: uuid.UUID
) -> dict[str, int]:
    return {
        "raw_parse_runs": await _count_by_batch(session, RawParseRun, batch_id),
        "raw_aal3_region_labels": await _count_by_batch(session, RawAal3RegionLabel, batch_id),
        "raw_macro96_region_rows": await _count_by_batch(session, RawMacro96RegionRow, batch_id),
        "candidate_generation_runs": await _count_by_batch(
            session, CandidateGenerationRun, batch_id
        ),
        "candidate_brain_regions": await _count_by_batch(
            session, CandidateBrainRegion, batch_id
        ),
        "rule_validation_runs": await _count_by_batch(session, RuleValidationRun, batch_id),
        "candidate_rule_validation_results": await _count_by_batch(
            session, CandidateRuleValidationResult, batch_id
        ),
        "candidate_review_records": await _count_by_batch(
            session, CandidateReviewRecord, batch_id
        ),
        "promotion_records": await _count_by_batch(session, PromotionRecord, batch_id),
        "final_brain_regions": await _count_by_batch(session, FinalBrainRegion, batch_id),
    }


def validate_rollback_preview_request(
    current_status: str,
    target_status: str,
) -> tuple[int, int]:
    if target_status in DISALLOWED_TARGETS:
        raise RollbackPreviewInvalidTargetError(
            f"rollback preview to {target_status!r} is not supported"
        )
    if target_status not in TARGET_RANK:
        raise RollbackPreviewInvalidTargetError(f"invalid target_status: {target_status!r}")

    if current_status in ("failed", "cancelled", "archived"):
        raise RollbackPreviewNotSupportedError(
            "rollback preview is not supported for failed/cancelled/archived batches"
        )
    if current_status in PREVIEW_UNSUPPORTED_CURRENT:
        raise RollbackPreviewNotSupportedError(
            f"rollback preview is not supported when batch status is {current_status!r}"
        )

    current_rank = normalize_status_rank(current_status)
    if current_rank < 0:
        raise RollbackPreviewNotSupportedError(
            f"rollback preview is not supported for unknown status {current_status!r}"
        )

    target_rank = TARGET_RANK[target_status]
    if target_rank >= current_rank:
        raise RollbackPreviewInvalidTargetError(
            f"target_status {target_status!r} must be earlier than current status {current_status!r}"
        )
    return current_rank, target_rank


def _plans_match(expected: dict[str, int] | None, actual: dict[str, int]) -> bool:
    if expected is None:
        return True
    for key, count in expected.items():
        if actual.get(key, 0) != count:
            return False
    return True


def validate_rollback_confirmation(
    confirmation_text: str,
    required_confirmation: str,
) -> None:
    if confirmation_text != required_confirmation:
        raise RollbackExecuteConfirmationError(
            "confirmation_text does not match required_confirmation from preview"
        )


def _assert_batch_scoped_model(model: type, key: str) -> None:
    if not hasattr(model, "batch_id"):
        raise RollbackExecuteUnsafeScopeError(
            f"{key} cannot be safely scoped to this batch with current schema"
        )


async def build_rollback_preview(
    session: AsyncSession,
    batch_id: uuid.UUID,
    target_status: str,
    *,
    for_execute: bool = False,
) -> tuple[ImportBatch, RollbackPreviewResponse]:
    batch = await get_batch(session, batch_id)
    current_status = batch.status
    validate_rollback_preview_request(current_status, target_status)

    target_rank = TARGET_RANK[target_status]
    dependency_counts = await collect_dependency_counts(session, batch_id)
    delete_plan, keep_plan = build_delete_keep_plans(dependency_counts, target_rank)
    risk_level = compute_risk_level(delete_plan)
    warnings = build_warnings(batch, dependency_counts, delete_plan, for_execute=for_execute)

    required = f"ROLLBACK {batch.batch_code} TO {target_status}"
    now = datetime.now(timezone.utc)

    preview = RollbackPreviewResponse(
        batch_id=batch.id,
        batch_code=batch.batch_code,
        resource_id=batch.resource_id,
        parser_key=batch.parser_key,
        current_status=current_status,
        target_status=target_status,
        supported=True,
        will_change_status=True,
        required_confirmation=required,
        warnings=warnings,
        delete_plan=delete_plan,
        keep_plan=keep_plan,
        dependency_counts=dependency_counts,
        risk_level=risk_level,
        next_api=f"POST /api/import-batches/{batch_id}/rollback",
        generated_at=now,
    )
    return batch, preview


async def _delete_batch_rows(
    session: AsyncSession,
    batch_id: uuid.UUID,
    key: str,
    expected: int,
) -> int:
    model = MODEL_BY_KEY[key]
    _assert_batch_scoped_model(model, key)
    result = await session.execute(delete(model).where(model.batch_id == batch_id))
    deleted = int(result.rowcount or 0)
    if deleted != expected:
        raise RollbackExecuteStalePreviewError(
            f"delete count mismatch for {key}: expected {expected}, deleted {deleted}; re-run preview"
        )
    return deleted


async def _execute_deletes(
    session: AsyncSession,
    batch_id: uuid.UUID,
    delete_plan: dict[str, int],
) -> dict[str, int]:
    deleted_counts: dict[str, int] = {k: 0 for k in PLAN_KEYS}
    for key in DELETE_ORDER:
        planned = delete_plan.get(key, 0)
        if planned <= 0:
            continue
        deleted_counts[key] = await _delete_batch_rows(session, batch_id, key, planned)
    return deleted_counts


def _kept_counts_after_delete(
    dependency_counts: dict[str, int],
    delete_plan: dict[str, int],
) -> dict[str, int]:
    kept: dict[str, int] = {}
    for key in PLAN_KEYS:
        dep = dependency_counts.get(key, 0)
        planned_delete = delete_plan.get(key, 0)
        kept[key] = max(0, dep - planned_delete)
    return kept


async def _append_rollback_event(
    session: AsyncSession,
    *,
    batch_id: uuid.UUID,
    event_type: str,
    from_status: str | None = None,
    to_status: str | None = None,
    message: str | None = None,
    payload_json: dict[str, Any] | None = None,
) -> ImportBatchEvent:
    event = ImportBatchEvent(
        batch_id=batch_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        message=message,
        payload_json=payload_json,
    )
    session.add(event)
    return event


async def create_rollback_audit_record(
    session: AsyncSession,
    *,
    batch: ImportBatch,
    preview: RollbackPreviewResponse,
    request: RollbackExecuteRequest,
    status: str,
    deleted_counts: dict[str, int] | None = None,
    kept_counts: dict[str, int] | None = None,
    error_message: str | None = None,
    finished_at: datetime | None = None,
) -> ImportBatchRollbackRecord:
    record = ImportBatchRollbackRecord(
        batch_id=batch.id,
        batch_code=batch.batch_code,
        resource_id=batch.resource_id,
        parser_key=batch.parser_key,
        from_status=preview.current_status,
        target_status=preview.target_status,
        operator=request.operator,
        reason=request.reason,
        confirmation_text=request.confirmation_text,
        required_confirmation=preview.required_confirmation,
        risk_level=preview.risk_level.value,
        preview_json=preview.model_dump(mode="json"),
        delete_plan_json=preview.delete_plan,
        keep_plan_json=preview.keep_plan,
        dependency_counts_json=preview.dependency_counts,
        deleted_counts_json=deleted_counts or {},
        kept_counts_json=kept_counts or {},
        status=status,
        error_message=error_message,
        finished_at=finished_at,
    )
    session.add(record)
    return record


async def write_rollback_events(
    session: AsyncSession,
    *,
    batch_id: uuid.UUID,
    from_status: str,
    to_status: str,
    operator: str,
    reason: str,
    rollback_record_id: uuid.UUID,
    deleted_counts: dict[str, int],
) -> list[str]:
    written: list[str] = []
    await _append_rollback_event(
        session,
        batch_id=batch_id,
        event_type=BatchEventType.rollback_succeeded.value,
        from_status=from_status,
        to_status=to_status,
        message=f"rollback succeeded by {operator}",
        payload_json={
            "rollback_record_id": str(rollback_record_id),
            "deleted_counts": deleted_counts,
        },
    )
    written.append(BatchEventType.rollback_succeeded.value)
    await _append_rollback_event(
        session,
        batch_id=batch_id,
        event_type=BatchEventType.status_changed.value,
        from_status=from_status,
        to_status=to_status,
        message=f"batch status rolled back from {from_status} to {to_status}",
        payload_json={"action": "rollback", "operator": operator, "reason": reason},
    )
    written.append(BatchEventType.status_changed.value)
    return written


async def get_import_batch_rollback_preview(
    session: AsyncSession,
    batch_id: uuid.UUID,
    target_status: str,
) -> RollbackPreviewResponse:
    _, preview = await build_rollback_preview(session, batch_id, target_status)
    return preview


async def execute_import_batch_rollback(
    session: AsyncSession,
    batch_id: uuid.UUID,
    request: RollbackExecuteRequest,
) -> RollbackExecuteResponse:
    target_status = request.target_status.strip()
    if target_status not in TARGET_RANK:
        raise RollbackPreviewInvalidTargetError(f"invalid target_status: {target_status!r}")

    batch, preview = await build_rollback_preview(
        session, batch_id, target_status, for_execute=True
    )
    if request.target_status != preview.target_status:
        raise RollbackPreviewInvalidTargetError(
            f"target_status mismatch: request={request.target_status!r}, preview={preview.target_status!r}"
        )

    validate_rollback_confirmation(request.confirmation_text, preview.required_confirmation)

    if not _plans_match(request.expected_delete_plan, preview.delete_plan):
        raise RollbackExecuteStalePreviewError(
            "expected_delete_plan does not match current preview; re-run rollback-preview"
        )
    if not _plans_match(request.expected_dependency_counts, preview.dependency_counts):
        raise RollbackExecuteStalePreviewError(
            "expected_dependency_counts does not match current data; re-run rollback-preview"
        )

    if preview.delete_plan.get("final_brain_regions", 0) > 0:
        _assert_batch_scoped_model(FinalBrainRegion, "final_brain_regions")

    from_status = preview.current_status
    new_batch_status = TARGET_TO_BATCH_STATUS.get(target_status)
    if new_batch_status is None:
        raise RollbackPreviewInvalidTargetError(f"unsupported rollback target: {target_status!r}")

    audit_record = await create_rollback_audit_record(
        session,
        batch=batch,
        preview=preview,
        request=request,
        status="started",
    )
    await session.flush()

    events_written: list[str] = []
    finished_at: datetime | None = None

    try:
        await _append_rollback_event(
            session,
            batch_id=batch.id,
            event_type=BatchEventType.rollback_started.value,
            from_status=from_status,
            to_status=target_status,
            message=f"rollback started by {request.operator}",
            payload_json={
                "rollback_record_id": str(audit_record.id),
                "reason": request.reason,
            },
        )
        events_written.append(BatchEventType.rollback_started.value)

        deleted_counts = await _execute_deletes(session, batch.id, preview.delete_plan)
        kept_counts = _kept_counts_after_delete(preview.dependency_counts, preview.delete_plan)

        batch.status = new_batch_status
        session.add(batch)

        more_events = await write_rollback_events(
            session,
            batch_id=batch.id,
            from_status=from_status,
            to_status=new_batch_status,
            operator=request.operator,
            reason=request.reason,
            rollback_record_id=audit_record.id,
            deleted_counts=deleted_counts,
        )
        events_written.extend(more_events)

        finished_at = datetime.now(timezone.utc)
        audit_record.status = "succeeded"
        audit_record.deleted_counts_json = deleted_counts
        audit_record.kept_counts_json = kept_counts
        audit_record.finished_at = finished_at

        await session.commit()

        return RollbackExecuteResponse(
            rollback_record_id=audit_record.id,
            batch_id=batch.id,
            batch_code=batch.batch_code,
            resource_id=batch.resource_id,
            parser_key=batch.parser_key,
            from_status=from_status,
            target_status=target_status,
            status="succeeded",
            deleted_counts=deleted_counts,
            kept_counts=kept_counts,
            batch_status=new_batch_status,
            warnings=preview.warnings,
            events_written=events_written,
            finished_at=finished_at,
        )
    except Exception as exc:
        await session.rollback()
        fail_at = datetime.now(timezone.utc)
        try:
            fail_record = ImportBatchRollbackRecord(
                batch_id=batch.id,
                batch_code=batch.batch_code,
                resource_id=batch.resource_id,
                parser_key=batch.parser_key,
                from_status=from_status,
                target_status=target_status,
                operator=request.operator,
                reason=request.reason,
                confirmation_text=request.confirmation_text,
                required_confirmation=preview.required_confirmation,
                risk_level=preview.risk_level.value,
                preview_json=preview.model_dump(mode="json"),
                delete_plan_json=preview.delete_plan,
                keep_plan_json=preview.keep_plan,
                dependency_counts_json=preview.dependency_counts,
                deleted_counts_json={},
                kept_counts_json={},
                status="failed",
                error_message=str(exc),
                finished_at=fail_at,
            )
            session.add(fail_record)
            await _append_rollback_event(
                session,
                batch_id=batch.id,
                event_type=BatchEventType.rollback_failed.value,
                from_status=from_status,
                to_status=target_status,
                message=f"rollback failed: {exc}",
                payload_json={"operator": request.operator, "reason": request.reason},
            )
            await session.commit()
        except Exception:
            await session.rollback()
        raise
