# Circuit Extraction Refactor — Implementation Plan

> **For agentic workers:** Use subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace old `circuit_with_function_steps` composite workflow with single-step pack-based circuit extraction from brain region pool, writing to mirror_region_circuits + mirror_circuit_steps + mirror_circuit_functions.

**Architecture:** New backend service `llm_circuit_pack_service.py` handles shuffle→pack→prompt→LLM→parse→write. New models for run tracking. Reuse existing `_resolve_model_status` for mirror_status. Frontend reuses `PoolExtractionModal` pattern with circuit-specific configuration.

**Tech Stack:** FastAPI async, DeepSeek via httpx.AsyncClient, React 18 + TypeScript frontend.

## Global Constraints

- mirror_status uses existing `_MODEL_TIER` mapping (llm_suggested / llm_v4_pro / llm_reasoner / llm_kimi)
- review_status = "pending", promotion_status unchanged
- Never write to final_* / kg_*
- Pack size default 10, shuffle before packing
- Cancellation checked between packs

---

### Task 1: Backend — ORM model for circuit extraction runs

**Files:**
- Create: `backend/app/models/llm_circuit_extraction.py`
- Create: `backend/migrations/042_circuit_extraction_runs.sql`

**Interfaces:**
- Produces: `CircuitExtractionRun` ORM class with fields: id, provider, model_name, candidate_count, pack_count, circuit_count, step_count, function_count, status, request_json, result_summary_json, errors_json, warnings_json, created_at, started_at, completed_at, updated_at

- [ ] **Step 1: Create migration SQL**

```sql
-- 042_circuit_extraction_runs.sql
CREATE TABLE IF NOT EXISTS circuit_extraction_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider VARCHAR(64) NOT NULL,
    model_name VARCHAR(128),
    candidate_count INT NOT NULL DEFAULT 0,
    pack_count INT NOT NULL DEFAULT 0,
    circuit_count INT NOT NULL DEFAULT 0,
    step_count INT NOT NULL DEFAULT 0,
    function_count INT NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    request_json JSONB,
    result_summary_json JSONB,
    errors_json JSONB DEFAULT '[]',
    warnings_json JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- [ ] **Step 2: Create ORM model**

```python
# backend/app/models/llm_circuit_extraction.py
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class CircuitExtractionRun(Base):
    __tablename__ = "circuit_extraction_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    pack_count: Mapped[int] = mapped_column(Integer, default=0)
    circuit_count: Mapped[int] = mapped_column(Integer, default=0)
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    function_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    request_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result_summary_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    errors_json: Mapped[list] = mapped_column(JSONB, default=list)
    warnings_json: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 3: Run migration and verify import**

```bash
PGPASSWORD=postgres psql -h 127.0.0.1 -U postgres -d neurographiq_kg_v3_mvp1_e2e -f backend/migrations/042_circuit_extraction_runs.sql
cd backend && .venv/Scripts/python.exe -c "from app.models.llm_circuit_extraction import CircuitExtractionRun; print('OK')"
```

---

### Task 2: Backend — Schemas

**Files:**
- Create: `backend/app/schemas/llm_circuit_extraction.py`

**Interfaces:**
- Produces: `CircuitExtractionRequest`, `CircuitExtractionStartResponse`, `CircuitExtractionRunRead`, `CircuitExtractionRunDetail`
- Consumes: `CircuitExtractionRun` (from Task 1)

- [ ] **Step 1: Create Pydantic schemas**

