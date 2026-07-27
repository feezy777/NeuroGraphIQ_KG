"""Monitor composite smoke run until terminal status."""
import json
import time
import urllib.request

API = "http://127.0.0.1:8003"
rid = open(
    r"D:\Tool\Coding\IDE\PyCharm\NeuroGraphIQ_KG_V3_1\backend\scripts\_smoke_run_id.txt"
).read().strip()
print("monitoring", rid, flush=True)

for i in range(80):
    r = json.loads(
        urllib.request.urlopen(
            f"{API}/api/llm-extraction/composite-workflows/runs/{rid}", timeout=30
        ).read().decode()
    )
    st = r.get("status")
    steps = [
        (s.get("step_key"), s.get("status"), s.get("created_counts"))
        for s in (r.get("steps") or [])
    ]
    print(f"[{i}] status={st} steps={steps} errors={(r.get('errors') or [])[:1]}", flush=True)
    if st in (
        "succeeded",
        "partially_succeeded",
        "failed",
        "cleanup_done",
        "no_edges",
        "cancelled",
    ):
        print("DONE", flush=True)
        print(
            json.dumps(
                {
                    "status": st,
                    "errors": r.get("errors"),
                    "warnings": (r.get("warnings") or [])[:8],
                },
                ensure_ascii=False,
            )[:2000],
            flush=True,
        )
        break
    time.sleep(15)
else:
    print("TIMEOUT still", st, flush=True)
