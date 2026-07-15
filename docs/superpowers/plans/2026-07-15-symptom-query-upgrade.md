# Symptom Query Page Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add AI conversational triage + step-level brain-region D3 force graph to SymptomQueryPage, per spec `docs/superpowers/specs/2026-07-15-symptom-query-upgrade.md`.

**Architecture:** Four-phase flow (chat→confirm→analyze→graph). Backend gets a new `/conversation` endpoint and a rewritten `/graph` endpoint using real step data. Frontend gets a chat panel with confirmation card, auto-chained analysis, and a shared D3 ForceGraph component with matching legend.

**Tech Stack:** FastAPI (Python, SQLAlchemy async), React 18 + TypeScript + D3 v7 (force simulation), DeepSeek LLM provider.

## Global Constraints

- All LLM calls use DeepSeek via `app.services.llm_providers.factory`
- Frontend uses D3 force simulation (not ReactFlow) for the graph
- Granularity is passed through all endpoints (`granularity_level` query/body param)
- No writes to `final_*` — all queries are read-only on mirror tables
- Follow existing code patterns in `symptom_query.py` (raw SQL via `text()`, Pydantic models inline)
- Frontend follows existing patterns: `useState`/`useCallback`/`useMemo`, no external state library

---

### Task 1: Backend — Conversation Endpoint

**Files:**
- Modify: `backend/app/routers/symptom_query.py` (add ~70 lines)
- Test: `backend/tests/test_symptom_query.py` (new file)

**Interfaces:**
- Produces: `POST /api/symptom-query/conversation` — accepts `{messages: [{role, content}], granularity_level}` → returns `{stage, content, summary}`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_symptom_query.py`:

```python
"""Tests for symptom-query endpoints."""
import asyncio, json, uuid
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

