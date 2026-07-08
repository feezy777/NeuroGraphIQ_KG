"""Neo4j graph API routes — sync, query, perturbation."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.services import neo4j_sync_service as n4s

router = APIRouter()

# ── Sync ─────────────────────────────────────────────────────────────────

@router.post("/sync")
async def trigger_sync():
    try:
        counts = await n4s.trigger_sync()
        return {"status": "ok", "counts": counts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sync/status")
async def sync_status():
    return n4s.get_sync_status()


# ── Query ────────────────────────────────────────────────────────────────

@router.get("/region/{region_id}/neighbors")
async def region_neighbors(region_id: str, depth: int = Query(default=1, ge=1, le=3)):
    """Expand region neighbors up to depth hops."""
    try:
        graph = n4s._get_graph()
        query = """
            MATCH (r:Region {id: $rid})
            OPTIONAL MATCH path = (r)-[*1..%d]-(neighbor:Region)
            RETURN r, collect(DISTINCT neighbor) as neighbors,
                   collect(DISTINCT relationships(path)) as edges
        """ % depth
        result = graph.run(query, rid=region_id).data()
        if not result:
            raise HTTPException(status_code=404, detail="Region not found")
        row = result[0]
        r = row["r"]
        return {
            "node": dict(r),
            "neighbors": [dict(n) for n in (row["neighbors"] or [])],
            "edges": len(row.get("edges", []) or []),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/circuit/{circuit_id}/path")
async def circuit_path(circuit_id: str):
    """Get full circuit path: regions + connections."""
    try:
        graph = n4s._get_graph()
        query = """
            MATCH (c:Circuit {id: $cid})
            OPTIONAL MATCH (c)-[:STARTS_AT]->(s:Region)
            OPTIONAL MATCH (c)-[:ENDS_AT]->(e:Region)
            OPTIONAL MATCH (c)-[:INCLUDES]->(conn:Connection)
            OPTIONAL MATCH (src:Region)-[:SOURCE_OF]->(conn)
            OPTIONAL MATCH (conn)-[:TARGET_OF]->(tgt:Region)
            RETURN c, collect(DISTINCT conn) as connections,
                   collect(DISTINCT s) as starts,
                   collect(DISTINCT e) as ends
        """
        result = graph.run(query, cid=circuit_id).data()
        if not result:
            raise HTTPException(status_code=404, detail="Circuit not found")
        row = result[0]
        return {
            "circuit": dict(row["c"]),
            "connections": [dict(c) for c in (row["connections"] or [])],
            "start_regions": [dict(r) for r in (row["starts"] or [])],
            "end_regions": [dict(r) for r in (row["ends"] or [])],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
async def search(q: str = Query(..., min_length=1)):
    """Search regions/circuits/connections by name."""
    try:
        graph = n4s._get_graph()
        query = """
            MATCH (n)
            WHERE (n:Region OR n:Circuit OR n:Connection)
              AND (toLower(n.name_en) CONTAINS toLower($q)
                   OR toLower(n.name_cn) CONTAINS toLower($q)
                   OR toLower(n.name) CONTAINS toLower($q))
            RETURN n LIMIT 20
        """
        results = graph.run(query, q=q).data()
        return {"items": [dict(r["n"]) for r in results], "total": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/global")
async def global_summary():
    """Return global graph stats."""
    try:
        graph = n4s._get_graph()
        query = """
            MATCH (r:Region)
            WITH count(r) as regions
            MATCH (c:Connection)
            WITH regions, count(c) as connections
            MATCH (ci:Circuit)
            RETURN regions, connections, count(ci) as circuits
        """
        stats = graph.run(query).data()[0]
        return dict(stats)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Perturbation ─────────────────────────────────────────────────────────

_perturbation_runs: dict[str, dict[str, Any]] = {}


@router.post("/perturb")
async def run_perturbation(body: dict):
    """Run perturbation: {mode, seed_region_id, signal_strength, max_hops}."""
    try:
        graph = n4s._get_graph()
        mode = body.get("mode", "enhance")
        seed_id = body["seed_region_id"]
        signal = float(body.get("signal_strength", 1.0))
        max_hops = int(body.get("max_hops", 3))

        if mode == "enhance":
            # BFS propagation along connections
            results = _bfs_propagate(graph, seed_id, signal, max_hops)
        elif mode == "remove":
            results = _remove_analysis(graph, seed_id)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown mode: {mode}")

        run_id = str(uuid.uuid4())[:12]
        _perturbation_runs[run_id] = results
        results["run_id"] = run_id
        return results
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _bfs_propagate(graph, seed_id: str, signal: float, max_hops: int) -> dict:
    """BFS propagation from seed region."""
    query = """
        MATCH (r:Region {id: $seed})
        OPTIONAL MATCH path = (r)-[*1..%d]-(neighbor:Region)
        RETURN r, collect(DISTINCT neighbor) as affected,
               collect(DISTINCT relationships(path)) as edges
    """ % max_hops
    data = graph.run(query, seed=seed_id).data()
    if not data:
        return {"error": "Region not found"}

    affected = {}
    total_impact = 0.0
    for n in (data[0].get("affected") or []):
        node = dict(n)
        impact = signal * (0.5 ** (max_hops - 1))  # decay per hop
        affected[node.get("id", "")] = {
            "name": node.get("name_en", node.get("name", "")),
            "impact": round(impact, 4),
        }
        total_impact += abs(impact)

    return {
        "mode": "enhance",
        "seed": dict(data[0]["r"]),
        "affected_regions": affected,
        "affected_count": len(affected),
        "total_impact": round(total_impact, 4),
        "max_hops": max_hops,
    }


def _remove_analysis(graph, seed_id: str) -> dict:
    """Analyze impact of removing a region."""
    query = """
        MATCH (r:Region {id: $seed})
        OPTIONAL MATCH (r)-[rel]-(neighbor)
        RETURN r, count(DISTINCT neighbor) as neighbor_count,
               collect(DISTINCT type(rel)) as rel_types
    """
    data = graph.run(query, seed=seed_id).data()
    if not data:
        return {"error": "Region not found"}

    row = data[0]
    return {
        "mode": "remove",
        "seed": dict(row["r"]),
        "direct_neighbors": row["neighbor_count"],
        "relation_types": row.get("rel_types", []),
        "impact": "removal would break these connections",
    }
