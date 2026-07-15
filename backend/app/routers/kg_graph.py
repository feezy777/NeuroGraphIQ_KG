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
    limit_connections: int = Query(default=500, ge=1, le=5000),
    limit_regions: int = Query(default=1000, ge=1, le=5000),
    granularity_level: str | None = Query(default=None),
):
    """Return nodes + edges for graph visualization, scoped by granularity.

    When ``granularity_level`` is provided, every source table is filtered by its
    ``granularity_level`` column. Region candidates are NOT restricted to the
    Macro96 ``rule_passed`` pool in that case, because non-macro granularities
    (molecular_attr, fine_cyto, …) carry ``candidate_created`` status instead —
    otherwise those graphs would come back empty.
    """
    # ── Regions ──────────────────────────────────────────────────────────────
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
        {"id": str(r[0]), "type": "region", "label": r[1] or r[2] or "?", "group": "region",
         "name_en": r[1] or "", "name_cn": r[2] or "", "laterality": r[3] or ""}
        for r in regions.fetchall()
    ]
    region_ids = {n["id"] for n in nodes}

    # ── Connections (filtered to the loaded regions) ─────────────────────────
    conn_sql = (
        "SELECT id, source_region_candidate_id, target_region_candidate_id, "
        "connection_type, confidence, strength, source_region_name_en, target_region_name_en "
        "FROM mirror_region_connections WHERE source_region_name_en IS NOT NULL"
    )
    conn_params: dict = {"lim": limit_connections}
    if granularity_level:
        conn_sql += " AND granularity_level = :gran"
        conn_params["gran"] = granularity_level
    conn_sql += " LIMIT :lim"
    conns = await session.execute(text(conn_sql), conn_params)
    edges = []
    for row in conns.fetchall():
        cid, src, tgt, ctype, conf, strength, sname, tname = row
        if src and tgt and str(src) in region_ids and str(tgt) in region_ids:
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
        "stats": {"regions": len(nodes),
                  "connections": len(edges)},
    }