def test_conversation_asking_stage(monkeypatch):
    """Mock LLM returns asking stage → response has stage='asking' with content."""
    from app.main import app
    from app.services.llm_providers.base import LlmProviderResponse, LlmProviderUsage

    mock_provider = AsyncMock()
    mock_provider.complete_json = AsyncMock(return_value=LlmProviderResponse(
        provider="deepseek", model="deepseek-chat",
        raw_text='{"stage":"asking","content":"Do you have tinnitus?","summary":null}',
        parsed_json={"stage": "asking", "content": "Do you have tinnitus?", "summary": None},
        usage=LlmProviderUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        finish_reason="stop", request_payload_redacted={}, response_payload={}, latency_ms=10,
    ))
    monkeypatch.setattr(
        "app.routers.symptom_query.get_llm_provider", lambda name: mock_provider,
    )
    monkeypatch.setattr(
        "app.routers.symptom_query.get_deepseek_runtime_config",
        lambda: type("C", (), {"api_key": "sk-test", "default_model": "deepseek-chat"})(),
    )

    client = TestClient(app)
    resp = client.post("/api/symptom-query/conversation", json={
        "messages": [{"role": "user", "content": "I feel dizzy"}],
        "granularity_level": "molecular_attr",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["stage"] == "asking"
    assert data["content"] == "Do you have tinnitus?"
    assert data["summary"] is None


def test_conversation_summarizing_stage(monkeypatch):
    """Mock LLM returns summarizing stage → response has summary."""
    from app.main import app
    from app.services.llm_providers.base import LlmProviderResponse, LlmProviderUsage

    mock_provider = AsyncMock()
    mock_provider.complete_json = AsyncMock(return_value=LlmProviderResponse(
        provider="deepseek", model="deepseek-chat",
        raw_text='{"stage":"summarizing","content":null,"summary":"Vestibular symptoms"}',
        parsed_json={"stage": "summarizing", "content": None, "summary": "Vestibular symptoms"},
        usage=LlmProviderUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        finish_reason="stop", request_payload_redacted={}, response_payload={}, latency_ms=10,
    ))
    monkeypatch.setattr(
        "app.routers.symptom_query.get_llm_provider", lambda name: mock_provider,
    )
    monkeypatch.setattr(
        "app.routers.symptom_query.get_deepseek_runtime_config",
        lambda: type("C", (), {"api_key": "sk-test", "default_model": "deepseek-chat"})(),
    )

    client = TestClient(app)
    resp = client.post("/api/symptom-query/conversation", json={
        "messages": [{"role": "user", "content": "Dizzy for weeks, worse standing"}],
        "granularity_level": "macro",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["stage"] == "summarizing"
    assert data["summary"] == "Vestibular symptoms"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests/test_symptom_query.py -q`
Expected: FAIL — 404 Not Found (no `/conversation` endpoint yet)

- [ ] **Step 3: Add schemas and endpoint to symptom_query.py**

Add these schemas after the existing `ExpandResponse` class (around line 250):

```python
class ConversationRequest(BaseModel):
    messages: list[dict]
    granularity_level: str = "macro"


class ConversationResponse(BaseModel):
    stage: str
    content: str | None = None
    summary: str | None = None


CONVERSATION_PROMPT = """You are a clinical neuroscientist conducting a brief symptom triage interview.
Your goal is to gather enough information to produce a concise clinical summary
that can be converted into standardized brain function terms.

Rules:
- Ask at most ONE question per response. Be specific and focused.
- After 2-4 exchanges, if you have sufficient information, stop asking and
  produce a summary instead.
- When summarizing, synthesize the key symptom picture in 2-4 sentences.
  Include: suspected brain region(s), symptom characteristics, possible
  functional domains involved.
- Your response MUST be valid JSON with exactly these keys:
  {"stage": "asking", "content": "your follow-up question", "summary": null}
  OR
  {"stage": "summarizing", "content": null, "summary": "your clinical summary text"}

Conversation history:
{history}"""
```

Add the endpoint after the expand endpoint (after line 289):

```python
@router.post("/conversation", response_model=ConversationResponse)
async def symptom_conversation(body: ConversationRequest):
    """Multi-turn symptom triage — LLM decides whether to ask more or summarize."""
    if not body.messages:
        return ConversationResponse(
            stage="asking",
            content="Please describe your symptoms. What do you feel, and where?",
            summary=None,
        )

    # Build conversation history string
    lines = []
    for m in body.messages[-10:]:  # last 10 messages max
        role = "Patient" if m.get("role") == "user" else "Doctor"
        lines.append(f"{role}: {m.get('content', '')}")
    history = "\n".join(lines)

    try:
        cfg = get_deepseek_runtime_config()
        provider = get_llm_provider("deepseek")
        resp = await provider.complete_json(
            model=cfg.default_model,
            system_prompt="You are a clinical neuroscientist. Output ONLY valid JSON.",
            user_prompt=CONVERSATION_PROMPT.format(history=history),
            temperature=0.3,
        )
        import ast as _ast, json as _json
        parsed = resp.parsed_json
        if isinstance(parsed, dict) and "_array" in parsed:
            parsed = parsed["_array"]
        if isinstance(parsed, str):
            for parser in (_json.loads, _ast.literal_eval):
                try:
                    parsed = parser(parsed)
                    break
                except Exception:
                    continue
        if isinstance(parsed, dict) and "stage" in parsed:
            return ConversationResponse(
                stage=str(parsed.get("stage", "asking")),
                content=parsed.get("content"),
                summary=parsed.get("summary"),
            )
        # Fallback: treat raw text as asking response
        raw = resp.raw_text or ""
        return ConversationResponse(stage="asking", content=raw[:200], summary=None)
    except Exception:
        logger.exception("Conversation failed")
        return ConversationResponse(
            stage="summarizing",
            content=None,
            summary=" ".join(m.get("content", "") for m in body.messages if m.get("role") == "user"),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests/test_symptom_query.py -q`
Expected: 2 passed

- [ ] **Step 5: Verify import**

Run: `cd backend && .\.venv\Scripts\python.exe -c "import app.main; print('OK')"`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/symptom_query.py backend/tests/test_symptom_query.py
git commit -m "feat: add /api/symptom-query/conversation endpoint for multi-turn symptom triage"
```

---

### Task 2: Backend — Rewrite Graph Endpoint with Step-Level Data

**Files:**
- Modify: `backend/app/routers/symptom_query.py` (replace `/graph` endpoint, lines 304–364)
- Test: `backend/tests/test_symptom_query.py` (append test)

**Interfaces:**
- Consumes: Graph endpoint reads `mirror_circuit_steps.region_candidate_id` joined to `candidate_brain_regions`
- Produces: Step-level nodes (`{id, type, label, circuit_id, circuit_name, step_order, role}`) + typed edges (`step_flow`, `belongs_to`, `co_occurs`)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_symptom_query.py`:

```python
def test_graph_returns_step_level_nodes(monkeypatch):
    """Graph endpoint uses real step data, not regex on circuit_name."""
    from app.main import app
    from app.database import AsyncSessionLocal
    import uuid as _uuid

    # Use the test DB directly (integration test)
    client = TestClient(app)

    # Create test data: one circuit with 3 steps, each referencing a candidate region
    cid = str(_uuid.uuid4())
    rid1 = str(_uuid.uuid4())
    rid2 = str(_uuid.uuid4())

    # Insert test circuit
    import psycopg
    conn = psycopg.connect(
        "host=127.0.0.1 port=5432 dbname=neurographiq_kg_v3_mvp1_e2e user=postgres password=postgres"
    )
    conn.autocommit = True
    try:
        conn.execute(
            "INSERT INTO candidate_brain_regions (id, en_name, source_atlas, candidate_status, granularity_level, batch_id, resource_id, generation_run_id, parse_run_id, raw_payload, row_index) "
            "VALUES (%s, %s, 'Allen_HBA_2012', 'candidate_created', 'molecular_attr', %s, %s, %s, %s, '{}', 0)",
            (_uuid.UUID(rid1), "Test Region A", _uuid.uuid4(), _uuid.uuid4(), _uuid.uuid4(), _uuid.uuid4()),
        )
        conn.execute(
            "INSERT INTO candidate_brain_regions (id, en_name, source_atlas, candidate_status, granularity_level, batch_id, resource_id, generation_run_id, parse_run_id, raw_payload, row_index) "
            "VALUES (%s, %s, 'Allen_HBA_2012', 'candidate_created', 'molecular_attr', %s, %s, %s, %s, '{}', 0)",
            (_uuid.UUID(rid2), "Test Region B", _uuid.uuid4(), _uuid.uuid4(), _uuid.uuid4(), _uuid.uuid4()),
        )
        conn.execute(
            "INSERT INTO mirror_region_circuits (id, circuit_name, circuit_type, granularity_level, source_atlas, mirror_status, review_status, promotion_status, raw_payload_json, normalized_payload_json) "
            "VALUES (%s, 'test_sensory_pathway', 'sensory_circuit', 'molecular_attr', 'Allen_HBA_2012', 'llm_suggested', 'pending', 'not_promoted', '{}', '{}')",
            (_uuid.UUID(cid),),
        )
        conn.execute(
            "INSERT INTO mirror_circuit_steps (id, circuit_id, step_order, step_name, step_type, role, region_candidate_id, granularity_level, source_atlas, mirror_status, review_status, promotion_status, raw_payload_json, normalized_payload_json) "
            "VALUES (%s, %s, 1, 'step 1', 'unknown', 'source', %s, 'molecular_attr', 'Allen_HBA_2012', 'llm_suggested', 'pending', 'not_promoted', '{}', '{}')",
            (_uuid.uuid4(), _uuid.UUID(cid), _uuid.UUID(rid1)),
        )
        conn.execute(
            "INSERT INTO mirror_circuit_steps (id, circuit_id, step_order, step_name, step_type, role, region_candidate_id, granularity_level, source_atlas, mirror_status, review_status, promotion_status, raw_payload_json, normalized_payload_json) "
            "VALUES (%s, %s, 2, 'step 2', 'unknown', 'target', %s, 'molecular_attr', 'Allen_HBA_2012', 'llm_suggested', 'pending', 'not_promoted', '{}', '{}')",
            (_uuid.uuid4(), _uuid.UUID(cid), _uuid.UUID(rid2)),
        )

        resp = client.post("/api/symptom-query/graph", json={
            "circuit_ids": [cid],
            "granularity_level": "molecular_attr",
        })
        data = resp.json()
        nodes = data["nodes"]
        edges = data["edges"]

        # Should have 2 step brain_region nodes + 1 circuit node = 3 nodes
        assert len(nodes) == 3
        assert any(n["type"] == "circuit" and n["label"] == "test_sensory_pathway" for n in nodes)
        assert any(n["type"] == "brain_region" and n["label"] == "Test Region A" for n in nodes)

        # Should have step_flow edges between steps + belongs_to edges to circuit
        step_flows = [e for e in edges if e["type"] == "step_flow"]
        assert len(step_flows) >= 1  # step 1 → step 2
    finally:
        conn.close()
```

- [ ] **Step 2: Verify test fails with old graph endpoint**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests/test_symptom_query.py::test_graph_returns_step_level_nodes -q`
Expected: FAIL — old endpoint returns regex-parsed nodes, not step-level nodes with region labels

- [ ] **Step 3: Rewrite the `/graph` endpoint**

Replace the entire `/graph` endpoint (lines 292–364 in `symptom_query.py`):

```python
@router.post("/graph", response_model=GraphDataResponse)
async def get_circuit_graph(
    body: GraphDataRequest,
    session: AsyncSession = Depends(get_db),
):
    cids = [uuid.UUID(c) for c in body.circuit_ids if c]
    if not cids:
        return GraphDataResponse(nodes=[], edges=[])

    cid_list = ",".join(f"'{c}'" for c in body.circuit_ids if c)

    # Load circuits
    circ_result = await session.execute(
        select(MirrorRegionCircuit).where(MirrorRegionCircuit.id.in_(cids))
    )
    all_circs = {str(c.id): c for c in circ_result.scalars().all()}

    # Load steps with region labels
    steps_sql = text(f"""
        SELECT s.id, s.circuit_id, s.step_order, s.role, s.step_name,
               cbr.en_name AS region_name, cbr.id AS region_uid
        FROM mirror_circuit_steps s
        LEFT JOIN candidate_brain_regions cbr ON cbr.id = s.region_candidate_id
        WHERE s.circuit_id IN ({cid_list})
        ORDER BY s.circuit_id, s.step_order
    """)
    step_rows = (await session.execute(steps_sql)).fetchall()

    nodes: list[dict] = []
    edges: list[dict] = []
    region_node_ids: dict[str, str] = {}  # (circuit_id, region_uid) → node_id
    circuit_step_map: dict[str, list[dict]] = {}  # circuit_id → ordered step info

    for row in step_rows:
        sid = str(row[0])
        cid = str(row[1])
        order = row[2] or 0
        role = row[3] or "participant"
        step_name = row[4] or ""
        region_name = row[5] or step_name or "Unknown"
        region_uid = str(row[6]) if row[6] else None

        # Brain region node
        if region_uid:
            rkey = f"{cid}:{region_uid}"
        else:
            rkey = f"{cid}:step_{sid}"
        if rkey not in region_node_ids:
            region_node_ids[rkey] = f"step_{sid}"
            nodes.append({
                "id": f"step_{sid}",
                "type": "brain_region",
                "label": region_name,
                "circuit_id": cid,
                "circuit_name": all_circs.get(cid, type("C", (), {"circuit_name": cid})()).circuit_name,
                "step_order": order,
                "role": role,
            })

        if cid not in circuit_step_map:
            circuit_step_map[cid] = []
        circuit_step_map[cid].append({"id": f"step_{sid}", "order": order, "role": role, "rkey": rkey})

    # Circuit nodes
    for cid, circ in all_circs.items():
        nodes.append({
            "id": f"circuit_{cid}",
            "type": "circuit",
            "label": circ.circuit_name or cid[:12],
        })

    # Edges
    for cid, steps in circuit_step_map.items():
        sorted_steps = sorted(steps, key=lambda s: s["order"])
        for i in range(len(sorted_steps)):
            si = sorted_steps[i]
            # belongs_to: step → circuit
            edges.append({
                "id": f"bt_{si['id']}",
                "source": si["id"],
                "target": f"circuit_{cid}",
                "type": "belongs_to",
                "label": all_circs.get(cid, type("C", (), {"circuit_name": cid})()).circuit_name,
            })
            # step_flow: step_i → step_{i+1}
            if i + 1 < len(sorted_steps):
                edges.append({
                    "id": f"sf_{si['id']}_{sorted_steps[i+1]['id']}",
                    "source": si["id"],
                    "target": sorted_steps[i+1]["id"],
                    "type": "step_flow",
                    "label": all_circs.get(cid, type("C", (), {"circuit_name": cid})()).circuit_name,
                })

    # co_occurs: steps from DIFFERENT circuits sharing the same region_candidate_id
    rkey_to_nodes: dict[str, list[str]] = {}
    for sid, info in region_node_ids.items():
        rkey_to_nodes.setdefault(sid.split(":")[1] if ":" in sid else sid, []).append(info)
    for rkey, node_ids in rkey_to_nodes.items():
        if len(node_ids) >= 2:
            for i in range(len(node_ids)):
                for j in range(i + 1, len(node_ids)):
                    edges.append({
                        "id": f"co_{node_ids[i]}_{node_ids[j]}",
                        "source": node_ids[i],
                        "target": node_ids[j],
                        "type": "co_occurs",
                        "label": "Shared brain region",
                    })

    return GraphDataResponse(nodes=nodes, edges=edges)
```

- [ ] **Step 4: Run graph test**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests/test_symptom_query.py::test_graph_returns_step_level_nodes -q`
Expected: PASS

- [ ] **Step 5: Run all symptom tests**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests/test_symptom_query.py -q`
Expected: 3 passed

- [ ] **Step 6: Verify import**

Run: `cd backend && .\.venv\Scripts\python.exe -c "import app.main; print('OK')"`
Expected: OK

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/symptom_query.py backend/tests/test_symptom_query.py
git commit -m "feat: rewrite /api/symptom-query/graph with step-level brain region data"
```

---

### Task 3: Extract Shared ForceGraph Component

**Files:**
- Create: `frontend/src/components/ForceGraph.tsx`
- Modify: `frontend/src/pages/GraphExplorerPage.tsx` (remove duplicated ForceGraph + drawGraph)
- Modify: `frontend/src/pages/SymptomQueryPage.tsx` (import from shared component)

**Interfaces:**
- Produces: `ForceGraph({ nodes: GNode[], edges: GEdge[], focusNode, onNodeClick, edgeColors, edgeDashes, nodeColors, nodeRadii, legendItems? })` component
- Produces: `drawGraph(el, nodes, edges, W, H, focusNode, onNodeClick, edgeColors, edgeDashes, nodeColors, nodeRadii)` function

- [ ] **Step 1: Extract ForceGraph + drawGraph into shared component**

Create `frontend/src/components/ForceGraph.tsx`. Copy the `ForceGraph` function and `drawGraph` function from `GraphExplorerPage.tsx` (lines 189–305 of the copy in that file), parameterizing the color/dash maps so both pages can customize them:

```typescript
import React, { useEffect, useMemo, useRef } from 'react'
import * as d3 from 'd3'

export interface GNode {
  id: string; type: string; label: string
  name_en?: string; name_cn?: string
  [key: string]: any  // allow extra fields like circuit_id, step_order, role
}

export interface GEdge {
  id: string; source: string; target: string; type: string
  label?: string; confidence?: number
}

export interface LegendItem { color: string; dash: string; label: string }

interface ForceGraphProps {
  nodes: GNode[]
  edges: GEdge[]
  focusNode: string | null
  onNodeClick?: (id: string) => void
  edgeColors?: Record<string, string>
  edgeDashes?: Record<string, string>
  nodeColors?: Record<string, string>
  nodeRadii?: Record<string, number>
  legendItems?: LegendItem[]
}

const DEFAULT_EDGE_COLOR: Record<string, string> = {
  belongs_to: '#d1d5db', step_flow: '#10b981', co_occurs: '#8b5cf6',
}
const DEFAULT_EDGE_DASH: Record<string, string> = {
  belongs_to: '', step_flow: '2,2', co_occurs: '6,3',
}
const DEFAULT_NODE_COLOR: Record<string, string> = { region: '#3b82f6', circuit: '#f59e0b', brain_region: '#3b82f6' }
const DEFAULT_NODE_R: Record<string, number> = { region: 7, circuit: 6, brain_region: 7 }

export function ForceGraph({
  nodes: _nodes, edges: _edges, focusNode, onNodeClick,
  edgeColors = DEFAULT_EDGE_COLOR, edgeDashes = DEFAULT_EDGE_DASH,
  nodeColors = DEFAULT_NODE_COLOR, nodeRadii = DEFAULT_NODE_R,
  legendItems,
}: ForceGraphProps) {
  const ref = useRef<HTMLDivElement>(null)

  const { nodes, edges } = useMemo(() => {
    const nm = new Map<string, GNode>()
    for (const n of _nodes) nm.set(n.id, n)
    for (const e of _edges) {
      if (!nm.has(e.source)) nm.set(e.source, { id: e.source, type: 'region', label: e.source.slice(0, 12) })
      if (!nm.has(e.target)) nm.set(e.target, { id: e.target, type: 'region', label: e.target.slice(0, 12) })
    }
    const validEdges = _edges.filter(e => nm.has(e.source) && nm.has(e.target))
    return { nodes: [...nm.values()], edges: validEdges }
  }, [_nodes, _edges])

  useEffect(() => {
    const el = ref.current; if (!el || nodes.length === 0) return
    const W = el.clientWidth || 800; const H = el.clientHeight || 600
    d3.select(el).html('')
    setTimeout(() => {
      d3.select(el).html('')
      drawGraph(el, nodes, edges, W, H, focusNode, onNodeClick, edgeColors, edgeDashes, nodeColors, nodeRadii, legendItems)
    }, 10)
    return () => {}
  }, [nodes.length, edges.length, focusNode])

  return <div ref={ref} style={{ width: '100%', height: '100%' }} />
}

function drawGraph(
  el: HTMLDivElement, nodes: GNode[], edges: GEdge[],
  W: number, H: number, focusNode: string | null, onNodeClick: ((id: string) => void) | undefined,
  edgeColors: Record<string, string>, edgeDashes: Record<string, string>,
  nodeColors: Record<string, string>, nodeRadii: Record<string, number>,
  legendItems?: LegendItem[],
) {
  d3.select(el).html('')
  const svg = d3.select(el).append('svg').attr('width', W).attr('height', H)
  const g = svg.append('g')
  svg.call(d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.1, 5]).on('zoom', (ev) => g.attr('transform', ev.transform)))

  const tip = d3.select(el).append('div').style('position', 'absolute').style('pointer-events', 'none')
    .style('background', '#1f2937').style('color', '#f9fafb').style('padding', '6px 10px')
    .style('border-radius', '6px').style('font-size', '11px').style('opacity', '0')
    .style('transition', 'opacity 0.15s').style('max-width', '300px').style('z-index', '100')

  nodes.forEach((n: any) => { n.x = W / 2 + (Math.random() - 0.5) * 200; n.y = H / 2 + (Math.random() - 0.5) * 200 })

  const link = g.append('g').selectAll('line').data(edges).join('line')
    .attr('stroke', (d: any) => edgeColors[d.type] || '#d1d5db')
    .attr('stroke-width', (d: any) => Math.max(0.3, (d.confidence || 0.3) * 1.5))
    .attr('stroke-opacity', 0.5)
    .attr('stroke-dasharray', (d: any) => edgeDashes[d.type] || '')
    .on('mouseenter', (ev: any, d: any) => {
      tip.style('opacity', '1').html(`<strong>${d.type}</strong><br/>${d.label || ''}`)
    })
    .on('mousemove', (ev: any) => { tip.style('left', (ev.offsetX + 12) + 'px').style('top', (ev.offsetY - 10) + 'px') })
    .on('mouseleave', () => { tip.style('opacity', '0') })

  const isHL = (d: any) => !focusNode || d.id === focusNode

  const ng = g.append('g').selectAll('g').data(nodes).join('g')
    .attr('cursor', 'pointer')
    .on('click', (ev: any, d: any) => { ev.stopPropagation(); onNodeClick?.(d.id) })
    .on('mouseenter', (ev: any, d: any) => {
      const extras = d.circuit_name ? `<br/>${d.circuit_name}` : ''
      const stepInfo = d.step_order != null ? `<br/>Step ${d.step_order} · ${d.role || ''}` : ''
      tip.style('opacity', '1').html(`<strong>${d.type}</strong>: ${d.label}${stepInfo}${extras}`)
    })
    .on('mousemove', (ev: any) => { tip.style('left', (ev.offsetX + 12) + 'px').style('top', (ev.offsetY - 10) + 'px') })
    .on('mouseleave', () => { tip.style('opacity', '0') })

  ng.append('circle')
    .attr('r', (d: any) => isHL(d) ? (focusNode ? 12 : (nodeRadii[d.type] || 6)) : (nodeRadii[d.type] || 6))
    .attr('fill', (d: any) => isHL(d) ? (focusNode && d.id === focusNode ? '#ef4444' : nodeColors[d.type] || '#999') : nodeColors[d.type] || '#999')
    .attr('stroke', (d: any) => isHL(d) ? '#fff' : 'none').attr('stroke-width', 2).attr('opacity', 1)

  ng.append('text').text((d: any) => (d.label || '').slice(0, 12))
    .attr('dx', 10).attr('dy', 4).style('font-size', '7px').style('fill', '#374151').style('opacity', 1)

  const sim = d3.forceSimulation(nodes as any)
    .force('link', d3.forceLink(edges).id((d: any) => d.id).distance(120))
    .force('charge', d3.forceManyBody().strength(-500))
    .force('center', d3.forceCenter(W / 2, H / 2))
    .force('collision', d3.forceCollide(25))
    .on('tick', () => {
      link.attr('x1', (d: any) => d.source.x).attr('y1', (d: any) => d.source.y)
          .attr('x2', (d: any) => d.target.x).attr('y2', (d: any) => d.target.y)
      ng.attr('transform', (d: any) => `translate(${d.x},${d.y})`)
    })

  // Drag
  ng.call(d3.drag<SVGGElement, any>()
    .on('start', (ev: any, d: any) => { if (!ev.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
    .on('drag', (ev: any, d: any) => { d.fx = ev.x; d.fy = ev.y })
    .on('end', (ev: any, d: any) => { if (!ev.active) sim.alphaTarget(0) }) as any)

  sim.alpha(1).restart()
  for (let i = 0; i < 300; i++) sim.tick()

  // Legend
  if (legendItems && legendItems.length > 0) {
    const legendRow = d3.select(el).append('div')
      .style('position', 'absolute').style('bottom', '8px').style('left', '12px').style('right', '12px')
      .style('display', 'flex').style('gap', '12px').style('flexWrap', 'wrap')
      .style('fontSize', '11px').style('color', '#555').style('lineHeight', '18px')
      .style('background', 'rgba(255,255,255,0.85)').style('padding', '6px 10px')
      .style('borderRadius', '6px').style('pointerEvents', 'none')

    for (const item of legendItems) {
      const span = legendRow.append('span').style('display', 'inline-flex').style('alignItems', 'center').style('gap', '4px')
      const line = span.append('span')
        .style('display', 'inline-block').style('width', '20px').style('height', '2px')
        .style('background', item.color).style('verticalAlign', 'middle')
      if (item.dash) line.style('borderBottom', `2px ${item.dash.includes(',') ? 'dashed' : 'solid'} ${item.color}`)
      span.append('span').text(item.label)
    }
  }
}
```

- [ ] **Step 2: Update GraphExplorerPage to use shared component**

In `frontend/src/pages/GraphExplorerPage.tsx`:
- Remove `ForceGraph` function (lines 189–248) and `drawGraph` function (lines 251–305)
- Replace with import: `import { ForceGraph, type GNode, type GEdge } from '../components/ForceGraph'`
- Remove local `GNode`/`GEdge` interfaces (keep the `RawGraph` type)
- Update `ForceGraph` usage to pass `edgeColors={EDGE_COLOR} edgeDashes={EDGE_DASH} nodeColors={NODE_COLOR} nodeRadii={NODE_R}`
- Keep local `EDGE_COLOR`, `EDGE_DASH`, `NODE_COLOR`, `NODE_R` constants (these are the page's visual configuration)

- [ ] **Step 3: Add legend items to GraphExplorerPage ForceGraph call**

Add `legendItems` prop to the ForceGraph call in GraphExplorerPage (around the `ForceGraph` invocation in the page render):

```tsx
<ForceGraph nodes={visNodes} edges={visEdges} focusNode={focusNode}
  onNodeClick={tab==='focus'?setFocusNode:undefined}
  edgeColors={EDGE_COLOR} edgeDashes={EDGE_DASH}
  nodeColors={NODE_COLOR} nodeRadii={NODE_R}
  legendItems={[
    {color:'#3b82f6',dash:'',label:'脑区(Region)'},
    {color:'#f59e0b',dash:'',label:'回路(Circuit)'},
    {color:'#10b981',dash:'',label:'连接(Connection)'},
    {color:'#3b82f6',dash:'',label:'━ 结构连接'},
    {color:'',dash:'6,3',label:'╌ 功能连接'},
    {color:'',dash:'2,2',label:'┈ 投射'},
    {color:'#fcd34d',dash:'',label:'━ 回路起止'},
    {color:'',dash:'6,3',label:'╌ 回路包含'},
  ]}
/>
```

Then remove the old inline legend div (lines 144–158 of GraphExplorerPage.tsx).

- [ ] **Step 4: Verify build compiles**

Run: `cd frontend && npx tsc --noEmit 2>&1 | grep -c "error"`
Expected: 0

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ForceGraph.tsx frontend/src/pages/GraphExplorerPage.tsx
git commit -m "refactor: extract shared ForceGraph component with customizable colors and legend"
```

---

### Task 4: Frontend — Chat Panel + State Machine

**Files:**
- Modify: `frontend/src/pages/SymptomQueryPage.tsx` (rewrite top section)

**Interfaces:**
- Consumes: `POST /api/symptom-query/conversation` (from Task 1)
- Produces: Chat panel UI + state machine (idle→chatting→summarizing→confirmed→analyzing→results)

- [ ] **Step 1: Replace the input area with chat panel**

In `SymptomQueryPage.tsx`, replace the current search card (current lines 122–131, the `<div className="card">` with single-line input) with the chat panel.

Add state variables:

```typescript
const [phase, setPhase] = useState<'idle'|'chatting'|'summarizing'|'confirmed'|'analyzing'|'results'>('idle')
const [messages, setMessages] = useState<{role:string;content:string}[]>([])
const [summary, setSummary] = useState('')
const [chatLoading, setChatLoading] = useState(false)
const [chatInput, setChatInput] = useState('')
const chatEndRef = useRef<HTMLDivElement>(null)
```

Replace the card at current line ~122 with:

```tsx
<div className="card" style={{ padding: 16, marginBottom: 16 }}>
  {/* Chat area */}
  {phase !== 'results' && (
    <>
      {messages.length > 0 && (
        <div style={{ maxHeight: 280, overflow: 'auto', marginBottom: 12, padding: '4px 0' }}>
          {messages.map((m, i) => (
            <div key={i} style={{
              display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start',
              marginBottom: 8,
            }}>
              <div style={{
                maxWidth: '75%', padding: '8px 12px', borderRadius: 12, fontSize: 13,
                background: m.role === 'user' ? '#eef4ff' : '#f3f4f6',
                color: m.role === 'user' ? '#1e40af' : '#374151',
                whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              }}>
                {m.content}
              </div>
            </div>
          ))}
          <div ref={chatEndRef} />
        </div>
      )}

      {/* Confirmation card (summarizing stage) */}
      {phase === 'summarizing' && (
        <div style={{ background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: 8, padding: 12, marginBottom: 12 }}>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6, color: '#92400e' }}>📋 AI 症状分析总结</div>
          <textarea
            className="form-input"
            value={summary}
            onChange={e => setSummary(e.target.value)}
            style={{ width: '100%', minHeight: 80, fontSize: 12, marginBottom: 8 }}
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-primary btn-sm" onClick={handleConfirm}>确认并开始分析</button>
            <button className="btn btn-sm" onClick={handleContinueChat}>继续对话</button>
          </div>
        </div>
      )}

      {/* Input bar */}
      {phase !== 'summarizing' && (
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            className="form-input" style={{ flex: 1 }}
            placeholder={messages.length === 0 ? '描述你的症状，如：头晕眼花走路不稳…' : '输入回复…'}
            value={chatInput}
            onChange={e => setChatInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSend()}
            disabled={chatLoading || phase === 'analyzing'}
          />
          <button className="btn btn-primary" onClick={handleSend} disabled={chatLoading || !chatInput.trim()}>
            {chatLoading ? '…' : '发送'}
          </button>
          {messages.length > 0 && (
            <button className="btn" onClick={handleClear}>清空</button>
          )}
        </div>
      )}
    </>
  )}

  {/* Analyzing spinner */}
  {phase === 'analyzing' && (
    <div style={{ textAlign: 'center', padding: 20, color: '#888', fontSize: 14 }}>
      ⏳ 正在分析症状并检索回路…
    </div>
  )}

  {/* After results: mode toggle + re-query bar (collapsed, expandable) */}
  {phase === 'results' && (
    <details style={{ fontSize: 12, color: '#888' }}>
      <summary>重新查询</summary>
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <button className={`btn btn-sm ${mode === 'single' ? 'btn-primary' : ''}`} onClick={() => setMode('single')}>单功能</button>
        <button className={`btn btn-sm ${mode === 'multi' ? 'btn-primary' : ''}`} onClick={() => setMode('multi')}>多功能</button>
        <button className="btn btn-sm" onClick={handleClear}>新查询</button>
      </div>
    </details>
  )}
</div>
```

- [ ] **Step 2: Implement handleSend, handleConfirm, handleContinueChat, handleClear**

```typescript
const handleSend = useCallback(async () => {
  const text = chatInput.trim(); if (!text) return
  setChatInput('')
  const newMessages = [...messages, { role: 'user', content: text }]
  setMessages(newMessages)
  if (phase === 'idle') setPhase('chatting')
  setChatLoading(true)
  try {
    const resp = await postJson<{stage:string;content:string|null;summary:string|null}>(
      '/api/symptom-query/conversation',
      { messages: newMessages, granularity_level: granularity },
    )
    if (resp.stage === 'asking' && resp.content) {
      setMessages([...newMessages, { role: 'assistant', content: resp.content }])
    } else if (resp.stage === 'summarizing' && resp.summary) {
      setMessages([...newMessages, { role: 'assistant', content: '我已经收集了足够的信息。请查看下方的症状总结，确认后我将开始分析。' }])
      setSummary(resp.summary)
      setPhase('summarizing')
    }
  } catch { /* retry? */ }
  finally { setChatLoading(false) }
  setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
}, [chatInput, messages, phase, granularity])

const handleConfirm = useCallback(async () => {
  if (!summary.trim()) return
  setPhase('analyzing')
  setError(null)
  try {
    const ar = await postJson<{functions:string[]}>('/api/symptom-query/analyze', { symptom: summary.trim(), mode })
    const funcs = ar.functions || []; setStdFunctions(funcs)
    const er = await postJson<{expanded:string[]}>('/api/symptom-query/expand', { functions: funcs })
    const sr = await postJson<{circuits:CircuitResult[]}>('/api/symptom-query/search', {
      functions: er.expanded || funcs, granularity_level: granularity,
    })
    const found = sr.circuits || []; setCircuits(found)
    if (found.length > 0) {
      const gr = await postJson<GraphData>('/api/symptom-query/graph', {
        circuit_ids: found.map(c => c.id), granularity_level: granularity,
      })
      setGraph(gr)
      setPhase('results')
    } else {
      setPhase('results')  // no circuits, show empty state
    }
  } catch (e: any) { setError(e?.message || String(e)); setPhase('idle') }
}, [summary, mode, granularity])

const handleContinueChat = useCallback(() => {
  setPhase('chatting')
  setSummary('')
}, [])

const handleClear = useCallback(() => {
  setPhase('idle'); setMessages([]); setSummary(''); setChatInput('')
  setStdFunctions([]); setCircuits([]); setError(null); setGraph(null); setSelectedId(null)
}, [])
```

- [ ] **Step 3: Add `useRef` to imports**

Change the React import line:

```typescript
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
```

- [ ] **Step 4: Build and verify**

Run: `cd frontend && npm run build 2>&1 | grep -E "error TS|✓ built"`
Expected: `✓ built in ...` + exit 0

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/SymptomQueryPage.tsx
git commit -m "feat: add AI conversational triage chat panel to SymptomQueryPage"
```

---

### Task 5: Frontend — Integrate Step-Level ForceGraph + Legend

**Files:**
- Modify: `frontend/src/pages/SymptomQueryPage.tsx` (graph rendering section)

**Interfaces:**
- Consumes: Shared `ForceGraph` component (from Task 3)
- Consumes: Step-level graph data (from Task 2)

- [ ] **Step 1: Replace old graph rendering with shared ForceGraph + custom colors + legend**

In `SymptomQueryPage.tsx`, replace the graph rendering section. The current `gNodes`/`gEdges` use simple types — keep them but remove the old `ForceGraph`/`drawGraph` functions (they're now in the shared component). Remove local `NODE_COLOR`, `NODE_R`, `EDGE_COLOR`, `EDGE_DASH` constants (the shared component has defaults).

Replace any remaining local ForceGraph/drawGraph with:

```typescript
// Update graph types
const gNodes: GNode[] = useMemo(() => {
  if (!graph) return []
  return graph.nodes.map(n => ({
    ...n,
    id: n.id, type: n.type, label: n.label,
  }))
}, [graph])

const gEdges: GEdge[] = useMemo(() => {
  if (!graph) return []
  return graph.edges.map(e => ({ id: e.id, source: e.source, target: e.target, type: e.type, label: e.label || '' }))
}, [graph])
```

Add edge color/dash maps for the symptom query page:

```typescript
const SYMPTOM_EDGE_COLOR: Record<string, string> = {
  step_flow:   '#10b981',
  belongs_to:  '#d1d5db',
  co_occurs:   '#8b5cf6',
}
const SYMPTOM_EDGE_DASH: Record<string, string> = {
  step_flow:   '2,2',
  belongs_to:  '',
  co_occurs:   '6,3',
}
const SYMPTOM_NODE_COLOR: Record<string, string> = {
  brain_region: '#3b82f6',
  circuit:      '#f59e0b',
}
const SYMPTOM_NODE_R: Record<string, number> = {
  brain_region: 7,
  circuit:      7,
}
```

Define legend items:

```typescript
const SYMPTOM_LEGEND: LegendItem[] = [
  { color: '#3b82f6', dash: '', label: '● 脑区 (Brain Region)' },
  { color: '#f59e0b', dash: '', label: '● 回路 (Circuit)' },
  { color: '#10b981', dash: '2,2', label: '┈ step_flow (步骤流向)' },
  { color: '#8b5cf6', dash: '6,3', label: '╌ co_occurs (共享脑区)' },
  { color: '#d1d5db', dash: '', label: '━ belongs_to (回路归属)' },
]
```

Replace the `<ForceGraph ...>` call in the render with:

```tsx
<ForceGraph
  nodes={gNodes} edges={gEdges}
  focusNode={selectedId}
  onNodeClick={(id) => setSelectedId(selectedId === id ? null : id)}
  edgeColors={SYMPTOM_EDGE_COLOR} edgeDashes={SYMPTOM_EDGE_DASH}
  nodeColors={SYMPTOM_NODE_COLOR} nodeRadii={SYMPTOM_NODE_R}
  legendItems={SYMPTOM_LEGEND}
/>
```

- [ ] **Step 2: Remove old local ForceGraph/drawGraph functions**

Delete any remaining `ForceGraph` or `drawGraph` function definitions in SymptomQueryPage.tsx. Remove unused local `NODE_COLOR`, `NODE_R`, `EDGE_COLOR`, `EDGE_DASH` — replace references with the new `SYMPTOM_*` maps.

- [ ] **Step 3: Import shared ForceGraph**

Update the import at the top:

```typescript
import { ForceGraph, type GNode, type GEdge, type LegendItem } from '../components/ForceGraph'
```

- [ ] **Step 4: Build and verify**

Run: `cd frontend && npm run build 2>&1 | grep -E "error TS|✓ built"`
Expected: `✓ built in ...` + exit 0

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/SymptomQueryPage.tsx
git commit -m "feat: integrate step-level ForceGraph with legend into SymptomQueryPage"
```

---

### Task 6: Final Integration + Smoke Test

**Files:**
- Modify: `frontend/src/pages/SymptomQueryPage.tsx` (tie together all phases)

**Goal:** Ensure the full flow works end-to-end: chat → confirm → analyze → circuit list → step-level graph with legend.

- [ ] **Step 1: Verify Phase 2 auto-chain triggers correctly**

The `handleConfirm` function (Task 4) already calls analyze→expand→search→graph in sequence. Verify the state transitions by reading the code path:
1. User clicks "确认并开始分析" → `setPhase('analyzing')`
2. analyze/expand/search succeed → `setPhase('results')`
3. If search returns empty → still `results` but empty state shown
4. If any step fails → `setPhase('idle')` with error

This is already implemented in `handleConfirm` from Task 4. No additional code needed.

- [ ] **Step 2: Ensure existing circuit list + detail sidebar still work**

The left panel (circuit list with match scores) and right detail sidebar (circuit name, matched functions, steps, stats) are from the previous upgrade and should be unchanged. Check that:
- `selectedCircuit` still resolves from `circuits.find(c => c.id === selectedId)`
- Click on circuit in left list sets `selectedId` and triggers ForceGraph highlight (via `focusNode`)
- Detail sidebar renders match score, functions tags, step list
- The `handleSelect` callback still works (click circuit node in graph → set selectedId)

No code change needed here — these are all preserved from the previous SymptomQueryPage upgrade.

- [ ] **Step 3: Full build**

Run: `cd frontend && npm run build 2>&1`
Expected: exit 0, no errors

- [ ] **Step 4: Backend test suite**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests/test_symptom_query.py -q`
Expected: 3 passed

- [ ] **Step 5: Full backend test suite (spot check)**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests/ -q 2>&1 | tail -5`
Expected: Only the known pre-existing failures (5 in test_llm_field_completion.py + 1 in test_resource_registry.py + 1 in test_connection*)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: complete SymptomQueryPage upgrade — conversational triage + step-level brain region graph with legend"
```

---

## Verification Checklist

After all tasks complete:

- [ ] Backend: `POST /conversation` returns `asking` stage with follow-up question
- [ ] Backend: `POST /conversation` returns `summarizing` stage with clinical summary after 2+ exchanges
- [ ] Backend: `POST /graph` returns step-level nodes with `brain_region` type and real region labels
- [ ] Backend: `POST /graph` returns `step_flow`, `belongs_to`, and `co_occurs` edge types
- [ ] Frontend: Chat panel shows message bubbles, sends to `/conversation`, shows LLM response
- [ ] Frontend: Confirmation card appears when LLM summarizes, editable textarea
- [ ] Frontend: "确认并开始分析" auto-chains analyze→expand→search→graph
- [ ] Frontend: Step-level graph renders with D3 force layout, nodes are draggable
- [ ] Frontend: Legend strip at bottom of graph with correct colors and dash styles
- [ ] Frontend: Clicking a circuit node highlights it red, connected brain regions highlight
- [ ] Frontend: Shared brain regions show `co_occurs` edges in purple
- [ ] Frontend: GraphExplorerPage still works correctly with shared ForceGraph component
