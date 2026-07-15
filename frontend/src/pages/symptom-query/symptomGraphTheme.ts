import type { LegendItem } from '../../components/ForceGraph'
import type { SymptomGraphTheme } from './symptomGraphTypes'

/** Single source of truth for symptom circuit graph visuals. */
export const SYMPTOM_GRAPH_THEME: SymptomGraphTheme = {
  nodeDefault: '#3b82f6',
  nodeSelected: '#1d4ed8',
  nodeCircuit: '#2563eb',
  nodeSelectedRing: '#93c5fd',
  edgeBackground: '#94a3b8',
  edgeCircuit: '#f97316',
  edgeCircuitActive: '#ea580c',
  edgeHover: '#64748b',
  error: '#ef4444',
  labelDefault: '#1e293b',
  labelMuted: '#94a3b8',
}

export const SYMPTOM_EDGE_DASH: Record<string, string> = {
  structural_connection: '',
  functional_connectivity: '6,4',
  projection: '2,3',
  association: '2,2',
  coactivation: '4,2',
  effective_connectivity: '6,3',
  uncertain_connection: '3,3',
  step_flow: '4,3',
  mapping: '2,4',
  unknown: '2,2',
}

export const SYMPTOM_GRAPH_LEGEND: LegendItem[] = [
  { color: SYMPTOM_GRAPH_THEME.nodeDefault, dash: '', label: '● 脑区节点' },
  { color: SYMPTOM_GRAPH_THEME.nodeSelected, dash: '', label: '● 选中脑区' },
  { color: SYMPTOM_GRAPH_THEME.edgeBackground, dash: '', label: '背景连接（浅灰蓝）' },
  { color: SYMPTOM_GRAPH_THEME.edgeCircuit, dash: '', label: '回路路径（橙色）' },
  { color: SYMPTOM_GRAPH_THEME.edgeCircuitActive, dash: '', label: '当前步骤（亮橙）' },
  { color: SYMPTOM_GRAPH_THEME.error, dash: '', label: '异常/冲突（红色）' },
  { color: SYMPTOM_GRAPH_THEME.edgeBackground, dash: '6,4', label: '功能连接（虚线）' },
  { color: SYMPTOM_GRAPH_THEME.edgeBackground, dash: '2,4', label: '映射关系（点线）' },
]

export function edgeDashForType(type: string): string {
  if (type === 'functional_connectivity' || type === 'coactivation') return SYMPTOM_EDGE_DASH.functional_connectivity
  if (type === 'mapping' || type === 'association') return SYMPTOM_EDGE_DASH.mapping
  if (type === 'projection') return SYMPTOM_EDGE_DASH.projection
  return SYMPTOM_EDGE_DASH[type] ?? SYMPTOM_EDGE_DASH.unknown
}

export function isErrorEdgeType(type: string): boolean {
  return type === 'model_conflict' || type === 'invalid' || type === 'human_rejected'
}
