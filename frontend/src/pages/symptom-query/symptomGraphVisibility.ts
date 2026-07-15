import {
  BACKGROUND_EDGE_LIMIT_DEFAULT,
  BACKGROUND_EDGE_LIMIT_MAX,
  type NormalizedEdge,
  type NormalizedNode,
  type SymptomDisplayMode,
  type SymptomGraphModel,
  type VisibilityResult,
} from './symptomGraphTypes'

export interface VisibilityOptions {
  displayMode: SymptomDisplayMode
  selectedCircuitId: string | null
  selectedStepIndex: number | null
  focusedNodeId: string | null
  minConfidence: number
  relationFilter: string
  searchQuery: string
  showBackgroundEdges: boolean
  backgroundEdgeLimit?: number
  /** step index -> region node id (from circuit step mapping) */
  stepRegionIds: string[]
}

function edgeWeight(edge: NormalizedEdge): number {
  return edge.confidence + (edge.isStepFlow ? 0.15 : 0)
}

function passesFilters(edge: NormalizedEdge, opts: VisibilityOptions): boolean {
  if (edge.confidence < opts.minConfidence) return false
  if (opts.relationFilter !== 'all' && edge.type !== opts.relationFilter) return false
  return true
}

function collectOneHop(
  seedIds: Set<string>,
  edges: NormalizedEdge[],
): Set<string> {
  const out = new Set(seedIds)
  for (const edge of edges) {
    if (seedIds.has(edge.source)) out.add(edge.target)
    if (seedIds.has(edge.target)) out.add(edge.source)
  }
  return out
}

function pickBackgroundEdges(
  candidates: NormalizedEdge[],
  limit: number,
  excludeIds: Set<string>,
): NormalizedEdge[] {
  return candidates
    .filter(e => !excludeIds.has(e.id))
    .sort((a, b) => edgeWeight(b) - edgeWeight(a))
    .slice(0, Math.min(limit, BACKGROUND_EDGE_LIMIT_MAX))
}

export function computeSymptomGraphVisibility(
  model: SymptomGraphModel,
  opts: VisibilityOptions,
): VisibilityResult {
  const { indexes, edges: allEdges, nodes: allNodes } = model
  const circuitPathEdgeIds = new Set<string>()
  const activeStepEdgeIds = new Set<string>()

  if (allNodes.length === 0) {
    return { nodes: [], edges: [], circuitPathEdgeIds, activeStepEdgeIds }
  }

  const bgLimit = Math.min(
    opts.backgroundEdgeLimit ?? BACKGROUND_EDGE_LIMIT_DEFAULT,
    BACKGROUND_EDGE_LIMIT_MAX,
  )

  let seedNodeIds = new Set<string>()
  let circuitEdges: NormalizedEdge[] = []

  if (opts.selectedCircuitId) {
    seedNodeIds = new Set(indexes.circuitNodeIds.get(opts.selectedCircuitId) || [])
    circuitEdges = (indexes.circuitEdgesById.get(opts.selectedCircuitId) || [])
      .filter(e => passesFilters(e, opts))
    circuitEdges.forEach(e => circuitPathEdgeIds.add(e.id))
  } else {
    seedNodeIds = new Set(allNodes.map(n => n.id))
    circuitEdges = allEdges.filter(e => e.circuitIds.length > 0 && passesFilters(e, opts))
    circuitEdges.forEach(e => circuitPathEdgeIds.add(e.id))
  }

  if (opts.displayMode === 'step_focus' && opts.selectedCircuitId) {
    seedNodeIds = new Set(indexes.circuitNodeIds.get(opts.selectedCircuitId) || [])
    const visibleEdges = circuitEdges
    const visibleNodeIds = new Set<string>(seedNodeIds)
    for (const e of visibleEdges) {
      visibleNodeIds.add(e.source)
      visibleNodeIds.add(e.target)
    }
    return {
      nodes: allNodes.filter(n => visibleNodeIds.has(n.id)),
      edges: visibleEdges,
      circuitPathEdgeIds,
      activeStepEdgeIds,
    }
  }

  if (opts.displayMode === 'region_focus' && opts.focusedNodeId) {
    const hopIds = collectOneHop(new Set([opts.focusedNodeId]), allEdges)
    const visibleEdges = allEdges.filter(
      e => hopIds.has(e.source) && hopIds.has(e.target) && passesFilters(e, opts),
    )
    if (opts.selectedCircuitId) {
      visibleEdges.forEach(e => {
        if (e.circuitIds.includes(opts.selectedCircuitId!)) circuitPathEdgeIds.add(e.id)
      })
    }
    return {
      nodes: allNodes.filter(n => hopIds.has(n.id)),
      edges: visibleEdges,
      circuitPathEdgeIds,
      activeStepEdgeIds,
    }
  }

  // all_related — core circuit nodes + limited background
  const coreNodeIds = new Set(seedNodeIds)
  const neighborIds = collectOneHop(coreNodeIds, allEdges)
  const visibleNodeIds = new Set(coreNodeIds)
  for (const id of neighborIds) {
    if (!coreNodeIds.has(id)) visibleNodeIds.add(id)
  }

  const circuitEdgeIdSet = new Set(circuitEdges.map(e => e.id))
  let visibleEdges: NormalizedEdge[] = [...circuitEdges]

  if (opts.showBackgroundEdges) {
    const bgCandidates = allEdges.filter(
      e =>
        passesFilters(e, opts) &&
        !circuitEdgeIdSet.has(e.id) &&
        visibleNodeIds.has(e.source) &&
        visibleNodeIds.has(e.target) &&
        (coreNodeIds.has(e.source) || coreNodeIds.has(e.target)),
    )
    const bgPicked = pickBackgroundEdges(bgCandidates, bgLimit, circuitEdgeIdSet)
    visibleEdges = [...visibleEdges, ...bgPicked]
  }

  // Step highlight: edges touching selected step region
  if (
    opts.selectedStepIndex != null &&
    opts.stepRegionIds[opts.selectedStepIndex]
  ) {
    const rid = opts.stepRegionIds[opts.selectedStepIndex]
    const prevRid = opts.stepRegionIds[opts.selectedStepIndex - 1]
    const nextRid = opts.stepRegionIds[opts.selectedStepIndex + 1]
    for (const e of visibleEdges) {
      if (!opts.selectedCircuitId || !e.circuitIds.includes(opts.selectedCircuitId)) continue
      if ((prevRid && e.source === prevRid && e.target === rid) || (nextRid && e.source === rid && e.target === nextRid)) {
        activeStepEdgeIds.add(e.id)
      }
    }
  }

  if (opts.searchQuery.trim()) {
    const q = opts.searchQuery.trim().toLowerCase()
    const matched = allNodes.filter(
      n =>
        n.label.toLowerCase().includes(q) ||
        n.nameEn.toLowerCase().includes(q) ||
        n.nameCn.toLowerCase().includes(q) ||
        n.id.toLowerCase().includes(q),
    )
    matched.forEach(n => visibleNodeIds.add(n.id))
  }

  const edgeNodeIds = new Set<string>()
  visibleEdges.forEach(e => {
    edgeNodeIds.add(e.source)
    edgeNodeIds.add(e.target)
  })
  // Keep every region in the selected circuit visible even if its adjacent
  // edge has no resolved endpoint or is filtered by the confidence control.
  coreNodeIds.forEach(id => edgeNodeIds.add(id))

  return {
    nodes: allNodes.filter(n => visibleNodeIds.has(n.id) && edgeNodeIds.has(n.id)),
    edges: visibleEdges,
    circuitPathEdgeIds,
    activeStepEdgeIds,
  }
}
