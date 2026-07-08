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
    limit_connections: int = Query(default=200, ge=1, le=500),
    include_circuits: bool = Query(default=True),
):
    """Return nodes + edges for graph visualization."""
    # Regions (96 Macro96)
    regions = await session.execute(text(
        "SELECT id, en_name, cn_name, laterality FROM candidate_brain_regions "
        "WHERE candidate_status = 'rule_passed' LIMIT 96"
    ))
    nodes = [
        {"id": str(r[0]), "type": "region", "label": r[1] or r[2] or "?", "group": "region",
         "name_en": r[1] or "", "name_cn": r[2] or "", "laterality": r[3] or ""}
        for r in regions.fetchall()
    ]
    region_ids = {n["id"] for n in nodes}

    # Connections (filtered to macro96 regions)
    conns = await session.execute(text(
        "SELECT id, source_region_candidate_id, target_region_candidate_id, "
        "connection_type, confidence, strength, source_region_name_en, target_region_name_en "
        "FROM mirror_region_connections WHERE source_region_name_en IS NOT NULL "
        "LIMIT :lim"
    ), {"lim": limit_connections})
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

    # Circuits
    circuits = []
    if include_circuits:
        circs = await session.execute(text(
            "SELECT id, circuit_name, circuit_type, confidence, "
            "normalized_payload_json->'formal_field_overlay'->>'canonical_start_region_id' as sid, "
            "normalized_payload_json->'formal_field_overlay'->>'canonical_end_region_id' as eid "
            "FROM mirror_region_circuits WHERE circuit_name IS NOT NULL LIMIT 200"
        ))
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
        mems = await session.execute(text(
            "SELECT circuit_id, projection_id, verification_status, confidence "
            "FROM mirror_circuit_projection_memberships LIMIT 500"
        ))
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
        "stats": {"regions": len([n for n in nodes if n["type"] == "region"]),
                  "connections": len([e for e in edges if e["type"] not in ("STARTS_AT", "ENDS_AT", "INCLUDES")]),
                  "circuits": len([n for n in nodes if n["type"] == "circuit"]),
                  "memberships": len([e for e in edges if e["type"] == "INCLUDES"])},
    }
