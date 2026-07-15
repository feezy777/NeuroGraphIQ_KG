# Symptom Query Refined — Categories + Relevance + Unified Brain-Region Graph

## 1. Backend: `/analyze` — Add Category Classification

Extend the LLM prompt to classify each function into a predefined category.

**Categories (9):** `motor | sensory | cognitive | emotional | autonomic | memory | language | attention | other`

**New response:**
```json
{
  "functions": ["motor coordination", "balance control"],
  "categories": ["motor", "motor"],
  "primary_category": "motor"
}
```

## 2. Backend: `/search` — Weighted Relevance Scoring

Replace the loose `similarity > 0.15` OR logic with a weighted scoring algorithm.

**Algorithm:**
```
relevance = category_bonus(30) + similarity(50) + density(20)
```
- `category_bonus`: count of matching categories between circuit functions and symptom categories × 10, capped at 30
- `similarity`: max trigram similarity between any symptom function term and any circuit function term × 50
- `density`: (matched_functions / total_functions) × 20

**Filter:** Only circuits with relevance ≥ 15. Sort by relevance DESC. Max 50 results.

**Implementation:** Compute in Python after loading candidate circuits, not in raw SQL.

## 3. Backend: `/graph` — Brain Regions + Connections Only

Unified graph: nodes = brain_regions, edges = projections between them.
For each matched circuit, resolve which brain regions (via steps) and connections are involved.

**Response:**
```json
{
  "nodes": [
    {"id": "region_uuid", "type": "brain_region", "label": "Visceral area, layer 5",
     "circuit_ids": ["cA", "cB"]}
  ],
  "edges": [
    {"id": "proj_uuid", "source": "region_A", "target": "region_B",
     "type": "structural_connection", "circuit_ids": ["cA"]}
  ]
}
```
Each node/edge carries a `circuit_ids` array so the frontend knows which circuit(s) it belongs to — used for highlighting.

## 4. Frontend: Categorized Circuit List + Unified Graph

**Left panel:**
- Circuits grouped by category (motor group, sensory group, …)
- Each circuit shows: name, relevance score bar, matched functions
- Click a circuit → highlight its brain regions + connections in the graph

**Right panel: ForceGraph**
- Renders ALL brain regions as nodes + ALL connections as edges
- **Highlight on click**: when a circuit is selected, all nodes/edges with that circuit_id in their array get highlighted (full opacity + red stroke), others stay at normal opacity (not dimmed)
- Performance: node count = brain regions only (not per-step), edge count = connections only (no step_flow/belongs_to edges)
- Legend: same as GraphExplorerPage (brain region node + connection types)

**Right sidebar (on circuit click):**
- Same detail panel as before: circuit name, matched functions, steps, stats

## 5. Performance

- Brain-region-only graph → orders of magnitude fewer nodes than step-level graph
- All relevant circuits rendered in one force layout (no separate sub-graphs)
- `maxRender` already at 200000 edges and 50000 nodes for scalability
- ForceGraph sorting (rare edges on top) already in place

## Files Changed

| File | Change |
|------|--------|
| `backend/app/routers/symptom_query.py` | `/analyze` + category, `/search` + relevance scoring, `/graph` + circuit_ids on nodes/edges |
| `frontend/src/pages/SymptomQueryPage.tsx` | Categorized list + unified graph highlight + legend |

## Testing

- Backend: unit test for relevance scoring algorithm
- Backend: verify `/graph` returns nodes/edges with circuit_ids
- Frontend: build passes, manual E2E
