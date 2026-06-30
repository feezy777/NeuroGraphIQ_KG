"""Candidate pool CRUD — cross-batch candidate accumulation for LLM extraction."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_pool import CandidatePool, CandidatePoolMembership
from app.models.candidate import CandidateBrainRegion


def _compute_pair_count(n: int) -> int:
    if n < 2:
        return 0
    return n * (n - 1) // 2


async def create_pool(
    session: AsyncSession,
    *,
    name: str | None,
    candidate_ids: list[uuid.UUID],
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    source_atlas: str,
    granularity_level: str,
    granularity_family: str | None,
) -> CandidatePool:
    """Create a candidate pool with initial members."""
    q = select(CandidateBrainRegion).where(CandidateBrainRegion.id.in_(candidate_ids))
    result = await session.execute(q)
    candidates = list(result.scalars().all())
    if len(candidates) < 2:
        raise ValueError("At least 2 valid candidate IDs are required")

    pool = CandidatePool(
        name=name,
        resource_id=resource_id or candidates[0].resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas or candidates[0].source_atlas,
        granularity_level=granularity_level or candidates[0].granularity_level,
        granularity_family=granularity_family or candidates[0].granularity_family,
        candidate_count=len(candidate_ids),
        pair_count=_compute_pair_count(len(candidate_ids)),
    )
    session.add(pool)
    await session.flush()

    for cid in candidate_ids:
        session.add(CandidatePoolMembership(pool_id=pool.id, candidate_id=cid))

    await session.flush()
    await session.refresh(pool, ["memberships"])
    return pool


async def get_pool(
    session: AsyncSession,
    pool_id: uuid.UUID,
    *,
    include_memberships: bool = True,
) -> CandidatePool | None:
    from sqlalchemy.orm import selectinload

    q = select(CandidatePool).where(CandidatePool.id == pool_id)
    if include_memberships:
        q = q.options(selectinload(CandidatePool.memberships))
    result = await session.execute(q)
    return result.scalar_one_or_none()


async def list_pools(
    session: AsyncSession,
    *,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[CandidatePool], int]:
    from sqlalchemy.orm import selectinload

    base = select(CandidatePool)
    if source_atlas:
        base = base.where(CandidatePool.source_atlas == source_atlas)
    if granularity_level:
        base = base.where(CandidatePool.granularity_level == granularity_level)
    if granularity_family:
        base = base.where(CandidatePool.granularity_family == granularity_family)
    if status:
        base = base.where(CandidatePool.status == status)

    count_q = select(func.count()).select_from(base.subquery())
    total = int((await session.execute(count_q)).scalar_one() or 0)

    q = (
        base.order_by(CandidatePool.created_at.desc())
        .options(selectinload(CandidatePool.memberships))
        .limit(limit)
        .offset(offset)
    )
    pools = list((await session.execute(q)).scalars().all())
    return pools, total


async def add_members(
    session: AsyncSession,
    pool_id: uuid.UUID,
    candidate_ids: list[uuid.UUID],
) -> CandidatePool:
    pool = await get_pool(session, pool_id)
    if pool is None:
        raise KeyError(f"Pool {pool_id} not found")

    existing = {m.candidate_id for m in pool.memberships}
    new_ids = [cid for cid in candidate_ids if cid not in existing]
    for cid in new_ids:
        session.add(CandidatePoolMembership(pool_id=pool_id, candidate_id=cid))

    pool.candidate_count = len(existing) + len(new_ids)
    pool.pair_count = _compute_pair_count(pool.candidate_count)
    await session.flush()
    await session.refresh(pool, ["memberships"])
    return pool


async def remove_members(
    session: AsyncSession,
    pool_id: uuid.UUID,
    candidate_ids: list[uuid.UUID],
) -> CandidatePool:
    pool = await get_pool(session, pool_id)
    if pool is None:
        raise KeyError(f"Pool {pool_id} not found")

    await session.execute(
        delete(CandidatePoolMembership).where(
            CandidatePoolMembership.pool_id == pool_id,
            CandidatePoolMembership.candidate_id.in_(candidate_ids),
        )
    )
    remaining = {m.candidate_id for m in pool.memberships} - set(candidate_ids)
    pool.candidate_count = len(remaining)
    pool.pair_count = _compute_pair_count(pool.candidate_count)
    await session.flush()
    await session.refresh(pool, ["memberships"])
    return pool


async def replace_pool_for_scope(
    session: AsyncSession,
    *,
    name: str | None,
    candidate_ids: list[uuid.UUID],
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    source_atlas: str,
    granularity_level: str,
    granularity_family: str | None,
) -> CandidatePool:
    """Idempotent: one active pool per scope with exactly the given members."""
    deduped_ids = list(dict.fromkeys(candidate_ids))
    q = select(CandidateBrainRegion).where(CandidateBrainRegion.id.in_(deduped_ids))
    result = await session.execute(q)
    candidates = list(result.scalars().all())
    if len(candidates) < 2:
        raise ValueError("At least 2 valid candidate IDs are required")

    pools, _ = await list_pools(
        session,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        granularity_family=granularity_family,
        status="active",
        limit=100,
    )
    primary = pools[0] if pools else None
    for extra in pools[1:]:
        await delete_pool(session, extra.id)

    resolved_resource_id = resource_id or candidates[0].resource_id
    resolved_batch_id = batch_id
    resolved_atlas = source_atlas or candidates[0].source_atlas
    resolved_level = granularity_level or candidates[0].granularity_level
    resolved_family = granularity_family or candidates[0].granularity_family

    if primary is None:
        pool = CandidatePool(
            name=name,
            resource_id=resolved_resource_id,
            batch_id=resolved_batch_id,
            source_atlas=resolved_atlas,
            granularity_level=resolved_level,
            granularity_family=resolved_family,
            candidate_count=len(deduped_ids),
            pair_count=_compute_pair_count(len(deduped_ids)),
        )
        session.add(pool)
        await session.flush()
    else:
        pool = primary
        await session.execute(
            delete(CandidatePoolMembership).where(
                CandidatePoolMembership.pool_id == pool.id,
            )
        )
        pool.name = name or pool.name
        pool.resource_id = resolved_resource_id
        pool.batch_id = resolved_batch_id
        pool.source_atlas = resolved_atlas
        pool.granularity_level = resolved_level
        pool.granularity_family = resolved_family
        pool.candidate_count = len(deduped_ids)
        pool.pair_count = _compute_pair_count(len(deduped_ids))

    for cid in deduped_ids:
        session.add(CandidatePoolMembership(pool_id=pool.id, candidate_id=cid))

    await session.flush()
    await session.refresh(pool, ["memberships"])
    return pool


async def delete_pool(session: AsyncSession, pool_id: uuid.UUID) -> bool:
    pool = await session.get(CandidatePool, pool_id)
    if pool is None:
        return False
    await session.delete(pool)
    await session.flush()
    return True


async def resolve_pool_candidate_ids(
    session: AsyncSession,
    pool_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Resolve all candidate IDs in a pool for extraction use."""
    q = select(CandidatePoolMembership.candidate_id).where(
        CandidatePoolMembership.pool_id == pool_id
    )
    result = await session.execute(q)
    return [row[0] for row in result.all()]
