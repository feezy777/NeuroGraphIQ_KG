"""Query existing Mirror KG records to support skip-existing logic."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm_extraction_prompt_engineering import make_pair_id


async def query_existing_canonical_keys(
    session: AsyncSession,
    candidate_ids: list[uuid.UUID],
    *,
    force_reextract: bool = False,
) -> set[str]:
    """Return the set of make_pair_id(source, target) keys that already have MirrorRegionConnection records.

    If force_reextract is True, returns an empty set (skip nothing).
    """
    if force_reextract or not candidate_ids:
        return set()

    result = await session.execute(
        text("""
            SELECT DISTINCT source_region_candidate_id, target_region_candidate_id
            FROM mirror_region_connections
            WHERE source_region_candidate_id = ANY(:ids)
               OR target_region_candidate_id = ANY(:ids)
        """),
        {"ids": [str(cid) for cid in candidate_ids]},
    )
    keys: set[str] = set()
    for row in result.fetchall():
        if row[0] and row[1]:
            keys.add(make_pair_id(uuid.UUID(str(row[0])), uuid.UUID(str(row[1]))))
    return keys


async def query_existing_function_projection_ids(
    session: AsyncSession,
    candidate_ids: list[uuid.UUID],
    *,
    force_reextract: bool = False,
) -> set[str]:
    """Return the set of projection connection IDs that already have MirrorProjectionFunction records.

    If force_reextract is True, returns an empty set (skip nothing).
    """
    if force_reextract or not candidate_ids:
        return set()

    result = await session.execute(
        text("""
            SELECT DISTINCT mrc.id::text
            FROM mirror_projection_functions mpf
            JOIN mirror_region_connections mrc ON mpf.projection_id = mrc.id
            WHERE mrc.source_region_candidate_id = ANY(:ids)
               OR mrc.target_region_candidate_id = ANY(:ids)
        """),
        {"ids": [str(cid) for cid in candidate_ids]},
    )
    return {row[0] for row in result.fetchall() if row[0]}
