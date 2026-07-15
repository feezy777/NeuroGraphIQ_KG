# GraphExplorerPage Simplify — Brain Regions Only

## Goal
Remove circuit nodes, connection nodes, and circuit-related edges from GraphExplorerPage. Only brain region nodes + connection edges remain.

## Backend: `GET /api/kg/graph/data`

**Remove:**
- Circuit node generation (query mirror_region_circuits, append circuit nodes, STARTS_AT, ENDS_AT edges)
- Membership edge generation (mirror_circuit_projection_memberships, INCLUDES edges)
- `include_circuits` query parameter (always false / removed)

**Keep:**
- Region nodes from candidate_brain_regions
- Connection edges from mirror_region_connections (joined to region_ids)

## Frontend: `GraphExplorerPage.tsx`

**normalize() function:** remove connection-node creation from edge IDs.

**EDGE_COLOR/EDGE_DASH:** remove STARTS_AT, ENDS_AT, INCLUDES entries.

**LEGEND_ITEMS:** remove circuit, connection node entries. Remove 回路起止/回路包含 entries. Keep brain region node + all connection types.

**Filter dropdown:** remove STARTS_AT, ENDS_AT, INCLUDES options.

**Tube selector:** remove `focus` tab (was circuit-focused). Keep `global` and `data`.

**Stats display:** remove circuits and memberships stats. Keep regions + connections.

## Shared ForceGraph
No changes — already parameterized via props.

## Testing
- Backend: update test_graph_returns_step_level_nodes (now graph endpoint is independent)
- Frontend: build passes
- Visual: macro and molecular graphs show only brain region nodes + colored connection edges
