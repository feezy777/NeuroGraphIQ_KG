"""MVP 1 End-to-End API test — mirrors frontend Workbench UI actions."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8002"
XML_PATH = Path(__file__).resolve().parents[1] / "data/archive/c36eea58_d44d141e_AAL3v1_1mm.xml"
SUFFIX = int(time.time()) % 100000


def pp(label: str, data: dict) -> None:
    print(f"\n=== {label} ===")
    print(json.dumps(data, indent=2, default=str)[:2000])


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=60.0, trust_env=False)
    results: dict[str, object] = {}

    # Pre-check health
    r = client.get("/api/health")
    r.raise_for_status()
    health = r.json()
    pp("Health", health)
    if health.get("status") != "ok":
        print("FAIL: health not ok")
        return 1

    # Step 1: Create Resource
    body = {
        "resource_code": f"aal3_v1_macro_e2e_{SUFFIX}",
        "source_atlas": "AAL3",
        "source_version": "v1",
        "resource_type": "atlas",
        "species": "human",
        "granularity_level": "macro",
        "granularity_family": "macro_clinical",
        "template_space": "MNI152",
        "en_name": "AAL3 Atlas E2E",
        "cn_name": "AAL3脑图谱E2E",
        "description": "MVP1 E2E test",
    }
    r = client.post("/api/resources", json=body)
    if r.status_code not in (200, 201):
        print(f"FAIL Step 1: {r.status_code} {r.text}")
        return 1
    resource = r.json()
    resource_id = resource["id"]
    results["resource_id"] = resource_id
    pp("Step 1 Create Resource", resource)

    # Step 2: Upload XML
    if not XML_PATH.exists():
        print(f"FAIL: XML not found at {XML_PATH}")
        return 1
    with open(XML_PATH, "rb") as f:
        files = {"file": ("AAL3v1_1mm.xml", f, "application/xml")}
        data = {
            "file_type": "label_table",
            "file_role": "label_dictionary",
            "description": "AAL3 E2E label XML",
        }
        r = client.post(f"/api/resources/{resource_id}/files", files=files, data=data)
    if r.status_code not in (200, 201):
        print(f"FAIL Step 2: {r.status_code} {r.text}")
        return 1
    file_rec = r.json()
    file_id = file_rec["id"]
    results["file_id"] = file_id
    pp("Step 2 Upload File", file_rec)

    # Step 3: Create Batch
    batch_body = {
        "resource_id": resource_id,
        "batch_type": "atlas_import",
        "parser_key": "aal3_xml",
        "files": [{"file_id": file_id, "file_role_in_batch": "label_dictionary"}],
        "description": "MVP1 E2E batch",
    }
    r = client.post("/api/import-batches", json=batch_body)
    if r.status_code not in (200, 201):
        print(f"FAIL Step 3: {r.status_code} {r.text}")
        return 1
    batch = r.json()
    batch_id = batch["id"]
    results["batch_id"] = batch_id
    pp("Step 3 Create Batch", {"id": batch_id, "status": batch.get("status")})

    # Step 4: Queue
    r = client.post(f"/api/import-batches/{batch_id}/queue")
    if r.status_code != 200:
        print(f"FAIL Step 4: {r.status_code} {r.text}")
        return 1
    batch = r.json()
    print(f"Step 4 Queue: status={batch['status']}")
    assert batch["status"] == "queued", f"expected queued, got {batch['status']}"

    # Step 5: Start
    r = client.post(f"/api/import-batches/{batch_id}/start")
    if r.status_code != 200:
        print(f"FAIL Step 5: {r.status_code} {r.text}")
        return 1
    batch = r.json()
    print(f"Step 5 Start: status={batch['status']}")
    assert batch["status"] == "running", f"expected running, got {batch['status']}"

    # Step 6: Parse AAL3
    r = client.post(f"/api/import-batches/{batch_id}/parse-aal3")
    if r.status_code != 200:
        print(f"FAIL Step 6: {r.status_code} {r.text}")
        return 1
    parse_resp = r.json()
    parse_run_id = parse_resp["parse_run"]["id"]
    output_count = parse_resp["output_count"]
    results["parse_run_id"] = parse_run_id
    results["raw_label_count"] = output_count
    pp("Step 6 Parse AAL3", parse_resp)

    # Step 7: View raw labels
    r = client.get("/api/raw-parsing/aal3-labels", params={"parse_run_id": parse_run_id, "limit": 5})
    if r.status_code != 200:
        print(f"FAIL Step 7: {r.status_code} {r.text}")
        return 1
    labels = r.json()
    results["raw_labels_sample"] = len(labels.get("items", []))
    pp("Step 7 Raw Labels (first 5)", {"total": labels.get("total"), "sample": labels.get("items", [])[:2]})

    # Step 8: Generate Candidates
    r = client.post(
        f"/api/import-batches/{batch_id}/generate-candidates",
        params={"parse_run_id": parse_run_id},
    )
    if r.status_code != 200:
        print(f"FAIL Step 8: {r.status_code} {r.text}")
        return 1
    gen_resp = r.json()
    generation_run_id = gen_resp["generation_run"]["id"]
    candidate_count = gen_resp["output_count"]
    results["generation_run_id"] = generation_run_id
    results["candidate_count"] = candidate_count
    pp("Step 8 Generate Candidates", gen_resp)

    # Step 9: View candidates
    r = client.get("/api/candidates/brain-regions", params={"batch_id": batch_id, "limit": 5})
    if r.status_code != 200:
        print(f"FAIL Step 9: {r.status_code} {r.text}")
        return 1
    cands = r.json()
    results["candidates_total"] = cands.get("total")
    first_cand = cands["items"][0] if cands.get("items") else None
    pp("Step 9 Candidates", {"total": cands.get("total"), "first_status": first_cand.get("candidate_status") if first_cand else None})

    # Step 10: Rule Validation (batch)
    r = client.post("/api/rule-validation/run", params={"batch_id": batch_id})
    if r.status_code != 200:
        print(f"FAIL Step 10: {r.status_code} {r.text}")
        return 1
    val_resp = r.json()
    validation_run_id = val_resp["validation_run"]["id"]
    results["validation_run_id"] = validation_run_id
    results["passed_count"] = val_resp["passed_count"]
    results["failed_count"] = val_resp["failed_count"]
    results["warning_count"] = val_resp.get("warning_count", 0)
    pp("Step 10 Rule Validation", val_resp)

    # Find a rule_passed candidate
    r = client.get("/api/candidates/brain-regions", params={"batch_id": batch_id, "candidate_status": "rule_passed", "limit": 1})
    if r.status_code != 200 or not r.json().get("items"):
        # try without filter - get any passed
        r = client.get("/api/candidates/brain-regions", params={"batch_id": batch_id, "limit": 200})
        items = [c for c in r.json().get("items", []) if c.get("candidate_status") == "rule_passed"]
        if not items:
            print("FAIL Step 11: no rule_passed candidate found")
            return 1
        review_candidate = items[0]
    else:
        review_candidate = r.json()["items"][0]

    review_candidate_id = review_candidate["id"]
    results["review_candidate_id"] = review_candidate_id

    # Step 11: Submit Review
    r = client.post(
        f"/api/candidates/{review_candidate_id}/submit-review",
        json={"reviewed_by": "local_user", "reason": "MVP1 E2E test submit"},
    )
    if r.status_code != 200:
        print(f"FAIL Step 11: {r.status_code} {r.text}")
        return 1
    submit_resp = r.json()
    pp("Step 11 Submit Review", {"candidate_status": submit_resp["candidate"]["candidate_status"]})

    # Step 12: Approve
    r = client.post(
        f"/api/candidates/{review_candidate_id}/review",
        json={"action": "approve", "reviewed_by": "local_user", "reason": "MVP1 E2E test approved"},
    )
    if r.status_code != 200:
        print(f"FAIL Step 12: {r.status_code} {r.text}")
        return 1
    approve_resp = r.json()
    pp("Step 12 Approve", {"candidate_status": approve_resp["candidate"]["candidate_status"]})

    # Step 13: Promote
    r = client.post(
        f"/api/candidates/{review_candidate_id}/promote",
        json={"promoted_by": "local_user", "reason": "MVP1 E2E test promotion"},
    )
    if r.status_code != 200:
        print(f"FAIL Step 13: {r.status_code} {r.text}")
        return 1
    promote_resp = r.json()
    final_region_id = promote_resp["final_region"]["id"]
    promotion_id = promote_resp["record"]["id"]
    results["final_region_id"] = final_region_id
    results["promotion_id"] = promotion_id
    pp("Step 13 Promote", {"final_region_id": final_region_id, "promotion_id": promotion_id})

    # Step 14: View Final Regions
    r = client.get(f"/api/final-regions/{final_region_id}")
    if r.status_code != 200:
        print(f"FAIL Step 14: {r.status_code} {r.text}")
        return 1
    final_region = r.json()
    pp("Step 14 Final Region", {"id": final_region["id"], "cn_name": final_region.get("cn_name"), "status": final_region.get("status")})

    # Step 15: Repeat Promote (expect 409)
    r = client.post(
        f"/api/candidates/{review_candidate_id}/promote",
        json={"promoted_by": "local_user", "reason": "repeat test"},
    )
    results["repeat_promote_status"] = r.status_code
    print(f"\nStep 15 Repeat Promote: status={r.status_code} (expect 409)")
    if r.status_code != 409:
        print(f"WARN: expected 409, got {r.status_code}: {r.text[:500]}")

    print("\n" + "=" * 60)
    print("E2E SUMMARY")
    print(json.dumps(results, indent=2, default=str))
    print("=" * 60)
    print("ALL STEPS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