```python
# backend/app/schemas/llm_circuit_extraction.py
from __future__ import annotations
import uuid
from datetime import datetime
from pydantic import BaseModel, Field

class CircuitExtractionRequest(BaseModel):
    provider: str = "deepseek"
    model_name: str | None = None
    candidate_ids: list[uuid.UUID]
    pool_id: uuid.UUID | None = None
    candidates_per_pack: int = Field(default=10, ge=2, le=50)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=16384, ge=256, le=65536)
    dry_run: bool = False

class CircuitExtractionStartResponse(BaseModel):
    run_id: uuid.UUID
    status: str = "pending"
    provider: str
    model_name: str | None
    candidate_count: int
    dry_run: bool
    estimated_packs: int = 0

class CircuitExtractionRunRead(BaseModel):
    id: uuid.UUID
    provider: str
    model_name: str | None
    candidate_count: int
    pack_count: int
    circuit_count: int
    step_count: int
    function_count: int
    status: str
    request_json: dict | None
    result_summary_json: dict | None
    errors_json: list = Field(default_factory=list)
    warnings_json: list = Field(default_factory=list)
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime
    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Verify module imports**

```bash
cd backend && .venv/Scripts/python.exe -c "from app.schemas.llm_circuit_extraction import CircuitExtractionRequest; print('OK')"
```

---

### Task 3: Backend — Circuit Pack Service (core logic)

**Files:**
- Create: `backend/app/services/llm_circuit_pack_service.py`

**Interfaces:**
- Produces: `run_circuit_pack_extraction(session, request) -> CircuitExtractionStartResponse`, `execute_circuit_extraction_background(run_id, payload)`, `get_circuit_extraction_run(session, run_id) -> CircuitExtractionRunDetail`, `cancel_circuit_extraction_run(session, run_id)`, `_check_cancelled(session, run_id) -> bool`
- Consumes: `CircuitExtractionRun` (Task 1), `CircuitExtractionRequest` (Task 2), `CandidateBrainRegion`, `MirrorRegionCircuit`, `MirrorCircuitStep`, `MirrorCircuitFunction`

- [ ] **Step 1: Create service file with core functions**

```python
# backend/app/services/llm_circuit_pack_service.py
"""Circuit extraction via brain region pack → DeepSeek → parse → write."""
from __future__ import annotations
import asyncio, json, logging, random, uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.llm_circuit_extraction import CircuitExtractionRun
from app.models.candidate import CandidateBrainRegion
from app.models.mirror_kg import MirrorRegionCircuit
from app.models.mirror_macro_clinical import MirrorCircuitStep, MirrorCircuitFunction
from app.schemas.llm_circuit_extraction import (
    CircuitExtractionRequest, CircuitExtractionStartResponse, CircuitExtractionRunRead,
)
from app.services.llm_providers import get_llm_provider, UnknownProviderError
from app.services.llm_field_completion_service import _resolve_model_status
from app.utils.json_safety import to_jsonable

logger = logging.getLogger(__name__)

CIRCUIT_PROMPT_SYSTEM = """You are a neuroscientist extracting brain circuits from region sets.
For the given brain regions, identify circuits they participate in. Output JSON with circuits, steps, and functions."""

CIRCUIT_PROMPT_TEMPLATE = """Given these {n} brain regions, identify all circuits they participate in:

{region_list}

Output JSON with:
- circuits[]: circuit_name, circuit_type, function_association, description, confidence, member_region_ids[]
- Each circuit has steps[]: step_order, step_name, step_type, role, description, confidence, region_id
- Each step has functions[]: function_term_en, function_term_cn, function_domain, function_role, effect_type, description, confidence

Return ONLY valid JSON."""


async def _check_cancelled(session: AsyncSession, run_id: uuid.UUID) -> bool:
    stmt = select(CircuitExtractionRun.status).where(CircuitExtractionRun.id == run_id)
    result = await session.execute(stmt)
    val = result.scalar_one_or_none()
    return val == "cancelled"


