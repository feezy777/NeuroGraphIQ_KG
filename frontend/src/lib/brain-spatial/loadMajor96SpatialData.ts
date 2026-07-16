/**
 * loadMajor96SpatialData.ts — Load brain surface meshes and region node coordinates.
 */
import type { BrainRegionNodesData, BrainSurfaceMesh, BrainSurfaceMeta } from './brain3d.types'

const BASE = '/brain_3d/major96'

let cachedNodes: BrainRegionNodesData | null = null
let cachedSurfaceMeta: BrainSurfaceMeta | null = null

export async function fetchRegionNodes(): Promise<BrainRegionNodesData> {
  if (cachedNodes) return cachedNodes
  const resp = await fetch(`${BASE}/brain_region_nodes.json`)
  if (!resp.ok) throw new Error(`Failed to load region nodes: ${resp.status}`)
  cachedNodes = await resp.json()
  return cachedNodes!
}

export async function fetchSurfaceMeta(): Promise<BrainSurfaceMeta> {
  if (cachedSurfaceMeta) return cachedSurfaceMeta
  const resp = await fetch(`${BASE}/brain_surface_metadata.json`)
  if (!resp.ok) throw new Error(`Failed to load surface metadata: ${resp.status}`)
  cachedSurfaceMeta = await resp.json()
  return cachedSurfaceMeta!
}

export async function fetchBrainSurface(hemi: 'left' | 'right'): Promise<BrainSurfaceMesh> {
  const resp = await fetch(`${BASE}/brain_${hemi}.json`)
  if (!resp.ok) throw new Error(`Failed to load brain surface (${hemi}): ${resp.status}`)
  return resp.json()
}

/** Get the 72 verified+plottable nodes, excluding manual_review and unmapped */
export function getPlottableNodes(data: BrainRegionNodesData) {
  return data.nodes.filter(
    (n) =>
      n.mapping_status === 'verified_exact' ||
      n.mapping_status === 'verified_alias',
  )
}
