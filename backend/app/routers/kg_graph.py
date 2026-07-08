"""Neo4j graph API routes."""

from fastapi import APIRouter, HTTPException

from app.services import neo4j_sync_service as n4s

router = APIRouter()


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
