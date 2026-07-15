# Symptom Query Page Upgrade — Conversational Triage + Step-Level Brain Region Graph

## Overview

Upgrade `SymptomQueryPage` with two major capabilities:

1. **AI Conversational Triage (Phase 1)** — Before converting symptoms to standardized
   functions, the user has a multi-turn dialogue with an LLM to narrow down and confirm
   the symptom picture. The confirmed summary then feeds downstream analysis.
2. **Step-Level Brain Region Graph (Phase 4)** — The right-side graph is rebuilt to
   show each circuit decomposed into its constituent steps, each step anchored to a
   real brain region (from `candidate_brain_regions`). Shared brain regions across
   circuits are naturally visible as convergence points. Edges use the same color-coded
   line styles as GraphExplorerPage, with a matching legend.

Phases 2 (function analysis) and 3 (circuit list + detail sidebar) remain structurally
unchanged, reusing the existing `/analyze`, `/expand`, and `/search` endpoints.

---

## Architecture

```
 ┌──────────────────────────────────────────────────────────────────┐
 │                    SymptomQueryPage                              │
 │                                                                  │
 │  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐ │
 │  │ Phase 1      │   │ Phase 2      │   │ Phase 3 + 4          │ │
 │  │ Chat Panel   │──▶│ Confirm Card │──▶│ Circuit List (left)  │ │
 │  │ (free text)  │   │ (summary)    │   │ + ForceGraph (right) │ │
 │  │              │   │ [edit + go]  │   │ + Detail Sidebar     │ │
 │  └──────────────┘   └──────────────┘   └──────────────────────┘ │
 │        │                   │                    │               │
 │        ▼                   ▼                    ▼               │
 │  POST /conversation   POST /analyze       POST /graph           │
 │                       POST /expand       (step-level)           │
 │                       POST /search                              │
 └──────────────────────────────────────────────────────────────────┘
```

**State machine (frontend):**

```
IDLE → CHATTING → SUMMARIZING → CONFIRMED → ANALYZING → RESULTS
                    │                           │
                    └── (user edits) ───────────┘
```

- `IDLE` — empty page, input visible
- `CHATTING` — conversation in progress, LLM asking follow-up questions
- `SUMMARIZING` — LLM produced a summary; confirmation card shown
- `CONFIRMED` — user approved (possibly edited) the summary
- `ANALYZING` — summary → analyze → expand → search (auto-chained, spinner shown)
- `RESULTS` — circuit list + step-level graph displayed

---

## Phase 1 — Conversational Triage

### Backend: `POST /api/symptom-query/conversation`

A new endpoint in `app/routers/symptom_query.py`. The LLM receives the full message
history and decides whether more questions are needed, or whether it has enough
information to produce a clinical summary.

**Request:**

```jsonc
{
  "messages": [
    {"role": "user",      "content": "I feel dizzy and unsteady when walking"},
    {"role": "assistant", "content": "Where exactly do you feel it? How long does it last?"},
    {"role": "user",      "content": "Mostly in the back of my head. Gets worse after standing for a while."}
  ],
  "granularity_level": "molecular_attr"
}
```

**Response — asking stage (LLM needs more information):**

```jsonc
{
  "stage": "asking",
  "content": "Do you also experience tinnitus (ringing in the ears) or hearing loss?",
  "summary": null
}
```

**Response — summarizing stage (LLM has enough context):**

```jsonc
{
  "stage": "summarizing",
  "content": null,
  "summary": "Patient reports posterior-head dizziness exacerbated by prolonged standing, suggestive of vestibular or posterior circulation involvement. No tinnitus or hearing loss reported. Duration and triggers point toward a possible vestibulo-cerebellar or brainstem-related circuit."
}
```

**LLM system prompt (inline in the endpoint):**

