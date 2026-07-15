# Task 2: Backend — Rewrite Graph Endpoint with Step-Level Data

Replace the current `/graph` endpoint (which parses circuit_name with regex) with real step data from `mirror_circuit_steps` joined to `candidate_brain_regions`.

## Spec
- Read steps for requested circuits, JOIN region labels
- Nodes: one per step (type=brain_region, with circuit_id, step_order, role) + one per circuit (type=circuit)
- Edges: step_flow (step_i → step_{i+1} within same circuit), belongs_to (step → circuit), co_occurs (steps across circuits sharing same region_candidate_id)
- Keep existing GraphDataRequest/GraphDataResponse schemas

## Steps
1. Write test in test_symptom_query.py (integration: insert test data, call /graph, verify node/edge structure)
2. Run: FAIL (old regex-based output)
3. Replace graph endpoint (lines 292-364) with new implementation using real step data
4. Run: 1 new test + 4 prior tests = 5 passed
5. `python -c "import app.main"` → OK
6. Commit
