# Task 3 Report: Extract Shared ForceGraph Component

## Summary

Successfully extracted the D3-based ForceGraph component from `GraphExplorerPage.tsx` into a shared component at `frontend/src/components/ForceGraph.tsx`, with all color/dash/radius maps parameterized as props.

## Changes

### Created: `frontend/src/components/ForceGraph.tsx`
- **Types:** `GNode`, `GEdge`, `LegendItem` (with index signature on GNode for extensibility, optional `confidence?`/`label?` on GEdge)
- **Defaults:** `NODE_COLOR`, `NODE_R`, `EDGE_COLOR`, `EDGE_DASH` maps (copied from GraphExplorerPage, consumers override via props)
- **`ForceGraph` component:** Accepts `nodes`, `edges`, `focusNode`, `onNodeClick`, `edgeColors`, `edgeDashes`, `nodeColors`, `nodeRadii`, `legendItems` props. Handles missing endpoint nodes, large-dataset limiting (2000 nodes max), and renders legend below the SVG when `legendItems` is provided.
- **`drawGraph` function:** Pure D3 SVG renderer, accepts the same color/dash/radius maps as parameters. Includes tooltip, zoom, drag, and force simulation.

### Updated: `frontend/src/pages/GraphExplorerPage.tsx`
- Removed local `GNode`/`GEdge` interfaces (use imported from shared)
- Removed local `ForceGraph` and `drawGraph` functions
- Kept local `NODE_COLOR`, `NODE_R`, `EDGE_COLOR`, `EDGE_DASH` as page-specific config, passed as props
- Removed inline legend div, replaced with `legendItems` prop on `ForceGraph`
- Fixed two TS errors from `confidence` becoming optional (used `?? 0`)

## Verification
- `npm run build` -- exit 0, no TS errors
- Backend tests: `tests/test_symptom_query.py` -- 5 passed
- Committed as `0703fcc` on `main`
