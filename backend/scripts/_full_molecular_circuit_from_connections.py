"""Full molecular connection -> circuit extraction (comprehensive)."""
from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.request

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

API = "http://127.0.0.1:8003"
OUT = r"D:\Tool\Coding\IDE\PyCharm\NeuroGraphIQ_KG_V3_1\backend\scripts\_full_circuit_run_id.txt"


async def load_all_molecular_connection_ids() -> list[str]:
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.mirror_kg import MirrorRegionConnection

    ids: list[str] = []
    async with AsyncSessionLocal() as s:
        q = (
            select(MirrorRegionConnection.id)
            .where(MirrorRegionConnection.granularity_level == "molecular_attr")
            .where(MirrorRegionConnection.mirror_status != "superseded")
            .where(MirrorRegionConnection.review_status != "rejected")
            .order_by(MirrorRegionConnection.id)
        )
        rows = (await s.execute(q)).scalars().all()
        ids = [str(x) for x in rows]
    return ids


def main() -> None:
    print("Loading all molecular_attr connection IDs...", flush=True)
    conn_ids = asyncio.run(load_all_molecular_connection_ids())
    print(f"connections={len(conn_ids)}", flush=True)
    if len(conn_ids) < 2:
        raise SystemExit("Not enough molecular connections")

    body = {
        "provider": "deepseek",
        "model_name": "deepseek-chat",
        "connection_ids": conn_ids,
        "candidates_per_pack": 16,
        "max_circuits": 200,
        "temperature": 0.45,
        "max_tokens": 16384,
        "pack_concurrency": 3,
        "skip_existing": False,
        "dry_run": False,
    }
    data = json.dumps(body).encode()
    print(f"POST body bytes={len(data):,} estimated packs~{len(conn_ids)//16}", flush=True)
    req = urllib.request.Request(
        f"{API}/api/llm-extraction/circuit-extraction/run",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=300).read().decode())
    rid = resp["run_id"]
    print(f"FULL_RUN={rid}", flush=True)
    print(json.dumps(resp, ensure_ascii=False, indent=2)[:1200], flush=True)
    open(OUT, "w", encoding="utf-8").write(rid)

    for i in range(100000):
        r = json.loads(
            urllib.request.urlopen(
                f"{API}/api/llm-extraction/circuit-extraction/runs/{rid}", timeout=30
            ).read().decode()
        )
        st = r.get("status")
        summary = r.get("result_summary_json") or {}
        print(
            f"[{i}] status={st} packs={r.get('succeeded_packs')}/{r.get('pack_count')} "
            f"circuits={r.get('circuit_count')} steps={r.get('step_count')} fns={r.get('function_count')} "
            f"failed={r.get('failed_packs')} no_findings={r.get('no_findings_packs')} "
            f"summary={summary}",
            flush=True,
        )
        if st in ("succeeded", "partially_succeeded", "failed", "cancelled", "completed"):
            print("DONE", json.dumps({k: r.get(k) for k in ('status','circuit_count','step_count','function_count','succeeded_packs','failed_packs','pack_count')}, ensure_ascii=False), flush=True)
            return
        time.sleep(60)


if __name__ == "__main__":
    main()
