"""Start a small molecular circuit smoke composite run and monitor it."""
from __future__ import annotations
import json, time, urllib.request
API = "http://127.0.0.1:8003"

def get(path: str):
    return json.loads(urllib.request.urlopen(API + path, timeout=60).read().decode())

def post(path: str, body: dict):
    data = json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read().decode())

def main() -> None:
    before = get("/api/mirror-kg/circuits?granularity_level=molecular_attr&limit=1")["total"]
    cands = get("/api/candidates/brain-regions?granularity_level=molecular_attr&limit=5")
    cids = [i["id"] for i in cands["items"]]
    print(f"before_circuits={before} candidates={len(cids)}", flush=True)
    start = post("/api/llm-extraction/composite-workflows/start", {
        "workflow_type": "circuit_with_function_steps",
        "provider": "deepseek",
        "model_name": "deepseek-v4-pro",
        "dry_run": False,
        "create_mirror_records": True,
        "create_triples": True,
        "create_evidence": True,
        "granularity_level": "molecular_attr",
        "granularity_family": "molecular_attr",
        "candidate_ids": cids,
    })
    rid = start["workflow_run_id"]
    print(f"SMOKE_RUN={rid}", flush=True)
    open(r"D:\Tool\Coding\IDE\PyCharm\NeuroGraphIQ_KG_V3_1\backend\scripts\_smoke_run_id.txt", "w", encoding="utf-8").write(rid)
    for i in range(80):
        r = get(f"/api/llm-extraction/composite-workflows/runs/{rid}")
        st = r.get("status")
        steps = [(s.get("step_key"), s.get("status"), s.get("created_counts")) for s in (r.get("steps") or [])]
        print(f"[{i}] status={st} steps={steps}", flush=True)
        if st in ("succeeded", "partially_succeeded", "failed", "cleanup_done", "cancelled", "no_edges"):
            after = get("/api/mirror-kg/circuits?granularity_level=molecular_attr&limit=1")["total"]
            print(json.dumps({"final_status": st, "errors": r.get("errors"), "warnings": (r.get("warnings") or [])[:8], "circuits_before": before, "circuits_after": after}, ensure_ascii=False), flush=True)
            return
        time.sleep(12)
    print("TIMEOUT", flush=True)

if __name__ == "__main__":
    main()
