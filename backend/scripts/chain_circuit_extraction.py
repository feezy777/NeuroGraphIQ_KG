"""Wait for connection extraction to finish, then auto-start circuit extraction.
High quality: per-pack commit, full field coverage, dedup/merge.
"""
import time, json, urllib.request, sys

API = "http://127.0.0.1:8003"
CONN_RUN = "a415d08d-9ee1-42cd-b255-f2417e9d5aa4"

def check_run(rid):
    try:
        r = json.loads(urllib.request.urlopen(f"{API}/api/llm-extraction/composite-workflows/runs/{rid}", timeout=10).read().decode())
        return r.get("status")
    except: return None

def start_circuits():
    resp = json.loads(urllib.request.urlopen(f"{API}/api/candidates/brain-regions?granularity_level=molecular_attr&limit=600", timeout=30).read().decode())
    cids = [i["id"] for i in resp["items"]]
    body = json.dumps({"workflow_type":"circuit_with_function_steps","provider":"deepseek","dry_run":False,"create_mirror_records":True,"create_triples":True,"create_evidence":True,"granularity_level":"molecular_attr","candidate_ids":cids}).encode()
    req = urllib.request.Request(f"{API}/api/llm-extraction/composite-workflows/start", data=body, headers={"Content-Type":"application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    print(f"Circuit extraction started: {r['workflow_run_id']} | candidates={len(cids)} | pairs={r.get('pair_count',0):,}")
    # Print steps
    for s in r.get("steps",[]): print(f"  {s['step_label']}: {s['status']}")
    return r["workflow_run_id"]

# Wait for connection to finish
print(f"Waiting for connection run {CONN_RUN}...")
while True:
    status = check_run(CONN_RUN)
    r = json.loads(urllib.request.urlopen(f"{API}/api/llm-extraction/composite-workflows/runs/{CONN_RUN}", timeout=10).read().decode())
    s = r["steps"][0]; pa = s["execution_summary"]["provider_audit"]
    print(f"  {pa.get('processed_pack_count',0)}/{pa.get('pack_count',0)} ({pa.get('processed_pack_count',0)/pa.get('pack_count',0)*100:.1f}%) status={status}")
    if status in ("succeeded","partially_succeeded","no_edges","failed"):
        break
    time.sleep(120)

# Start circuits
print("\nConnection done! Starting circuit extraction...")
circuit_rid = start_circuits()
print(f"\nCircuit run: {circuit_rid}")
print("Monitor: curl http://127.0.0.1:8003/api/llm-extraction/composite-workflows/runs/{circuit_rid}")
