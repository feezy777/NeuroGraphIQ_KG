import type {
  GraphNormalizeStats,
  NormalizedEdge,
  NormalizedNode,
  RawGraphData,
  RawGraphEdge,
  RawGraphNode,
  SymptomGraphIndexes,
  SymptomGraphModel,
} from './symptomGraphTypes'

const UNKNOWN_LABELS = new Set(['', '?', 'unknown', 'unknown_region', 'Unknown', 'UNKNOWN'])

function endpointId(raw: unknown): string {
  if (raw == null) return ''
  if (typeof raw === 'object') {
    const obj = raw as { id?: unknown; name?: unknown }
    return String(obj.id || obj.name || '').trim()
  }
  return String(raw).trim()
}

function pickEndpoint(raw: RawGraphEdge, side: 'source' | 'target'): string {
  if (side === 'source') {
    return endpointId(
      raw.source ?? raw.source_id ?? raw.source_region_id ?? (raw as Record<string, unknown>).from,
    )
  }
  return endpointId(
    raw.target ?? raw.target_id ?? raw.target_region_id ?? (raw as Record<string, unknown>).to,
  )
}

function hashUnit(input: string): number {
  let h = 2166136261
  for (let i = 0; i < input.length; i += 1) {
    h ^= input.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return (h >>> 0) / 4294967296
}

function inferHemisphere(name: string): 'left' | 'right' | 'center' {
  const s = name.toLowerCase()
  if (/\bleft\b|_l\b|\(l\)|左/.test(s)) return 'left'
  if (/\bright\b|_r\b|\(r\)|右/.test(s)) return 'right'
  return 'center'
}

function shortLabel(text: string, max = 14): string {
  const t = text.trim()
  if (t.length <= max) return t
  return `${t.slice(0, max - 1)}…`
}

function displayName(node: RawGraphNode): { label: string; nameEn: string; nameCn: string; nameMissing: boolean } {
  const id = String(node.id || '').trim()
  const en = String(node.name_en || node.label || '').trim()
  const cn = String(node.name_cn || '').trim()
  const candidates = [en, cn, String(node.label || '').trim()].filter(Boolean)
  const primary = candidates.find(v => !UNKNOWN_LABELS.has(v)) || ''
  if (primary) {
    return { label: primary, nameEn: en || primary, nameCn: cn, nameMissing: false }
  }
  const fallback = id ? `${id.slice(0, 8)}…` : '未命名'
  return {
    label: `${fallback}（名称待补全）`,
    nameEn: en,
    nameCn: cn,
    nameMissing: true,
  }
}

function buildIndexes(nodes: NormalizedNode[], edges: NormalizedEdge[]): SymptomGraphIndexes {
  const nodeById = new Map(nodes.map(n => [n.id, n]))
  const edgesByNodeId = new Map<string, NormalizedEdge[]>()
  const circuitEdgesById = new Map<string, NormalizedEdge[]>()
  const circuitNodeIds = new Map<string, Set<string>>()

  for (const edge of edges) {
    for (const side of [edge.source, edge.target]) {
      const list = edgesByNodeId.get(side) || []
      list.push(edge)
      edgesByNodeId.set(side, list)
    }
    for (const cid of edge.circuitIds) {
      const elist = circuitEdgesById.get(cid) || []
      elist.push(edge)
      circuitEdgesById.set(cid, elist)
    }
  }

  for (const node of nodes) {
    for (const cid of node.circuitIds) {
      const set = circuitNodeIds.get(cid) || new Set<string>()
      set.add(node.id)
      circuitNodeIds.set(cid, set)
    }
  }

  return { nodeById, edgesByNodeId, circuitEdgesById, circuitNodeIds }
}

function assignParallelOffsets(edges: NormalizedEdge[]): NormalizedEdge[] {
  const groups = new Map<string, NormalizedEdge[]>()
  for (const edge of edges) {
    const key = [edge.source, edge.target].sort().join('|')
    const list = groups.get(key) || []
    list.push(edge)
    groups.set(key, list)
  }
  return edges.map(edge => {
    const key = [edge.source, edge.target].sort().join('|')
    const list = groups.get(key) || [edge]
    const idx = list.findIndex(e => e.id === edge.id)
    return { ...edge, parallelIndex: idx, parallelTotal: list.length }
  })
}

export function normalizeSymptomGraph(
  raw: RawGraphData | null | undefined,
  matchedCircuitIds: Set<string>,
): SymptomGraphModel {
  const stats: GraphNormalizeStats = {
    rawNodeCount: raw?.nodes?.length ?? 0,
    rawEdgeCount: raw?.edges?.length ?? 0,
    validEdgeCount: 0,
    invalidEndpointCount: 0,
    duplicateEdgeCount: 0,
    selfLoopCount: 0,
    missingNameCount: 0,
  }

  if (!raw) {
    return { nodes: [], edges: [], stats, indexes: buildIndexes([], []) }
  }

  const nodeMap = new Map<string, NormalizedNode>()
  for (const rawNode of raw.nodes) {
    const id = endpointId(rawNode.id)
    if (!id) continue
    const names = displayName(rawNode)
    if (names.nameMissing) stats.missingNameCount += 1
    const circuitIds = (rawNode.circuit_ids || [])
      .map(String)
      .filter(cid => matchedCircuitIds.has(cid))
    if (circuitIds.length === 0 && matchedCircuitIds.size > 0) continue

    nodeMap.set(id, {
      id,
      type: String(rawNode.type || 'brain_region'),
      label: names.label,
      shortLabel: shortLabel(names.label),
      nameEn: names.nameEn,
      nameCn: names.nameCn,
      nameMissing: names.nameMissing,
      circuitIds: [...new Set(circuitIds)],
      degree: 0,
      hemisphere: inferHemisphere(`${names.nameEn} ${names.nameCn} ${names.label}`),
    })
  }

  const seenEdgeKeys = new Set<string>()
  const validEdges: NormalizedEdge[] = []

  for (const rawEdge of raw.edges) {
    const source = pickEndpoint(rawEdge, 'source')
    const target = pickEndpoint(rawEdge, 'target')
    if (!source || !target) {
      stats.invalidEndpointCount += 1
      continue
    }
    if (source === target) {
      stats.selfLoopCount += 1
      continue
    }
    if (!nodeMap.has(source) || !nodeMap.has(target)) {
      stats.invalidEndpointCount += 1
      continue
    }

    const dedupeKey = `${source}|${target}|${rawEdge.type || 'unknown'}|${rawEdge.id}`
    if (seenEdgeKeys.has(dedupeKey)) {
      stats.duplicateEdgeCount += 1
      continue
    }
    seenEdgeKeys.add(dedupeKey)

    const circuitIds = (rawEdge.circuit_ids || [])
      .map(String)
      .filter(cid => matchedCircuitIds.has(cid))
    const type = String(rawEdge.type || 'unknown')
    const srcName = String(rawEdge.source_name || nodeMap.get(source)?.label || source)
    const tgtName = String(rawEdge.target_name || nodeMap.get(target)?.label || target)

    validEdges.push({
      id: String(rawEdge.id),
      source,
      target,
      type,
      label: String(rawEdge.label || `${srcName} → ${tgtName}`),
      confidence: Number(rawEdge.confidence ?? 0.3),
      circuitIds: [...new Set(circuitIds)],
      isStepFlow: type === 'step_flow' || String(rawEdge.id).startsWith('step-flow:'),
      isInvalid: type === 'invalid' || type === 'model_conflict',
      parallelIndex: 0,
      parallelTotal: 1,
    })
  }

  stats.validEdgeCount = validEdges.length
  const edges = assignParallelOffsets(validEdges)

  for (const edge of edges) {
    nodeMap.get(edge.source)!.degree += 1
    nodeMap.get(edge.target)!.degree += 1
  }

  const nodes = [...nodeMap.values()]
  const indexes = buildIndexes(nodes, edges)
  return { nodes, edges, stats, indexes }
}

/** Deterministic initial coordinates — stable across re-renders for same ids. */
export function stableNodePosition(
  node: NormalizedNode,
  width: number,
  height: number,
): { x: number; y: number } {
  const padX = 80
  const padY = 60
  const usableW = Math.max(width - padX * 2, 200)
  const usableH = Math.max(height - padY * 2, 200)
  const hx = hashUnit(node.id)
  const hy = hashUnit(`${node.id}:y`)
  const band =
    node.hemisphere === 'left' ? 0.25 :
    node.hemisphere === 'right' ? 0.75 :
    0.5
  const x = padX + usableW * (band * 0.55 + hx * 0.35)
  const y = padY + usableH * (0.15 + hy * 0.7)
  return { x, y }
}
