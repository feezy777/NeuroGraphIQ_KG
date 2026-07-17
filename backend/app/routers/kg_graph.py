"""Graph API routes — PostgreSQL-based graph data (Neo4j optional)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

router = APIRouter()


@router.get("/data")
async def get_graph_data(
    session: AsyncSession = Depends(get_db),
    limit_connections: int = Query(default=50000, ge=1, le=200000),
    limit_regions: int = Query(default=5000, ge=1, le=50000),
    granularity_level: str | None = Query(default=None),
):
    """Return nodes + edges for graph visualization, scoped by granularity.

    Optimised: connections are filtered in SQL via a subquery on the same
    granularity level so the DB does the heavy lifting instead of loading
    every row into Python memory.
    """
    # ── Regions ──────────────────────────────────────────────────────────
    if granularity_level:
        regions = await session.execute(text(
            "SELECT id, en_name, cn_name, laterality FROM candidate_brain_regions "
            "WHERE granularity_level = :gran ORDER BY en_name LIMIT :rlim"
        ), {"gran": granularity_level, "rlim": limit_regions})
    else:
        regions = await session.execute(text(
            "SELECT id, en_name, cn_name, laterality FROM candidate_brain_regions "
            "WHERE candidate_status = 'rule_passed' ORDER BY en_name LIMIT :rlim"
        ), {"rlim": limit_regions})
    nodes = [
        {"id": str(r[0]), "type": "region", "label": r[1] or r[2] or "?",
         "group": "region", "name_en": r[1] or "", "name_cn": r[2] or "",
         "laterality": r[3] or ""}
        for r in regions.fetchall()
    ]
    if not nodes:
        return {"nodes": [], "edges": [], "granularity_level": granularity_level,
                "stats": {"regions": 0, "connections": 0}}

    # ── Connections — SQL-side join to filter by region granularity ─────────
    # Only return edges where BOTH endpoints belong to the requested granularity.
    # This avoids loading 100k rows and filtering in Python.
    if granularity_level:
        conn_sql = text("""
            SELECT mc.id, mc.source_region_candidate_id, mc.target_region_candidate_id,
                   mc.connection_type, mc.confidence, mc.strength,
                   mc.source_region_name_en, mc.target_region_name_en
            FROM mirror_region_connections mc
            WHERE mc.granularity_level = :gran
              AND mc.source_region_candidate_id IS NOT NULL
              AND mc.target_region_candidate_id IS NOT NULL
              AND mc.source_region_name_en IS NOT NULL
            ORDER BY mc.confidence DESC
            LIMIT :lim
        """)
        conn_params: dict = {"gran": granularity_level, "lim": limit_connections}
    else:
        # Without granularity, filter to rule_passed candidates via subquery
        conn_sql = text("""
            SELECT mc.id, mc.source_region_candidate_id, mc.target_region_candidate_id,
                   mc.connection_type, mc.confidence, mc.strength,
                   mc.source_region_name_en, mc.target_region_name_en
            FROM mirror_region_connections mc
            WHERE mc.source_region_candidate_id IN (
                SELECT id FROM candidate_brain_regions WHERE candidate_status = 'rule_passed'
            )
              AND mc.target_region_candidate_id IN (
                SELECT id FROM candidate_brain_regions WHERE candidate_status = 'rule_passed'
            )
              AND mc.source_region_name_en IS NOT NULL
            ORDER BY mc.confidence DESC
            LIMIT :lim
        """)
        conn_params = {"lim": limit_connections}

    conns = await session.execute(conn_sql, conn_params)
    edges = []
    for row in conns.fetchall():
        cid, src, tgt, ctype, conf, strength, sname, tname = row
        edges.append({
            "id": str(cid), "source": str(src), "target": str(tgt),
            "type": ctype or "unknown", "confidence": float(conf or 0),
            "strength": float(strength or 0),
            "source_name": sname or "", "target_name": tname or "",
        })

    return {
        "nodes": nodes,
        "edges": edges,
        "granularity_level": granularity_level,
        "stats": {"regions": len(nodes), "connections": len(edges)},
    }