```
You are a clinical neuroscientist conducting a brief symptom triage interview.
Your goal is to gather enough information to produce a concise clinical summary
that can be converted into standardized brain function terms.

Rules:
- Ask at most ONE question per response. Be specific and focused.
- After 2–4 exchanges, if you have sufficient information, stop asking and
  produce a summary instead.
- When summarizing, synthesize the key symptom picture in 2–4 sentences.
  Include: suspected brain region(s), symptom characteristics, possible
  functional domains involved.
- Your response MUST be valid JSON: {"stage": "asking", "content": "...", "summary": null}
  OR {"stage": "summarizing", "content": null, "summary": "..."}
```

**Error handling:** On LLM failure, return the raw conversation text as a simple
summary so the flow can continue (graceful degradation).

**Schemas (in `app/routers/symptom_query.py`):**

```python
class ConversationRequest(BaseModel):
    messages: list[dict]  # [{"role": str, "content": str}, ...]
    granularity_level: str = "macro"

class ConversationResponse(BaseModel):
    stage: str           # "asking" | "summarizing"
    content: str | None  # LLM follow-up question (null when summarizing)
    summary: str | None  # Clinical summary (null when asking)
```

### Frontend: Chat Panel

Replace the current single-line `<input>` + "查询" button area (lines 122–131 of the
current page) with a chat panel.

**Layout:**
- Full-width card with scrollable message area (max ~300px height, auto-scroll)
- User messages: right-aligned, blue background (`#eef4ff`)
- Assistant messages: left-aligned, gray background (`#f3f4f6`), with a small "🧠" avatar
- Bottom bar: `<input>` + "Send" button (Enter to send)
- Disabled during `ANALYZING` phase

**Confirmation card (shown when `stage === "summarizing"`):**
- Appears overlaying or pushing the chat area
- Displays the LLM-generated summary in an editable `<textarea>`
- Two buttons: "Edit & Confirm" (primary) and "Continue Chat" (go back to CHATTING)
- On confirm → state transitions to `CONFIRMED` → triggers Phase 2

**State transitions:**

```typescript
const [phase, setPhase] = useState<'idle'|'chatting'|'summarizing'|'confirmed'|'analyzing'|'results'>('idle')
const [messages, setMessages] = useState<{role:string;content:string}[]>([])
const [summary, setSummary] = useState('')
```

When the user sends a message in `IDLE` or `CHATTING`:
1. Append user message to `messages`
2. POST to `/conversation` with full message history
3. If `stage === "asking"` → append assistant message, stay in `CHATTING`
4. If `stage === "summarizing"` → set `summary`, transition to `SUMMARIZING`

When the user confirms the summary:
1. Set `phase = 'analyzing'`
2. Chain: `POST /analyze` with `summary` as symptom → `POST /expand` → `POST /search`
3. On results: set `phase = 'results'`, render circuit list + graph

**"Clear" button behavior:** Resets all state to `IDLE`, clears messages, summary,
circuits, and graph.

---

## Phase 2 — Analysis (Reuse Existing)

No endpoint changes. The confirmed `summary` text is passed to:

1. `POST /api/symptom-query/analyze` — `{symptom: summary, mode: "multi"}`
   → returns standardized function terms
2. `POST /api/symptom-query/expand` — `{functions: [...]}`
   → returns expanded synonym list
3. `POST /api/symptom-query/search` — `{functions: expanded, granularity_level}`
   → returns ranked `CircuitResult[]`

All three are called sequentially with a single loading spinner. Individual errors
are caught and surfaced without blocking the chain (if analyze fails, try with raw
summary text as fallback).

---

## Phase 3 — Circuit List + Detail Sidebar (Unchanged)

The left panel (circuit list with match-score bars) and the right-side detail sidebar
(circuit name, matched functions, step list, stats) remain as-is from the previous
SymptomQueryPage upgrade.

---

## Phase 4 — Step-Level Brain Region Graph

### Backend: Rewrite `POST /api/symptom-query/graph`

