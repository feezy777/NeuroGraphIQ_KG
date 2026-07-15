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
    include_circuits: bool = Query(default=True),
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

    # ── Circuits ─────────────────────────────────────────────────────────────
    circuits = []
    if include_circuits:
        circ_sql = (
            "SELECT id, circuit_name, circuit_type, confidence, "
            "normalized_payload_json->'formal_field_overlay'->>'canonical_start_region_id' as sid, "
            "normalized_payload_json->'formal_field_overlay'->>'canonical_end_region_id' as eid "
            "FROM mirror_region_circuits WHERE circuit_name IS NOT NULL"
        )
        circ_params: dict = {}
        if granularity_level:
            circ_sql += " AND granularity_level = :gran"
            circ_params["gran"] = granularity_level
        circ_sql += " LIMIT 200"
        circs = await session.execute(text(circ_sql), circ_params)
        for row in circs.fetchall():
            cid, name, ctype, conf, sid, eid = row
            cnode = {"id": str(cid), "type": "circuit", "label": name[:40] if name else "?",
                     "group": "circuit", "circuit_class": ctype or ""}
            nodes.append(cnode)
            if sid and str(sid) in region_ids:
                edges.append({"id": f"cstart_{cid}", "source": str(cid), "target": str(sid),
                              "type": "STARTS_AT", "confidence": 1.0, "strength": 0})
            if eid and str(eid) in region_ids:
                edges.append({"id": f"cend_{cid}", "source": str(cid), "target": str(eid),
                              "type": "ENDS_AT", "confidence": 1.0, "strength": 0})

        # Membership edges
        mem_sql = (
            "SELECT circuit_id, projection_id, verification_status, confidence "
            "FROM mirror_circuit_projection_memberships"
        )
        mem_params: dict = {}
        if granularity_level:
            mem_sql += " WHERE granularity_level = :gran"
            mem_params["gran"] = granularity_level
        mem_sql += " LIMIT 500"
        mems = await session.execute(text(mem_sql), mem_params)
        for row in mems.fetchall():
            mcid, mpid, vstatus, mconf = row
            edges.append({
                "id": f"mem_{mcid}_{mpid}", "source": str(mcid), "target": str(mpid),
                "type": "INCLUDES", "confidence": float(mconf or 0),
                "verification": vstatus or "circuit_supported",
            })

    return {
        "nodes": nodes,
        "edges": edges,
        "granularity_level": granularity_level,
        "stats": {"regions": len([n for n in nodes if n["type"] == "region"]),
                  "connections": len([e for e in edges if e["type"] not in ("STARTS_AT", "ENDS_AT", "INCLUDES")]),
                  "circuits": len([n for n in nodes if n["type"] == "circuit"]),
                  "memberships": len([e for e in edges if e["type"] == "INCLUDES"])},
    }
