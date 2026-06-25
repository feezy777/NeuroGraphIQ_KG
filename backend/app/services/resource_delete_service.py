"""Destructive cascade delete for atlas resources and all downstream data."""

from __future__ import annotations

import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.candidate import CandidateBrainRegion, CandidateGenerationRun
from app.models.file_normalization import FileIntermediateArtifact, FileNormalizationRun
from app.models.human_review import CandidateReviewRecord
from app.models.import_batch import ImportBatch, ImportBatchEvent, ImportBatchFile
from app.models.llm_extraction import CandidateLlmExtraction
from app.models.promotion import FinalBrainRegion, PromotionRecord
from app.models.raw_parsing import RawAal3RegionLabel, RawParseRun
from app.models.resource import AtlasResource
from app.models.resource_delete_audit import DestructiveResourceDeleteRecord
from app.models.resource_file import ResourceFile
from app.models.rule_validation import CandidateRuleValidationResult, RuleValidationRun
from app.schemas.resource_delete import (
    DeletedCounts,
    DependencyCounts,
    ResourceDeletePreview,
    ResourceDeleteRequest,
    ResourceDeleteResult,
)
from app.services import resource_service
from app.utils.file_meta import resolve_under_root

logger = logging.getLogger(__name__)

WARNINGS = [
    "This operation permanently deletes all downstream data linked to this resource.",
    "This operation cannot be undone from the workbench.",
]


class ResourceDeleteConfirmationError(Exception):
    pass


class ResourceDeleteValidationError(Exception):
    pass


async def _table_exists(session: AsyncSession, table_name: str) -> bool:
    result = await session.execute(
        text(
            """
            SELECT EXISTS (
              SELECT 1 FROM information_schema.tables
              WHERE table_schema = 'public' AND table_name = :t
            )
            """
        ),
        {"t": table_name},
    )
    return bool(result.scalar_one())


async def _count_by_resource(session: AsyncSession, model: type, resource_id: uuid.UUID) -> int:
    col = getattr(model, "resource_id", None)
    if col is None:
        return 0
    q = select(func.count()).select_from(model).where(col == resource_id)
    return int((await session.execute(q)).scalar_one())


async def _count_by_resource_table(
    session: AsyncSession, table_name: str, resource_id: uuid.UUID
) -> int:
    if not await _table_exists(session, table_name):
        return 0
    result = await session.execute(
        text(f"SELECT COUNT(*) FROM {table_name} WHERE resource_id = :rid"),
        {"rid": resource_id},
    )
    return int(result.scalar_one())


async def _count_batch_events(session: AsyncSession, resource_id: uuid.UUID) -> int:
    batch_ids = select(ImportBatch.id).where(ImportBatch.resource_id == resource_id)
    q = select(func.count()).select_from(ImportBatchEvent).where(
        ImportBatchEvent.batch_id.in_(batch_ids)
    )
    return int((await session.execute(q)).scalar_one())


async def _audit_table_available(session: AsyncSession) -> bool:
    return await _table_exists(session, "destructive_resource_delete_records")


async def collect_dependency_counts(
    session: AsyncSession, resource_id: uuid.UUID
) -> DependencyCounts:
    return DependencyCounts(
        resource_files=await _count_by_resource(session, ResourceFile, resource_id),
        file_intermediate_artifacts=await _count_by_resource(
            session, FileIntermediateArtifact, resource_id
        ),
        file_normalization_runs=await _count_by_resource(
            session, FileNormalizationRun, resource_id
        ),
        import_batches=await _count_by_resource(session, ImportBatch, resource_id),
        import_batch_files=await _count_by_resource(session, ImportBatchFile, resource_id),
        import_batch_events=await _count_batch_events(session, resource_id),
        raw_parse_runs=await _count_by_resource(session, RawParseRun, resource_id),
        raw_aal3_region_labels=await _count_by_resource(session, RawAal3RegionLabel, resource_id),
        raw_macro96_region_rows=await _count_by_resource_table(
            session, "raw_macro96_region_rows", resource_id
        ),
        candidate_generation_runs=await _count_by_resource(
            session, CandidateGenerationRun, resource_id
        ),
        candidate_brain_regions=await _count_by_resource(
            session, CandidateBrainRegion, resource_id
        ),
        candidate_llm_extractions=await _count_by_resource(
            session, CandidateLlmExtraction, resource_id
        ),
        rule_validation_runs=await _count_by_resource(session, RuleValidationRun, resource_id),
        candidate_rule_validation_results=await _count_by_resource(
            session, CandidateRuleValidationResult, resource_id
        ),
        candidate_review_records=await _count_by_resource(
            session, CandidateReviewRecord, resource_id
        ),
        promotion_records=await _count_by_resource(session, PromotionRecord, resource_id),
        final_brain_regions=await _count_by_resource(session, FinalBrainRegion, resource_id),
    )


