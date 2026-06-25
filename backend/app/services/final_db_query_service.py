"""Final DB Query — read-only queries over final_brain_regions and promotion_records.

Boundaries (guide §6.2 / §25):
  - SELECT-only. No INSERT / UPDATE / DELETE on any table.
  - Does NOT write final_* / kg_* / candidate_* / promotion_records.
  - Does NOT trigger promotion, human review, rule validation, or LLM.
  - final_brain_regions is separate from candidate_brain_regions (never merged).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.promotion import FinalBrainRegion, PromotionRecord


class FinalRegionNotFoundError(Exception):
    pass


def _apply_filters(
    stmt,
    *,
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    source_atlas: str | None,
    source_version: str | None,
    laterality: str | None,
    granularity_level: str | None,
    granularity_family: str | None,
    status: str | None,
    keyword: str | None,
):
    if resource_id:
        stmt = stmt.where(FinalBrainRegion.resource_id == resource_id)
    if batch_id:
        stmt = stmt.where(FinalBrainRegion.batch_id == batch_id)
    if source_atlas:
        stmt = stmt.where(FinalBrainRegion.source_atlas == source_atlas)
    if source_version:
        stmt = stmt.where(FinalBrainRegion.source_version == source_version)
    if laterality:
        stmt = stmt.where(FinalBrainRegion.laterality == laterality)
    if granularity_level:
        stmt = stmt.where(FinalBrainRegion.granularity_level == granularity_level)
    if granularity_family:
        stmt = stmt.where(FinalBrainRegion.granularity_family == granularity_family)
    if status:
        stmt = stmt.where(FinalBrainRegion.status == status)
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                FinalBrainRegion.raw_name.ilike(pattern),
                FinalBrainRegion.std_name.ilike(pattern),
                FinalBrainRegion.en_name.ilike(pattern),
                FinalBrainRegion.cn_name.ilike(pattern),
            )
        )
    return stmt


async def list_final_regions(
    session: AsyncSession,
    *,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    source_version: str | None = None,
    laterality: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[FinalBrainRegion], int]:
    base = _apply_filters(
        select(FinalBrainRegion),
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        source_version=source_version,
        laterality=laterality,
        granularity_level=granularity_level,
        granularity_family=granularity_family,
        status=status,
        keyword=keyword,
    )
    count_q = _apply_filters(
        select(func.count()).select_from(FinalBrainRegion),
        resource_id=resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas,
        source_version=source_version,
        laterality=laterality,
        granularity_level=granularity_level,
        granularity_family=granularity_family,
        status=status,
        keyword=keyword,
    )
    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(FinalBrainRegion.promoted_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def get_final_region(
    session: AsyncSession, final_region_id: uuid.UUID
) -> FinalBrainRegion:
    row = await session.get(FinalBrainRegion, final_region_id)
    if row is None:
        raise FinalRegionNotFoundError(str(final_region_id))
    return row


async def get_final_region_provenance(
    session: AsyncSession, final_region_id: uuid.UUID
) -> tuple[FinalBrainRegion, list[PromotionRecord]]:
    """Return the final region plus all its promotion records (audit trail)."""
    region = await get_final_region(session, final_region_id)
    records_q = (
        select(PromotionRecord)
        .where(PromotionRecord.candidate_id == region.candidate_id)
        .order_by(PromotionRecord.created_at.desc())
    )
    records = list((await session.execute(records_q)).scalars().all())
    return region, records


async def summary(
    session: AsyncSession,
    *,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
) -> dict:
    """Aggregate counts by laterality and source_atlas."""
    lat_q = (
        select(FinalBrainRegion.laterality, func.count())
        .select_from(FinalBrainRegion)
        .where(FinalBrainRegion.status == "active")
        .group_by(FinalBrainRegion.laterality)
    )
    atlas_q = (
        select(FinalBrainRegion.source_atlas, func.count())
        .select_from(FinalBrainRegion)
        .where(FinalBrainRegion.status == "active")
        .group_by(FinalBrainRegion.source_atlas)
    )
    total_q = select(func.count()).select_from(FinalBrainRegion)

    if resource_id:
        lat_q = lat_q.where(FinalBrainRegion.resource_id == resource_id)
        atlas_q = atlas_q.where(FinalBrainRegion.resource_id == resource_id)
        total_q = total_q.where(FinalBrainRegion.resource_id == resource_id)
    if batch_id:
        lat_q = lat_q.where(FinalBrainRegion.batch_id == batch_id)
        atlas_q = atlas_q.where(FinalBrainRegion.batch_id == batch_id)
        total_q = total_q.where(FinalBrainRegion.batch_id == batch_id)

    total = int((await session.execute(total_q)).scalar_one())
    by_laterality = {lat: int(cnt) for lat, cnt in (await session.execute(lat_q)).all()}
    by_atlas = {atlas: int(cnt) for atlas, cnt in (await session.execute(atlas_q)).all()}

    return {
        "total": total,
        "by_laterality": by_laterality,
        "by_atlas": by_atlas,
    }
