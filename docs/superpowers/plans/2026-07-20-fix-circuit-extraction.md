# Fix Circuit Extraction: Granularity Hardcode + Duplicate Name Handling

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix circuit extraction to correctly use the caller's granularity_level (not hardcoded "macro") and handle duplicate circuit names gracefully.

**Architecture:** Two-line fix in `llm_circuit_pack_service.py` + mirror service dedup for circuits. No new files needed.

**Tech Stack:** Python 3.11+, SQLAlchemy async, PostgreSQL

## Global Constraints

- Do NOT modify the composite workflow orchestrator
- Do NOT change the API contracts
- Existing circuits must not be affected
- Per-pack commit must continue to work

---

### Task 1: Fix granularity_level hardcode

**Files:**
- Modify: `backend/app/services/llm_circuit_pack_service.py:712`

**Root cause:** Line 712 hardcodes `granularity_level="macro"`. The composite workflow passes `granularity_level` in the request, but the circuit pack service ignores it and always writes "macro".

**Fix:** Pass the correct granularity from the run context.

- [ ] **Step 1:** Find where `run_circuit_pack_extraction` receives the granularity level

```bash
grep -n "granularity_level\|def run_circuit_pack_extraction" backend/app/services/llm_circuit_pack_service.py | head -20
```

- [ ] **Step 2:** The `CompositeWorkflowRunRequest` already has `granularity_level`. Find where the composite workflow calls the circuit pack service and pass it through.

```bash
grep -n "run_circuit_pack_extraction\|circuit_with_function" backend/app/services/llm_composite_workflow_service.py | head -10
```

- [ ] **Step 3:** Read the call chain at the composite workflow level and confirm the granularity field exists in the request data dict passed to `execute_circuit_extraction_background`.

- [ ] **Step 4:** In `llm_circuit_pack_service.py`, near the circuit creation loop, change:

```python
# BEFORE (line ~712):
granularity_level="macro",

# AFTER:
granularity_level=request_granularity or "macro",
```

Where `request_granularity` is extracted from the run's scope_json or passed as parameter. Check line `run_circuit_pack_extraction` signature for the `scope` parameter — it should already have `granularity_level` from `CircuitExtractionScope`.

- [ ] **Step 5:** Restart 8003 and run test:

```bash
python -c "
import urllib.request,json
resp=json.loads(urllib.request.urlopen('http://127.0.0.1:8003/api/candidates/brain-regions?granularity_level=molecular_attr&limit=10',timeout=30).read().decode())
cids=[i['id'] for i in resp['items']]
body=json.dumps({'workflow_type':'circuit_with_function_steps','provider':'deepseek','dry_run':False,'create_mirror_records':True,'granularity_level':'molecular_attr','candidate_ids':cids}).encode()
req=urllib.request.Request('http://127.0.0.1:8003/api/llm-extraction/composite-workflows/start',data=body,headers={'Content-Type':'application/json'})
r=json.loads(urllib.request.urlopen(req,timeout=60).read().decode())
print(f'Test run: {r[\"workflow_run_id\"]}')
"
```

- [ ] **Step 6:** Monitor test run for ~2 min, check circuits created:

```bash
curl -s http://127.0.0.1:8003/api/mirror-kg/circuits?granularity_level=molecular_attr | python -c "import sys,json;d=json.load(sys.stdin);print(f'Circuits: {d[\"total\"]}')"
```

Expected: circuits count should increase beyond 1831.

---

### Task 2: Handle duplicate circuit names gracefully

**Files:**
- Modify: `backend/app/services/mirror_kg_service.py` — the `create_mirror_circuit` function

**Root cause:** The `create_mirror_circuit` function (line 678) doesn't handle `IntegrityError` for duplicate names. It tries to insert, and if the name already exists, PostgreSQL throws `UniqueViolation` which crashes the savepoint.

**Fix:** Add try/except for `IntegrityError` in `create_mirror_circuit`, falling back to an UPDATE with higher confidence.

- [ ] **Step 1:** Read the current `create_mirror_circuit` function:

```bash
sed -n '678,780p' backend/app/services/mirror_kg_service.py
```

- [ ] **Step 2:** Find the `session.add()` and `session.flush()` calls. Wrap them in try/except for `IntegrityError`:

```python
from sqlalchemy.exc import IntegrityError

# After session.add(circuit) and await session.flush():
try:
    await session.flush()
except IntegrityError:
    await session.rollback()
    # Duplicate name — fetch existing and update if higher confidence
    existing = await session.execute(
        select(MirrorRegionCircuit).where(
            MirrorRegionCircuit.circuit_name == data["circuit_name"]
        )
    )
    existing = existing.scalar_one_or_none()
    if existing and payload.confidence > (existing.confidence or 0):
        existing.confidence = payload.confidence
        existing.description = payload.description or existing.description
        existing.function_association = payload.function_association or existing.function_association
        session.add(existing)
        await session.flush()
    return existing
```

- [ ] **Step 3:** Verify fix with test:

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/ -q -k "circuit" 2>&1 | tail -5
```

- [ ] **Step 4:** Restart 8003, run full circuit extraction test again (same as Task 1 Step 5).

---

### Task 3: Run full molecular circuit extraction

- [ ] **Step 1:** Cancel any stale runs on 8003
- [ ] **Step 2:** Start full circuit extraction with all 574 candidates:

```bash
python -c "
import urllib.request,json
resp=json.loads(urllib.request.urlopen('http://127.0.0.1:8003/api/candidates/brain-regions?granularity_level=molecular_attr&limit=600',timeout=30).read().decode())
cids=[i['id'] for i in resp['items']]
body=json.dumps({'workflow_type':'circuit_with_function_steps','provider':'deepseek','dry_run':False,'create_mirror_records':True,'create_triples':True,'create_evidence':True,'granularity_level':'molecular_attr','candidate_ids':cids}).encode()
req=urllib.request.Request('http://127.0.0.1:8003/api/llm-extraction/composite-workflows/start',data=body,headers={'Content-Type':'application/json'})
r=json.loads(urllib.request.urlopen(req,timeout=60).read().decode())
print(f'Full circuit run: {r[\"workflow_run_id\"]}')
"
```

- [ ] **Step 3:** Monitor for 5 minutes to confirm it doesn't fail immediately
- [ ] **Step 4:** Commit all changes

```bash
git add backend/app/services/llm_circuit_pack_service.py backend/app/services/mirror_kg_service.py
git commit -m "fix: circuit extraction granularity hardcode + duplicate name handling"
```
