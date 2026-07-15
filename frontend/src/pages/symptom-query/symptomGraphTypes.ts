export type SymptomDisplayMode = 'all_related' | 'step_focus' | 'region_focus'

export interface RawGraphNode {
  id: string
  type?: string
  label?: string
  name_en?: string
  name_cn?: string
  circuit_ids?: string[]
  [key: string]: unknown
}

export interface RawGraphEdge {
  id: string
  source?: string
  target?: string
  source_id?: string
  target_id?: string
  source_region_id?: string
  target_region_id?: string
  type?: string
  label?: string
  confidence?: number
  circuit_ids?: string[]
  source_name?: string
  target_name?: string
  strength?: string | number
  [key: string]: unknown
}

export interface RawGraphData {
  nodes: RawGraphNode[]
  edges: RawGraphEdge[]
}

export interface NormalizedNode {
  id: string
  type: string
  label: string
  shortLabel: string
  nameEn: string
  nameCn: string
  nameMissing: boolean
  circuitIds: string[]
  degree: number
  /** Stable layout bucket: left | right | center */
  hemisphere: 'left' | 'right' | 'center'
}

export interface NormalizedEdge {
  id: string
  source: string
  target: string
  type: string
  label: string
  confidence: number
  circuitIds: string[]
  isStepFlow: boolean
  isInvalid: boolean
  /** Parallel edge index for curve offset */
  parallelIndex: number
  parallelTotal: number
}

export interface GraphNormalizeStats {
  rawNodeCount: number
  rawEdgeCount: number
  validEdgeCount: number
  invalidEndpointCount: number
  duplicateEdgeCount: number
  selfLoopCount: number
  missingNameCount: number
}

export interface SymptomGraphIndexes {
  nodeById: Map<string, NormalizedNode>
  edgesByNodeId: Map<string, NormalizedEdge[]>
  circuitEdgesById: Map<string, NormalizedEdge[]>
  circuitNodeIds: Map<string, Set<string>>
}

export interface SymptomGraphModel {
  nodes: NormalizedNode[]
  edges: NormalizedEdge[]
  stats: GraphNormalizeStats
  indexes: SymptomGraphIndexes
}

export interface VisibilityResult {
  nodes: NormalizedNode[]
  edges: NormalizedEdge[]
  circuitPathEdgeIds: Set<string>
  activeStepEdgeIds: Set<string>
}

export interface SymptomGraphTheme {
  nodeDefault: string
  nodeSelected: string
  nodeCircuit: string
  nodeSelectedRing: string
  edgeBackground: string
  edgeCircuit: string
  edgeCircuitActive: string
  edgeHover: string
  error: string
  labelDefault: string
  labelMuted: string
}

export const BACKGROUND_EDGE_LIMIT_DEFAULT = 200
export const BACKGROUND_EDGE_LIMIT_MAX = 300