async def run_circuit_pack_extraction(
    session: AsyncSession, request: CircuitExtractionRequest,
) -> CircuitExtractionStartResponse:
    """Start a circuit extraction run (async path)."""
    candidate_ids = list(dict.fromkeys(request.candidate_ids))
    run = CircuitExtractionRun(
        provider=request.provider,
        model_name=request.model_name,
        candidate_count=len(candidate_ids),
        status="pending",
        request_json=to_jsonable(request.model_dump(mode="json")),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    estimated = max(1, len(candidate_ids) // request.candidates_per_pack)
    return CircuitExtractionStartResponse(
        run_id=run.id, status="pending", provider=request.provider,
        model_name=request.model_name, candidate_count=len(candidate_ids),
        dry_run=False, estimated_packs=estimated,
    )


async def execute_circuit_extraction_background(run_id: uuid.UUID, request_payload: dict) -> None:
    from app.database import AsyncSessionLocal
    if AsyncSessionLocal is None: return
    request = CircuitExtractionRequest.model_validate(request_payload)

    async with AsyncSessionLocal() as session:
        run = await session.get(CircuitExtractionRun, run_id)
        if run is None: return
        if await _check_cancelled(session, run_id): return

        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        await session.flush()

        # Load candidates
        q = select(CandidateBrainRegion).where(CandidateBrainRegion.id.in_(request.candidate_ids))
        result = await session.execute(q)
        candidates = {r.id: r for r in result.scalars().all()}

        # Shuffle and pack
        ids = list(candidates.keys())
        random.shuffle(ids)
        packs = [ids[i:i + request.candidates_per_pack] for i in range(0, len(ids), request.candidates_per_pack)]
        run.pack_count = len(packs)
        await session.flush()

        provider_key = request.provider.lower()
        resolved_model = request.model_name or "deepseek-chat"

        total_circuits = total_steps = total_functions = 0
        errors: list[str] = []
        warnings: list[str] = []

        for pi, pack_ids in enumerate(packs):
            if await _check_cancelled(session, run_id):
                run.status = "cancelled"
                run.completed_at = datetime.now(timezone.utc)
                run.warnings_json = to_jsonable(warnings + ["Cancelled by user"])
                await session.commit()
                return

            region_list = "\n".join(
                f"- {candidates[rid].name_cn or candidates[rid].name_en or str(rid)} "
                f"(id={rid}, atlas={candidates[rid].source_atlas})"
                for rid in pack_ids if rid in candidates
            )
            user_prompt = CIRCUIT_PROMPT_TEMPLATE.format(n=len(pack_ids), region_list=region_list)

            try:
                provider = get_llm_provider(provider_key)
                response = await provider.complete_json(
                    model=resolved_model, system_prompt=CIRCUIT_PROMPT_SYSTEM,
                    user_prompt=user_prompt, temperature=request.temperature,
                    max_tokens=request.max_tokens, timeout_seconds=120,
                )
                parsed = response.parsed_json or {}
            except Exception as exc:
                errors.append(f"pack {pi}: {exc}")
                continue

            circuits_data = parsed.get("circuits", [])
            for cdata in circuits_data:
                circuit = MirrorRegionCircuit(
                    circuit_name=cdata.get("circuit_name", ""),
                    circuit_type=cdata.get("circuit_type", "functional"),
                    function_association=cdata.get("function_association"),
                    description=cdata.get("description"),
                    confidence=float(cdata.get("confidence", 0.7)),
                    granularity_level=candidates.get(pack_ids[0], None) and candidates[pack_ids[0]].granularity_level or "macro",
                    source_atlas=candidates.get(pack_ids[0], None) and candidates[pack_ids[0]].source_atlas or "",
                    mirror_status=_resolve_model_status(resolved_model)[0],
                    review_status="pending",
                )
                session.add(circuit)
                await session.flush()
                total_circuits += 1

                for sdata in cdata.get("steps", []):
                    step = MirrorCircuitStep(
                        circuit_id=circuit.id,
                        step_order=sdata.get("step_order", 1),
                        step_name=sdata.get("step_name", ""),
                        step_type=sdata.get("step_type", ""),
                        role=sdata.get("role"),
                        description=sdata.get("description"),
                        confidence=float(sdata.get("confidence", 0.7)),
                        region_candidate_id=sdata.get("region_id"),
                        granularity_level=circuit.granularity_level,
                        source_atlas=circuit.source_atlas,
                        mirror_status=_resolve_model_status(resolved_model)[0],
                        review_status="pending",
                    )
                    session.add(step)
                    await session.flush()
                    total_steps += 1

                    for fdata in sdata.get("functions", []):
                        fn = MirrorCircuitFunction(
                            circuit_id=circuit.id,
                            function_term_en=fdata.get("function_term_en", ""),
                            function_term_cn=fdata.get("function_term_cn"),
                            function_domain=fdata.get("function_domain"),
                            function_role=fdata.get("function_role"),
                            effect_type=fdata.get("effect_type"),
                            description=fdata.get("description"),
                            confidence=float(fdata.get("confidence", 0.7)),
                            granularity_level=circuit.granularity_level,
                            source_atlas=circuit.source_atlas,
                            mirror_status=_resolve_model_status(resolved_model)[0],
                            review_status="pending",
                        )
                        session.add(fn)
                        total_functions += 1

            logger.info("[circuit-extraction] pack %s/%s: circuits=%s steps=%s functions=%s",
                         pi + 1, len(packs), total_circuits, total_steps, total_functions)

        run.circuit_count = total_circuits
        run.step_count = total_steps
        run.function_count = total_functions
        run.status = "partially_succeeded" if errors else "succeeded"
        run.completed_at = datetime.now(timezone.utc)
        run.result_summary_json = to_jsonable({
            "circuit_created": total_circuits, "step_created": total_steps,
            "function_created": total_functions, "pack_count": len(packs),
            "model_call_count": len(packs),
        })
        run.errors_json = to_jsonable(errors)
        run.warnings_json = to_jsonable(warnings)
        await session.commit()


async def get_circuit_extraction_run(session: AsyncSession, run_id: uuid.UUID) -> CircuitExtractionRunRead | None:
    run = await session.get(CircuitExtractionRun, run_id)
    if run is None: return None
    await session.refresh(run)
    return CircuitExtractionRunRead.model_validate(run)


async def cancel_circuit_extraction_run(session: AsyncSession, run_id: uuid.UUID) -> CircuitExtractionRun | None:
    run = await session.get(CircuitExtractionRun, run_id)
    if run is None: return None
    if run.status not in ("pending", "running"): return run
    run.status = "cancelled"
    run.completed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(run)
    return run
```

- [ ] **Step 2: Verify imports**

```bash
cd backend && .venv/Scripts/python.exe -c "from app.services.llm_circuit_pack_service import run_circuit_pack_extraction; print('OK')"
```

---

### Task 4: Backend — Router + main.py wiring

**Files:**
- Create: `backend/app/routers/llm_circuit_extraction.py`
- Modify: `backend/app/main.py` (add import + include_router)

- [ ] **Step 1: Create router**

```python
# backend/app/routers/llm_circuit_extraction.py
from __future__ import annotations
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.llm_circuit_extraction import (
    CircuitExtractionRequest, CircuitExtractionStartResponse, CircuitExtractionRunRead,
)
from app.services import llm_circuit_pack_service as svc

router = APIRouter()

@router.post("/run")
async def run_extraction(
    body: CircuitExtractionRequest, background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    if not body.dry_run:
        start = await svc.run_circuit_pack_extraction(session, body)
        background_tasks.add_task(svc.execute_circuit_extraction_background, start.run_id, body.model_dump(mode="json"))
        return start
    return {"dry_run": True, "estimated_packs": max(1, len(body.candidate_ids) // body.candidates_per_pack)}

@router.get("/runs", response_model=dict)
async def list_runs(
    status: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func, select as sa_select
    from app.models.llm_circuit_extraction import CircuitExtractionRun
    base = sa_select(CircuitExtractionRun)
    if status: base = base.where(CircuitExtractionRun.status == status)
    count_q = sa_select(func.count()).select_from(base.subquery())
    total = (await session.execute(count_q)).scalar_one()
    q = base.order_by(CircuitExtractionRun.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(q)).scalars().all()
    return {"items": [CircuitExtractionRunRead.model_validate(r) for r in rows], "total": total}

@router.get("/runs/{run_id}", response_model=CircuitExtractionRunRead)
async def get_run(run_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    detail = await svc.get_circuit_extraction_run(session, run_id)
    if detail is None: raise HTTPException(404, detail={"code": "NOT_FOUND"})
    return detail

@router.post("/runs/{run_id}/cancel", response_model=CircuitExtractionRunRead)
async def cancel_run(run_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    run = await svc.cancel_circuit_extraction_run(session, run_id)
    if run is None: raise HTTPException(404, detail={"code": "NOT_FOUND"})
    return CircuitExtractionRunRead.model_validate(run)
```

- [ ] **Step 2: Wire into main.py**

Add import: `from app.routers import llm_circuit_extraction` in the import block.
Add router: `app.include_router(llm_circuit_extraction.router, prefix="/api/llm-extraction/circuit-extraction", tags=["Circuit Extraction"])`

- [ ] **Step 3: Restart backend and test**

```bash
taskkill //F //IM python.exe 2>/dev/null; sleep 2; cd backend && .venv/Scripts/python.exe run_server.py &
sleep 4 && curl -s http://127.0.0.1:8002/api/llm-extraction/circuit-extraction/runs
```

---

### Task 5: Frontend — API types and endpoints

**Files:**
- Modify: `frontend/src/api/endpoints.ts`

- [ ] **Step 1: Add types and API functions**

After the existing field completion API section, add:

```typescript
// ── Circuit Pack Extraction ─────────────────────────────────────────────────

export interface CircuitExtractionRequest {
  provider: string
  model_name?: string | null
  candidate_ids: string[]
  pool_id?: string | null
  candidates_per_pack?: number
  temperature?: number
  max_tokens?: number
  dry_run?: boolean
}

export interface CircuitExtractionStartResponse {
  run_id: string
  status: string
  provider: string
  model_name: string | null
  candidate_count: number
  dry_run: boolean
  estimated_packs: number
}

export interface CircuitExtractionRunRead {
  id: string
  provider: string
  model_name: string | null
  candidate_count: number
  pack_count: number
  circuit_count: number
  step_count: number
  function_count: number
  status: string
  request_json: Record<string, unknown> | null
  result_summary_json: Record<string, unknown> | null
  errors_json: unknown[]
  warnings_json: unknown[]
  created_at: string
  started_at: string | null
  completed_at: string | null
  updated_at: string
}

export const runCircuitExtraction = (body: CircuitExtractionRequest) =>
  postJson<CircuitExtractionStartResponse>('/api/llm-extraction/circuit-extraction/run', body)

export const getCircuitExtractionRun = (runId: string) =>
  getJson<CircuitExtractionRunRead>(`/api/llm-extraction/circuit-extraction/runs/${runId}`)

export const cancelCircuitExtractionRun = (runId: string) =>
  postJson<CircuitExtractionRunRead>(`/api/llm-extraction/circuit-extraction/runs/${runId}/cancel`)
```

- [ ] **Step 2: Verify compilation**

```bash
cd frontend && npx tsc -b 2>&1 | grep -v "DryRunDetailPanel"
```

---

### Task 6: Frontend — Wire quick card + PoolExtractionModal

**Files:**
- Modify: `frontend/src/pages/LlmExtractionPage.tsx` (update circuit card onClick)
- Modify: `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx` (add circuit extraction mode)

- [ ] **Step 1: Update quick card onClick in LlmExtractionPage.tsx**

Find the `onExtractCircuit` callback and change it to call the new circuit extraction:

```typescript
onExtractCircuit={() => {
  openCircuitExtractModal()
}}
```

Add a new function `openCircuitExtractModal` that opens PoolExtractionModal in circuit mode:

```typescript
const openCircuitExtractModal = useCallback(async () => {
  const ids = [...new Set(selectedCandidateIdsRef.current.filter(Boolean))]
  if (ids.length < 2) {
    setCandidateMinError('请至少选择 2 个脑区')
    return
  }
  // Set pool and open extraction
  try {
    await setupExtractionPoolFromCurrentSelection()
    // Open the modal with circuit mode configuration
    setCircuitExtractionOpen(true)
  } catch (err) {
    console.error('setup pool failed', err)
  }
}, [])
```

Add state: `const [circuitExtractionOpen, setCircuitExtractionOpen] = useState(false)`

- [ ] **Step 2: Render circuit extraction panel**

When `circuitExtractionOpen` is true, render a new component `CircuitExtractionPanel`:

```tsx
{circuitExtractionOpen && pool && (
  <CircuitExtractionPanel
    pool={pool}
    provider={provider}
    modelName={modelName || 'deepseek-chat'}
    onClose={() => setCircuitExtractionOpen(false)}
    onCompleted={() => { setCircuitExtractionOpen(false); refresh() }}
  />
)}
```

- [ ] **Step 3: Create CircuitExtractionPanel component**

```bash
Create: frontend/src/pages/llm-extraction/components/CircuitExtractionPanel.tsx
```

Minimal component with: run button, progress polling, results summary. Follows the pattern of FieldCompletionStatsCards but for circuit results.

- [ ] **Step 4: Verify compilation**

```bash
cd frontend && npx tsc -b 2>&1 | grep -v "DryRunDetailPanel"
```

---

### Task 7: Backend — Remove old composite workflow circuit entry

**Files:**
- Modify: `backend/app/services/llm_composite_workflow_service.py`
- Modify: `frontend/src/pages/llm-extraction/llmDataFirstTypes.ts`

- [ ] **Step 1: Remove circuit_with_function_steps from WORKFLOW_STEP_DEFS**

In `llm_composite_workflow_service.py`, remove lines 106-128 (the `CompositeWorkflowType.circuit_with_function_steps` entry and its steps).

- [ ] **Step 2: Remove circuit composite from frontend task types**

In `llmDataFirstTypes.ts`, remove `composite_circuit_with_function_and_steps` from COMPOSITE_TASKS and related entries.

- [ ] **Step 3: Verify backend tests still pass**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/ -q -k "composite" 2>&1 | tail -5
```

- [ ] **Step 4: Verify frontend compiles**

```bash
cd frontend && npx tsc -b 2>&1 | grep -v "DryRunDetailPanel"
```