**Current problem:** The `/graph` endpoint (`symptom_query.py` lines 304–364) parses
`circuit_name` with regex to guess brain region names. This is inaccurate and carries
no step-level information.

**Upgrade:** Read the `mirror_circuit_steps` table for each circuit, use
`region_candidate_id` to join `candidate_brain_regions` for real brain region names,
and build nodes/edges that reflect actual step anatomy.

**New implementation logic:**

```python
@router.post("/graph", response_model=GraphDataResponse)
async def get_circuit_graph(body: GraphDataRequest, session: AsyncSession):
    cids = [uuid.UUID(c) for c in body.circuit_ids if c]
    if not cids:
        return GraphDataResponse(nodes=[], edges=[])

    # 1. Load all circuits
    # 2. Load all steps for these circuits, JOIN region labels
    # 3. Build nodes: one per unique (step_id, region_id) + one per circuit
    # 4. Build edges:
    #    a. step_flow edges: step_i → step_{i+1} within same circuit (ordered by step_order)
    #    b. belongs_to edges: each step → its circuit node
    #    c. co_occurs edges (optional): two steps across circuits that share the same region_candidate_id
    #       → connect the two brain_region nodes via a dashed co_occurs edge
```

**SQL approach (raw parameterized SQL for performance):**

```sql
-- Load steps with region labels
SELECT s.id AS step_id, s.circuit_id, s.step_order, s.role, s.step_name,
       cbr.id AS region_uid, cbr.en_name AS region_name
FROM mirror_circuit_steps s
LEFT JOIN candidate_brain_regions cbr ON cbr.id = s.region_candidate_id
WHERE s.circuit_id IN (:cids)
ORDER BY s.circuit_id, s.step_order
```

**Node types:**

| node type | id pattern | label | visual |
|-----------|-----------|-------|--------|
| `brain_region` | `step_{step_uuid}` | `region_name` (from candidates table) | blue circle, radius varies by `role` |
| `circuit` | `circuit_{circuit_uuid}` | `circuit_name` | amber diamond/rounded rect |

**Edge types:**

| edge type | source → target | visual |
|-----------|----------------|--------|
| `step_flow` | `step_{s_i}` → `step_{s_{i+1}}` (same circuit) | dashed arrow, color varies by circuit |
| `belongs_to` | `step_{s}` → `circuit_{c}` | thin gray line |
| `co_occurs` | `step_{s_a}` → `step_{s_b}` (different circuits, same region_id) | dotted purple line |

**Response schema (unchanged from current — `GraphDataResponse`):**

```jsonc
{
  "nodes": [
    {"id": "step_uuid_A",   "type": "brain_region", "label": "Visceral area, layer 5",
     "circuit_id": "cA", "circuit_name": "viscerosensory_cortical_pathway",
     "step_order": 1, "role": "source"},
    {"id": "step_uuid_D",   "type": "brain_region", "label": "Orbital area, vl layer 1",
     "circuit_id": "cA", "circuit_name": "viscerosensory_cortical_pathway",
     "step_order": 4, "role": "target"},
    {"id": "circuit_cA", "type": "circuit", "label": "viscerosensory_cortical_pathway"}
  ],
  "edges": [
    {"id": "sf_1", "source": "step_uuid_A", "target": "step_uuid_B", "type": "step_flow", "label": "viscerosensory_cortical_pathway"},
    {"id": "bt_A", "source": "step_uuid_A", "target": "circuit_cA", "type": "belongs_to"},
    {"id": "co_1", "source": "step_uuid_A", "target": "step_uuid_X", "type": "co_occurs", "label": "Shared: Visceral area, layer 5"}
  ]
}
```

### Frontend: Reuse ForceGraph component + Matching Legend

The `ForceGraph` / `drawGraph` from `GraphExplorerPage.tsx` already provides D3
force-directed layout, zoom (scale 0.1–5), drag, tooltips, and node click handling.
We reuse the exact same render code, adapting only:
- Node colors/radii for our node types
- Edge color/dash based on `EDGE_COLOR` / `EDGE_DASH` from GraphExplorerPage

