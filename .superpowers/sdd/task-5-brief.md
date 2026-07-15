# Task 5: Integrate Shared ForceGraph + Legend into SymptomQueryPage

Replace the local ForceGraph/drawGraph in SymptomQueryPage with the shared ForceGraph component (from Task 3). Add step-level color maps and legend.

## Steps
1. Remove local ForceGraph/drawGraph functions + local GNode/GEdge types + local NODE_COLOR/NODE_R/EDGE_COLOR/EDGE_DASH from SymptomQueryPage.tsx
2. Import ForceGraph, GNode, GEdge, LegendItem from '../components/ForceGraph'
3. Add customized color/dash/radii maps for symptom query:
   - SYMPTOM_EDGE_COLOR: step_flow=#10b981, belongs_to=#d1d5db, co_occurs=#8b5cf6
   - SYMPTOM_EDGE_DASH: step_flow='2,2', belongs_to='', co_occurs='6,3'
   - SYMPTOM_NODE_COLOR: brain_region=#3b82f6, circuit=#f59e0b
   - SYMPTOM_NODE_R: brain_region=7, circuit=7
   - SYMPTOM_LEGEND with 5 items (node + edge types, Chinese labels)
4. Replace <ForceGraph ...> call to pass these props + legendItems
5. `npm run build` → exit 0
6. `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_symptom_query.py -q` → 5 passed
7. Commit
