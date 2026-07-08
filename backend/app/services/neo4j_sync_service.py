"""Neo4j graph sync service — PostgreSQL → Neo4j full-sync."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from py2neo import Graph, Node, Relationship

from app.config import get_settings

logger = logging.getLogger(__name__)

# ── Connection ──────────────────────────────────────────────────────────

def _get_graph() -> Graph:
    settings = get_settings()
    uri = getattr(settings, 'neo4j_uri', 'bolt://localhost:7687')
    user = getattr(settings, 'neo4j_user', 'neo4j')
    pwd = getattr(settings, 'neo4j_password', 'password123')
    return Graph(uri, auth=(user, pwd))


# ── Sync ────────────────────────────────────────────────────────────────

async def sync_all() -> dict[str, int]:
    """Full sync: clear Neo4j → import all regions, connections, circuits."""
    import asyncio
    from app.database import get_session

    graph = _get_graph()

    # Clear all
    graph.run("MATCH (n) DETACH DELETE n")

    counts = {"regions": 0, "connections": 0, "circuits": 0, "memberships": 0}

    async with get_session() as session:
        from sqlalchemy import text

        # ── Regions ─────────────────────────────────────────────────────
        rows = await session.execute(text(
            "SELECT id, en_name, cn_name, laterality FROM candidate_brain_regions "
            "WHERE batch_id = (SELECT id FROM import_batches WHERE source_atlas = 'Macro96' LIMIT 1) "
            "LIMIT 96"
        ))
        tx = graph.begin()
        for row in rows:
            node = Node("Region", id=str(row[0]), name_en=row[1] or "",
                        name_cn=row[2] or "", laterality=row[3] or "")
            tx.create(node)
            counts["regions"] += 1
        tx.commit()

        # ── Connections ─────────────────────────────────────────────────
        rows = await session.execute(text(
            "SELECT id, source_region_candidate_id, target_region_candidate_id, "
            "connection_type, confidence, strength, source_region_name_en, target_region_name_en "
            "FROM mirror_region_connections LIMIT 5000"
        ))
        tx = graph.begin()
        for row in rows:
            cid, src, tgt, ctype, conf, strength, sname, tname = row
            node = Node("Connection", id=str(cid), type=ctype or "unknown",
                        confidence=float(conf or 0), strength=float(strength or 0),
                        source_name=sname or "", target_name=tname or "")
            tx.create(node)
            if src:
                tx.create(Relationship.node("Region", id=str(src)), "SOURCE_OF", node)
            if tgt:
                tx.create(Relationship.node("Region", id=str(tgt)), "TARGET_OF", node)
            counts["connections"] += 1
        tx.commit()

        # ── Circuits ────────────────────────────────────────────────────
        rows = await session.execute(text(
            "SELECT id, circuit_name, circuit_type, confidence, "
            "normalized_payload_json->'formal_field_overlay'->>'canonical_start_region_id' as sid, "
            "normalized_payload_json->'formal_field_overlay'->>'canonical_end_region_id' as eid "
            "FROM mirror_region_circuits LIMIT 500"
        ))
        tx = graph.begin()
        for row in rows:
            cid, name, ctype, conf, sid, eid = row
            node = Node("Circuit", id=str(cid), name=name or "", circuit_class=ctype or "",
                        confidence=float(conf or 0))
            tx.create(node)
            if sid:
                tx.create(Relationship(node, "STARTS_AT", Node("Region", id=sid)))
            if eid:
                tx.create(Relationship(node, "ENDS_AT", Node("Region", id=eid)))
            counts["circuits"] += 1
        tx.commit()

        # ── Memberships ─────────────────────────────────────────────────
        rows = await session.execute(text(
            "SELECT circuit_id, projection_id, verification_status, confidence "
            "FROM mirror_circuit_projection_memberships LIMIT 5000"
        ))
        tx = graph.begin()
        for row in rows:
            cid, pid, vstatus, conf = row
            tx.create(Relationship(
                Node("Circuit", id=str(cid)), "INCLUDES",
                Node("Connection", id=str(pid)),
                status=vstatus or "circuit_supported",
                confidence=float(conf or 0),
            ))
            counts["memberships"] += 1
        tx.commit()

    return counts


_sync_status: dict[str, Any] = {"last_sync": None, "counts": {}, "running": False}

def get_sync_status() -> dict[str, Any]:
    return _sync_status

async def trigger_sync() -> dict[str, int]:
    _sync_status["running"] = True
    try:
        counts = await sync_all()
        _sync_status["counts"] = counts
        _sync_status["last_sync"] = datetime.now(timezone.utc).isoformat()
        return counts
    finally:
        _sync_status["running"] = False