**Color mapping (matching GraphExplorerPage legend):**

```typescript
const NODE_COLOR: Record<string, string> = {
  brain_region: '#3b82f6',  // blue
  circuit:      '#f59e0b',  // amber
}
const NODE_R: Record<string, number> = {
  brain_region: 7,  // larger for source/target, smaller for relay
  circuit:      6,
}

// Reuse the SAME EDGE_COLOR from GraphExplorerPage:
const EDGE_COLOR: Record<string, string> = {
  step_flow:   '#10b981',  // green (like "projection")
  belongs_to:  '#d1d5db',  // light gray
  co_occurs:   '#8b5cf6',  // purple (like "association")
}

// Same dash styles from GraphExplorerPage:
const EDGE_DASH: Record<string, string> = {
  step_flow:   '2,2',      // dotted (directional flow)
  belongs_to:  '',          // solid
  co_occurs:   '6,3',      // dashed
}
```

**Highlight behavior on circuit click:**
- Clicked circuit node → turns red (`#ef4444`), radius 12
- All brain_region nodes belonging to that circuit → highlight to full opacity
- Other brain_region nodes → stay at normal opacity (do NOT dim)
- Click same circuit again → deselect (all nodes return to normal colors)

**Legend strip (below the graph, matching GraphExplorerPage style):**

```
Node:  ● Brain Region  ● Circuit
Edge:  ━━ step_flow (步骤流向)  ╌╌╌ co_occurs (共享脑区)  ━━ belongs_to (回路归属)
```

Positioned at the bottom of the graph container in a single row with `fontSize: 11`,
`color: #555`, matching the existing legend in `GraphExplorerPage.tsx` (lines 144–158).

---

## State Management

```
┌──────────────┐
│ phase        │── idle → chatting → summarizing → confirmed → analyzing → results
├──────────────┤
│ messages[]   │── accumulated chat history (for /conversation + display)
├──────────────┤
│ summary      │── LLM summary text (editable before confirmation)
├──────────────┤
│ stdFunctions │── from /analyze
│ circuits[]   │── from /search
│ selectedId   │── highlighted circuit (null = none)
├──────────────┤
│ graph        │── from /graph (nodes + edges for ForceGraph)
└──────────────┘
```

`useGlobalGranularity()` is already consumed (line 70 of current page). The `granularity`
value is passed to `/conversation`, `/search`, and `/graph`.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/routers/symptom_query.py` | Add `/conversation` endpoint + rewrite `/graph` endpoint |
| `frontend/src/pages/SymptomQueryPage.tsx` | Chat panel + confirmation card + ForceGraph integration + legend |
| `backend/tests/test_symptom_query.py` | (new) Test conversation stages + graph step-level output |

---

## Testing Strategy

### Backend

1. **`/conversation` unit test:**
   - Mock LLM provider to return `asking` stage → verify response shape
   - Mock LLM provider to return `summarizing` stage → verify summary is passed through
   - Test with empty messages array → graceful handling

2. **`/graph` unit test:**
   - Create mock circuits + steps with `region_candidate_id` → verify node count matches step count + circuit count
   - Two circuits sharing one brain region → verify `co_occurs` edge generated
   - Circuit with no `region_candidate_id` on any step → verify no crash, step nodes use `step_name` as fallback label

### Frontend

- Manual E2E: type symptom → chat a few rounds → confirm summary → verify circuit list loads → click circuit → verify ForceGraph highlights
- Visual: verify legend renders below graph, edge colors match legend, nodes are draggable

---

## Out of Scope

- Multi-user / session persistence for conversations (in-memory only per page visit)
- Real-time streaming of LLM responses (uses standard request/response)
- Mobile responsiveness (desktop-first)
- Graph export / screenshot functionality