async def get_resource_delete_preview(
    session: AsyncSession, resource_id: uuid.UUID
) -> ResourceDeletePreview:
    row = await resource_service.get_resource(session, resource_id, include_archived=True)
    counts = await collect_dependency_counts(session, resource_id)
    required = f"DELETE {row.resource_code}"
    return ResourceDeletePreview(
        resource_id=row.id,
        resource_code=row.resource_code,
        source_atlas=row.source_atlas,
        status=row.status,
        can_delete=True,
        delete_mode="destructive_cascade",
        dependency_counts=counts,
        will_release_resource_code=True,
        resource_code_after_delete_can_be_recreated=True,
        warnings=list(WARNINGS),
        required_confirmation=required,
    )


async def _delete_where_resource(
    session: AsyncSession, model: type, resource_id: uuid.UUID
) -> int:
    col = getattr(model, "resource_id", None)
    if col is None:
        return 0
    result = await session.execute(delete(model).where(col == resource_id))
    return int(result.rowcount or 0)


async def _delete_batch_events(session: AsyncSession, resource_id: uuid.UUID) -> int:
    batch_ids = select(ImportBatch.id).where(ImportBatch.resource_id == resource_id)
    result = await session.execute(
        delete(ImportBatchEvent).where(ImportBatchEvent.batch_id.in_(batch_ids))
    )
    return int(result.rowcount or 0)


async def _delete_raw_macro96(session: AsyncSession, resource_id: uuid.UUID) -> int:
    if not await _table_exists(session, "raw_macro96_region_rows"):
        return 0
    result = await session.execute(
        text("DELETE FROM raw_macro96_region_rows WHERE resource_id = :rid"),
        {"rid": resource_id},
    )
    return int(result.rowcount or 0)


