"""Resource Registry business logic.

Structured audit_log table is not implemented yet; actions are logged via Python logger.
See Logging & Audit module for future persistence.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion, CandidateGenerationRun
from app.models.human_review import CandidateReviewRecord
from app.models.import_batch import ImportBatch
from app.models.promotion import FinalBrainRegion, PromotionRecord
from app.models.raw_parsing import RawAal3RegionLabel, RawParseRun
from app.models.resource import AtlasResource
from app.models.resource_file import ResourceFile
from app.models.rule_validation import RuleValidationRun
from app.schemas.resource import ResourceCreate, ResourceUpdate

logger = logging.getLogger(__name__)


class ResourceNotFoundError(Exception):
    pass


class ResourceCodeConflictError(Exception):
    def __init__(self, resource_code: str, existing: AtlasResource | None = None) -> None:
        super().__init__(resource_code)
        self.resource_code = resource_code
        self.existing = existing


class ResourceActiveCodeConflictError(Exception):
    def __init__(self, resource_code: str, existing_id: uuid.UUID) -> None:
        super().__init__(resource_code)
        self.resource_code = resource_code
        self.existing_id = existing_id


class ResourceHasDependenciesError(Exception):
    def __init__(self, resource_id: uuid.UUID, dependency_counts: dict[str, int]) -> None:
        super().__init__(str(resource_id))
        self.resource_id = resource_id
        self.dependency_counts = dependency_counts


class ResourceNotArchivedError(Exception):
    pass


@dataclass(frozen=True)
class ResourceDependencyCounts:
    files: int = 0
    batches: int = 0
    raw_rows: int = 0
    candidates: int = 0
    final_regions: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "files": self.files,
            "batches": self.batches,
            "raw_rows": self.raw_rows,
            "candidates": self.candidates,
            "final_regions": self.final_regions,
        }

    @property
    def total(self) -> int:
        return self.files + self.batches + self.raw_rows + self.candidates + self.final_regions


def _log_action(
    *,
    event_type: str,
    action: str,
    result: str,
    resource_id: uuid.UUID | None = None,
    resource_code: str | None = None,
    error: str | None = None,
) -> None:
    logger.info(
        "event_type=%s action=%s result=%s resource_id=%s resource_code=%s error=%s",
        event_type,
        action,
        result,
        resource_id,
        resource_code,
        error,
    )


def _existing_resource_summary(row: AtlasResource) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "resource_code": row.resource_code,
        "source_atlas": row.source_atlas,
        "source_version": row.source_version,
        "granularity_level": row.granularity_level,
        "granularity_family": row.granularity_family,
        "status": row.status,
        "cn_name": row.cn_name,
        "en_name": row.en_name,
    }


def build_duplicate_resource_detail(
    existing: AtlasResource,
    counts: ResourceDependencyCounts,
) -> dict[str, Any]:
    is_active = existing.deleted_at is None and existing.status == "active"
    can_restore = not is_active
    can_purge = not is_active and counts.total == 0
    can_destructive_delete = not is_active
    if is_active:
        suggestion = (
            "Use the existing active resource, or create a new version with a different resource_code."
        )
    elif can_destructive_delete:
        suggestion = (
            "Restore the existing resource, or run destructive delete with confirmation before recreating."
        )
    else:
        suggestion = (
            "Restore and reuse this resource, or create a new version with a different resource_code."
        )
    return {
        "code": "DUPLICATE_RESOURCE_CODE",
        "message": "Resource code already exists.",
        "resource_code": existing.resource_code,
        "existing_resource": _existing_resource_summary(existing),
        "can_restore": can_restore,
        "can_purge": can_purge,
        "can_destructive_delete": can_destructive_delete,
        "delete_preview_url": f"/api/resources/{existing.id}/delete-preview",
        "dependency_counts": counts.as_dict(),
        "suggestion": suggestion,
    }


async def count_resource_dependencies(
    session: AsyncSession,
    resource_id: uuid.UUID,
) -> ResourceDependencyCounts:
    async def _count(model: type, column) -> int:
        q = select(func.count()).select_from(model).where(column == resource_id)
        return int((await session.execute(q)).scalar_one())

    files = await _count(ResourceFile, ResourceFile.resource_id)
    batches = await _count(ImportBatch, ImportBatch.resource_id)
    raw_aal3 = await _count(RawAal3RegionLabel, RawAal3RegionLabel.resource_id)
    raw_parse_runs = await _count(RawParseRun, RawParseRun.resource_id)
    candidate_gen = await _count(CandidateGenerationRun, CandidateGenerationRun.resource_id)
    candidates = await _count(CandidateBrainRegion, CandidateBrainRegion.resource_id)
    final_regions = await _count(FinalBrainRegion, FinalBrainRegion.resource_id)

    raw_rows = raw_aal3 + raw_parse_runs + candidate_gen
    return ResourceDependencyCounts(
        files=files,
        batches=batches,
        raw_rows=raw_rows,
        candidates=candidates,
        final_regions=final_regions,
    )


async def count_extended_resource_dependencies(
    session: AsyncSession,
    resource_id: uuid.UUID,
) -> int:
    counts = await count_resource_dependencies(session, resource_id)
    async def _count(model: type, column) -> int:
        q = select(func.count()).select_from(model).where(column == resource_id)
        return int((await session.execute(q)).scalar_one())

    review_records = await _count(CandidateReviewRecord, CandidateReviewRecord.resource_id)
    rule_runs = await _count(RuleValidationRun, RuleValidationRun.resource_id)
    promotions = await _count(PromotionRecord, PromotionRecord.resource_id)
    return counts.total + review_records + rule_runs + promotions


async def get_resource_by_code_any(
    session: AsyncSession,
    resource_code: str,
) -> AtlasResource | None:
    row = (
        await session.execute(
            select(AtlasResource).where(AtlasResource.resource_code == resource_code)
        )
    ).scalar_one_or_none()
    return row


async def list_resources(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    status: str | None = None,
    include_deleted: bool = False,
) -> tuple[list[AtlasResource], int]:
    base = select(AtlasResource)
    count_q = select(func.count()).select_from(AtlasResource)

    status_norm = (status or "").strip().lower() or None
    if status_norm == "all":
        pass
    elif status_norm == "archived":
        base = base.where(AtlasResource.deleted_at.isnot(None))
        count_q = count_q.where(AtlasResource.deleted_at.isnot(None))
    else:
        if not include_deleted:
            base = base.where(AtlasResource.deleted_at.is_(None))
            count_q = count_q.where(AtlasResource.deleted_at.is_(None))
        if status_norm:
            base = base.where(AtlasResource.status == status_norm)
            count_q = count_q.where(AtlasResource.status == status_norm)

    if source_atlas:
        base = base.where(AtlasResource.source_atlas == source_atlas)
        count_q = count_q.where(AtlasResource.source_atlas == source_atlas)
    if granularity_level:
        base = base.where(AtlasResource.granularity_level == granularity_level)
        count_q = count_q.where(AtlasResource.granularity_level == granularity_level)
    if granularity_family:
        base = base.where(AtlasResource.granularity_family == granularity_family)
        count_q = count_q.where(AtlasResource.granularity_family == granularity_family)

    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(AtlasResource.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_resource(
    session: AsyncSession,
    resource_id: uuid.UUID,
    *,
    include_archived: bool = False,
) -> AtlasResource:
    row = await session.get(AtlasResource, resource_id)
    if row is None:
        raise ResourceNotFoundError(str(resource_id))
    if not include_archived and row.deleted_at is not None:
        raise ResourceNotFoundError(str(resource_id))
    return row


async def create_resource(session: AsyncSession, payload: ResourceCreate) -> AtlasResource:
    existing = await get_resource_by_code_any(session, payload.resource_code)
    if existing is not None:
        counts = await count_resource_dependencies(session, existing.id)
        _log_action(
            event_type="resource_registry",
            action="create",
            result="error",
            resource_code=payload.resource_code,
            error="duplicate resource_code",
        )
        raise ResourceCodeConflictError(payload.resource_code, existing)

    row = AtlasResource(
        resource_code=payload.resource_code,
        source_atlas=payload.source_atlas,
        source_version=payload.source_version,
        resource_type=payload.resource_type.value,
        species=payload.species.value,
        granularity_level=payload.granularity_level.value,
        granularity_family=payload.granularity_family.value,
        template_space=payload.template_space.value,
        cn_name=payload.cn_name,
        en_name=payload.en_name,
        description=payload.description,
        remark=payload.remark,
        status=payload.status.value,
    )
    session.add(row)
    try:
        await session.commit()
        await session.refresh(row)
    except IntegrityError as exc:
        await session.rollback()
        existing = await get_resource_by_code_any(session, payload.resource_code)
        _log_action(
            event_type="resource_registry",
            action="create",
            result="error",
            resource_code=payload.resource_code,
            error=str(exc.orig),
        )
        raise ResourceCodeConflictError(payload.resource_code, existing) from exc

    _log_action(
        event_type="resource_registry",
        action="create",
        result="success",
        resource_id=row.id,
        resource_code=row.resource_code,
    )
    return row


async def update_resource(
    session: AsyncSession, resource_id: uuid.UUID, payload: ResourceUpdate
) -> AtlasResource:
    row = await get_resource(session, resource_id)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(row, key, value.value if hasattr(value, "value") else value)

    try:
        await session.commit()
        await session.refresh(row)
    except IntegrityError as exc:
        await session.rollback()
        _log_action(
            event_type="resource_registry",
            action="update",
            result="error",
            resource_id=resource_id,
            resource_code=row.resource_code,
            error=str(exc.orig),
        )
        raise

    _log_action(
        event_type="resource_registry",
        action="update",
        result="success",
        resource_id=row.id,
        resource_code=row.resource_code,
    )
    return row


async def soft_delete_resource(session: AsyncSession, resource_id: uuid.UUID) -> AtlasResource:
    row = await get_resource(session, resource_id)
    now = datetime.now(timezone.utc)
    row.deleted_at = now
    row.status = "archived"
    await session.commit()
    await session.refresh(row)

    _log_action(
        event_type="resource_registry",
        action="archive",
        result="success",
        resource_id=row.id,
        resource_code=row.resource_code,
    )
    return row


async def restore_resource(session: AsyncSession, resource_id: uuid.UUID) -> AtlasResource:
    row = await get_resource(session, resource_id, include_archived=True)
    if row.deleted_at is None and row.status == "active":
        return row

    conflict = (
        await session.execute(
            select(AtlasResource.id).where(
                AtlasResource.resource_code == row.resource_code,
                AtlasResource.deleted_at.is_(None),
                AtlasResource.status == "active",
                AtlasResource.id != resource_id,
            )
        )
    ).scalar_one_or_none()
    if conflict is not None:
        raise ResourceActiveCodeConflictError(row.resource_code, conflict)

    row.deleted_at = None
    row.status = "active"
    await session.commit()
    await session.refresh(row)

    _log_action(
        event_type="resource_registry",
        action="restore",
        result="success",
        resource_id=row.id,
        resource_code=row.resource_code,
    )
    return row


async def purge_resource(session: AsyncSession, resource_id: uuid.UUID) -> None:
    row = await get_resource(session, resource_id, include_archived=True)
    counts = await count_resource_dependencies(session, resource_id)
    extended_total = await count_extended_resource_dependencies(session, resource_id)
    if extended_total > 0:
        raise ResourceHasDependenciesError(resource_id, counts.as_dict())

    resource_code = row.resource_code
    await session.delete(row)
    await session.commit()

    _log_action(
        event_type="resource_registry",
        action="purge",
        result="success",
        resource_id=resource_id,
        resource_code=resource_code,
    )
