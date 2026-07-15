# Task 3: Extract Shared ForceGraph Component

Extract the D3 ForceGraph + drawGraph functions from GraphExplorerPage.tsx into a shared component at `frontend/src/components/ForceGraph.tsx` that both pages can use.

## Steps
1. Create `frontend/src/components/ForceGraph.tsx` — extract ForceGraph + drawGraph from GraphExplorerPage.tsx (the functions from the current file), parameterize colors/dashes/radii/legend as props
2. Update GraphExplorerPage.tsx: remove local ForceGraph/drawGraph, import from shared component, pass its specific color maps as props
3. Remove the old inline legend div from GraphExplorerPage (replace with legendItems prop)
4. `npm run build` → exit 0
5. Tests: run `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_symptom_query.py -q` (just to confirm backend still OK — 5 passed)
6. Commit