async def _create_audit_record(
    session: AsyncSession,
    *,
    resource_id: uuid.UUID,
    resource_code: str,
    source_atlas: str | None,
    request: ResourceDeleteRequest,
    dependency_counts: dict[str, Any],
    status: str,
    deleted_counts: dict[str, Any] | None = None,
    error_message: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> None:
    if not await _audit_table_available(session):
        logger.info(
            "destructive_delete_audit resource_id=%s resource_code=%s status=%s operator=%s",
            resource_id,
            resource_code,
            status,
            request.operator,
        )
        return
    record = DestructiveResourceDeleteRecord(
        resource_id=resource_id,
        resource_code=resource_code,
        source_atlas=source_atlas,
        operator=request.operator.strip(),
        reason=request.reason.strip(),
        confirmation_text=request.confirmation_text.strip(),
        delete_physical_files=request.delete_physical_files,
        dependency_counts_json=dependency_counts,
        deleted_counts_json=deleted_counts,
        status=status,
        error_message=error_message,
        started_at=started_at,
        finished_at=finished_at,
    )
    session.add(record)


def _validate_request(row: AtlasResource, request: ResourceDeleteRequest) -> None:
    expected = f"DELETE {row.resource_code}"
    if request.confirmation_text.strip() != expected:
        raise ResourceDeleteConfirmationError(
            f"confirmation_text must exactly match: {expected}"
        )
    if not request.operator.strip():
        raise ResourceDeleteValidationError("operator is required")
    if not request.reason.strip():
        raise ResourceDeleteValidationError("reason is required")


async def _collect_storage_paths(session: AsyncSession, resource_id: uuid.UUID) -> list[str]:
    rows = (
        await session.execute(
            select(ResourceFile.storage_path).where(ResourceFile.resource_id == resource_id)
        )
    ).scalars().all()
    return list(rows)


def _delete_physical_files(resource_id: uuid.UUID, storage_paths: list[str]) -> tuple[bool, str | None]:
    settings = get_settings()
    upload_root = Path(settings.upload_dir).resolve()
    resource_dir = upload_root / str(resource_id)
    errors: list[str] = []
    for rel in storage_paths:
        try:
            path = resolve_under_root(upload_root, rel)
            if path.is_file():
                path.unlink()
        except Exception as exc:
            errors.append(f"{rel}: {exc}")
    if resource_dir.is_dir():
        try:
            shutil.rmtree(resource_dir)
        except Exception as exc:
            errors.append(f"resource_dir: {exc}")
    if errors:
        return False, "; ".join(errors)
    return True, None


async def destructive_delete_resource(
    session: AsyncSession,
    resource_id: uuid.UUID,
    request: ResourceDeleteRequest,
) -> ResourceDeleteResult:
    row = await resource_service.get_resource(session, resource_id, include_archived=True)
    _validate_request(row, request)

    resource_code = row.resource_code
    source_atlas = row.source_atlas
    started_at = datetime.now(timezone.utc)
    dependency_counts = (await collect_dependency_counts(session, resource_id)).model_dump()
    storage_paths = await _collect_storage_paths(session, resource_id)

    await _create_audit_record(
        session,
        resource_id=resource_id,
        resource_code=resource_code,
        source_atlas=source_atlas,
        request=request,
        dependency_counts=dependency_counts,
        status="started",
        started_at=started_at,
    )

    deleted = DeletedCounts()
    try:
        deleted.promotion_records = await _delete_where_resource(
            session, PromotionRecord, resource_id
        )
        deleted.final_brain_regions = await _delete_where_resource(
            session, FinalBrainRegion, resource_id
        )
        deleted.candidate_llm_extractions = await _delete_where_resource(
            session, CandidateLlmExtraction, resource_id
        )
        deleted.candidate_rule_validation_results = await _delete_where_resource(
            session, CandidateRuleValidationResult, resource_id
        )
        deleted.candidate_review_records = await _delete_where_resource(
            session, CandidateReviewRecord, resource_id
        )
        deleted.rule_validation_runs = await _delete_where_resource(
            session, RuleValidationRun, resource_id
        )
        deleted.candidate_brain_regions = await _delete_where_resource(
            session, CandidateBrainRegion, resource_id
        )
        deleted.candidate_generation_runs = await _delete_where_resource(
            session, CandidateGenerationRun, resource_id
        )
        deleted.raw_aal3_region_labels = await _delete_where_resource(
            session, RawAal3RegionLabel, resource_id
        )
        deleted.raw_macro96_region_rows = await _delete_raw_macro96(session, resource_id)
        deleted.raw_parse_runs = await _delete_where_resource(session, RawParseRun, resource_id)
        deleted.import_batch_events = await _delete_batch_events(session, resource_id)
        deleted.import_batch_files = await _delete_where_resource(
            session, ImportBatchFile, resource_id
        )
        deleted.import_batches = await _delete_where_resource(session, ImportBatch, resource_id)
        deleted.file_intermediate_artifacts = await _delete_where_resource(
            session, FileIntermediateArtifact, resource_id
        )
        deleted.file_normalization_runs = await _delete_where_resource(
            session, FileNormalizationRun, resource_id
        )
        deleted.resource_files = await _delete_where_resource(session, ResourceFile, resource_id)
        atlas_result = await session.execute(
            delete(AtlasResource).where(AtlasResource.id == resource_id)
        )
        deleted.atlas_resources = int(atlas_result.rowcount or 0)

        finished_at = datetime.now(timezone.utc)
        await _create_audit_record(
            session,
            resource_id=resource_id,
            resource_code=resource_code,
            source_atlas=source_atlas,
            request=request,
            dependency_counts=dependency_counts,
            deleted_counts=deleted.model_dump(),
            status="succeeded",
            started_at=started_at,
            finished_at=finished_at,
        )
        await session.commit()

        physical_ok = False
        physical_err: str | None = None
        if request.delete_physical_files:
            physical_ok, physical_err = _delete_physical_files(resource_id, storage_paths)

        logger.info(
            "destructive_delete_succeeded resource_id=%s resource_code=%s operator=%s",
            resource_id,
            resource_code,
            request.operator,
        )
        return ResourceDeleteResult(
            resource_id=resource_id,
            resource_code=resource_code,
            deleted_counts=deleted,
            resource_code_released=True,
            can_recreate_resource_code=True,
            physical_files_deleted=physical_ok if request.delete_physical_files else False,
            physical_files_error=physical_err,
        )
    except Exception as exc:
        await session.rollback()
        finished_at = datetime.now(timezone.utc)
        try:
            await _create_audit_record(
                session,
                resource_id=resource_id,
                resource_code=resource_code,
                source_atlas=source_atlas,
                request=request,
                dependency_counts=dependency_counts,
                status="failed",
                error_message=str(exc),
                started_at=started_at,
                finished_at=finished_at,
            )
            await session.commit()
        except Exception:
            await session.rollback()
        logger.exception(
            "destructive_delete_failed resource_id=%s resource_code=%s",
            resource_id,
            resource_code,
        )
        raise
