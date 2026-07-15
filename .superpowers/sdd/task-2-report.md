# Task 2 Report: Rewrite /graph Endpoint with Step-Level Data

**Status**: DONE

## Summary

Replaced the regex-based `/api/symptom-query/graph` endpoint with a real step-level implementation that reads from `mirror_circuit_steps` joined to `candidate_brain_regions`.

## What Was Changed

### `backend/app/routers/symptom_query.py`

Replaced the `get_circuit_graph` function (lines 390-450) with a new implementation:

- **Nodes**: One `brain_region` node per step (with `circuit_id`, `step_order`, `role`, `step_name`, `region_candidate_id`) + one `circuit` node per circuit (with `label = circuit_name`)
- **Edges**:
  - `step_flow` — connects consecutive steps within the same circuit
  - `belongs_to` — connects each step node to its parent circuit
  - `co_occurs` — connects brain_region nodes of steps from different circuits that share the same `region_candidate_id`
- **Data source**: Raw SQL via `text()` joining `mirror_circuit_steps` with `candidate_brain_regions` on `region_candidate_id`
- **Region label**: `COALESCE(c.en_name, c.std_name, c.raw_name, s.step_name)` — prefers English name from candidate regions
- Removed `import re` (no longer needed for circuit_name parsing)

### `backend/tests/test_symptom_query.py`

Added `test_graph_returns_step_level_nodes` — integration test that:

1. Inserts real test data via `AsyncSessionLocal` (bypasses FK checks via `SET session_replication_role = replica`)
2. Creates 3 `candidate_brain_regions`, 2 `mirror_region_circuits`, 4 `mirror_circuit_steps`
3. Calls `POST /api/symptom-query/graph` with both circuit IDs
4. Asserts: correct node count (6+), correct region labels/metadata, all edge types present
5. Cleans up all test data in `finally` block

## Verification

```
$ pytest tests/test_symptom_query.py -q
.....                                      [100%]
5 passed, 2 warnings in 1.59s

$ python -c "import app.main; print('OK')"
OK
```

## Implementation Notes

- Node IDs are `step_{uuid[:12]}` — unique per step, no dedup by region_candidate_id (each step gets its own node, enabling co_occurs edges across circuits)
- `co_occurs` only fires when steps from genuinely different circuits share a region_candidate_id
- The test uses real DB inserts rather than mocks, with idempotent cleanup
