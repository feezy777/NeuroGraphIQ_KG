import { useState, useCallback, useMemo } from 'react'
import { PageHeader } from '../components/PageHeader'
import { useGlobalGranularity } from '../hooks/useGlobalGranularity'
import { useI18n } from '../i18n-context'
import { postJson } from '../api/client'
import {
  ReactFlow, Background, Controls, Handle, Position,
  useNodesState, useEdgesState, MarkerType, BaseEdge, getStraightPath,
  type Node, type Edge, type NodeProps, type EdgeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

interface CircuitResult {
  id: string; circuit_name: string; circuit_type: string | null
  step_count: number; function_count: number; matched_functions: string[]; match_score: number
  steps: { id: string; step_order: number; step_name: string; step_type: string; role: string }[]
}
interface GraphData { nodes: { id: string; label: string; type: string }[]; edges: { id: string; source: string; target: string; label?: string }[] }

// ── Custom node components ─────────────────────────────────────────────────

function CircuitNode({ data }: NodeProps) {
  const label = (data.label as string) || ''
  const isHL = data.isHighlighted as boolean
  return (
    <div style={{
      padding: '6px 12px', borderRadius: 8, fontSize: 12, fontWeight: 600,
      background: isHL ? '#8b5cf6' : '#e9d5ff', color: isHL ? '#fff' : '#6b21a8',
      border: `2px solid ${isHL ? '#6d28d9' : '#c4b5fd'}`, opacity: data.opacity || 1,
      maxWidth: 180, textAlign: 'center', cursor: 'pointer',
    }}>
      <Handle type="target" position={Position.Top} style={{ background: '#8b5cf6' }} />
      <Handle type="source" position={Position.Bottom} style={{ background: '#8b5cf6' }} />
      {label.slice(0, 40)}
    </div>
  )
}

function RegionNode({ data }: NodeProps) {
  const label = (data.label as string) || ''
  const isHL = data.isHighlighted as boolean
  return (
    <div style={{
      padding: '4px 10px', borderRadius: 20, fontSize: 11,
      background: isHL ? '#3b82f6' : '#dbeafe', color: isHL ? '#fff' : '#1e40af',
      border: `1px solid ${isHL ? '#2563eb' : '#93c5fd'}`, opacity: data.opacity || 1,
      maxWidth: 140, textAlign: 'center', cursor: 'pointer',
    }}>
      <Handle type="target" position={Position.Top} style={{ background: '#3b82f6' }} />
      <Handle type="source" position={Position.Bottom} style={{ background: '#3b82f6' }} />
      {label.slice(0, 28)}
    </div>
  )
}

function SymptomEdge({ id, sourceX, sourceY, targetX, targetY, data }: EdgeProps) {
  const [edgePath] = getStraightPath({ sourceX, sourceY, targetX, targetY })
  const isCircuit = data?.label === 'belongs_to'
  const dash = isCircuit ? '5,4' : '3,3'
  const color = isCircuit ? '#cbd5e1' : '#fbbf24'
  return <BaseEdge id={id} path={edgePath} style={{ stroke: color, strokeDasharray: dash, strokeWidth: 1.5, opacity: (data?.opacity as number) || 0.5 }} />
}

const nodeTypes = { circuit: CircuitNode, brain_region: RegionNode }
const edgeTypes = { symptom: SymptomEdge }

// ── Page ───────────────────────────────────────────────────────────────────

export function SymptomQueryPage() {
  const { t } = useI18n(); const { granularity } = useGlobalGranularity()
  const [symptom, setSymptom] = useState(''); const [mode, setMode] = useState<'single' | 'multi'>('multi')
  const [loading, setLoading] = useState(false); const [error, setError] = useState<string | null>(null)
  const [stdFunctions, setStdFunctions] = useState<string[]>([]); const [circuits, setCircuits] = useState<CircuitResult[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [graphNodes, setGraphNodes] = useNodesState<Node>([])
  const [graphEdges, setGraphEdges] = useEdgesState<Edge>([])

  const handleQuery = useCallback(async () => {
    if (!symptom.trim()) return
    setLoading(true); setError(null); setStdFunctions([]); setCircuits([]); setSelectedId(null)
    try {
      const ar = await postJson<{ functions: string[] }>('/api/symptom-query/analyze', { symptom: symptom.trim(), mode })
      const funcs = ar.functions || []; setStdFunctions(funcs)
      const er = await postJson<{ expanded: string[] }>('/api/symptom-query/expand', { functions: funcs })
      const sr = await postJson<{ circuits: CircuitResult[] }>('/api/symptom-query/search', { functions: er.expanded || funcs, granularity_level: granularity })
      const found = sr.circuits || []; setCircuits(found)
      if (found.length > 0) {
        const gr = await postJson<GraphData>('/api/symptom-query/graph', { circuit_ids: found.map(c => c.id), granularity_level: granularity })
        buildFlow(gr, null)
      }
    } catch (e: any) { setError(e?.message || String(e)) } finally { setLoading(false) }
  }, [symptom, mode, granularity])

  const buildFlow = useCallback((graph: GraphData, selId: string | null) => {
    const nodes: Node[] = graph.nodes.map((n, i) => ({
      id: n.id, type: n.type === 'circuit' ? 'circuit' : 'brain_region',
      position: { x: (i % 4) * 220 + 50, y: Math.floor(i / 4) * 120 + 50 },
      data: { label: n.label, isHighlighted: !selId || n.id === selId, opacity: selId && n.id !== selId ? 0.15 : 1 },
    }))
    const edges: Edge[] = graph.edges.map(e => ({
      id: e.id, source: e.source, target: e.target, type: 'symptom',
      data: { label: e.label, opacity: selId ? ((e.source === selId || e.target === selId) ? 0.8 : 0.06) : 0.5 },
    }))
    setGraphNodes(nodes); setGraphEdges(edges)
  }, [setGraphNodes, setGraphEdges])

  // Rebuild flow when selectedId changes
  const handleSelect = useCallback((cid: string) => {
    setSelectedId(cid)
    // Rebuild with highlight
    setGraphNodes(nds => nds.map(n => ({
      ...n, data: { ...n.data, isHighlighted: n.id === cid, opacity: n.id === cid ? 1 : 0.15 },
    })))
    setGraphEdges(eds => eds.map(e => ({
      ...e, data: { ...e.data, opacity: (e.source === cid || e.target === cid) ? 0.8 : 0.06 },
    })))
  }, [setGraphNodes, setGraphEdges])

  return (
    <div className="page">
      <PageHeader title="症状回路查询" description="输入症状，AI 转化为标准功能并检索关联回路" readonly />
      <div className="card" style={{ padding: 16, marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <button className={`btn btn-sm ${mode === 'single' ? 'btn-primary' : ''}`} onClick={() => setMode('single')}>单功能</button>
          <button className={`btn btn-sm ${mode === 'multi' ? 'btn-primary' : ''}`} onClick={() => setMode('multi')}>多功能</button>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <input className="form-input" style={{ flex: 1 }} placeholder="描述症状，如：头晕眼花走路不稳" value={symptom} onChange={e => setSymptom(e.target.value)} onKeyDown={e => e.key === 'Enter' && handleQuery()} />
          <button className="btn btn-primary" onClick={handleQuery} disabled={loading || !symptom.trim()}>{loading ? '分析中...' : '查询'}</button>
          <button className="btn" onClick={() => { setSymptom(''); setCircuits([]); setStdFunctions([]); setError(null); setGraphNodes([]); setGraphEdges([]) }}>清空</button>
        </div>
        {error && <div style={{ color: '#cf1322', marginTop: 8, fontSize: 13 }}>{error}</div>}
      </div>
      {stdFunctions.length > 0 && (
        <div style={{ marginBottom: 12, fontSize: 13, color: '#64748b' }}>
          标准化功能: {stdFunctions.map((f, i) => (
            <span key={i} style={{ display: 'inline-block', marginRight: 6, padding: '2px 8px', background: '#eef4ff', color: '#2563eb', borderRadius: 4, fontSize: 12 }}>{f}</span>
          ))}
        </div>
      )}
      {circuits.length > 0 && (
        <div style={{ display: 'flex', gap: 16, height: 'calc(100vh - 280px)' }}>
          <div style={{ width: 360, overflow: 'auto', flexShrink: 0 }}>
            <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 14 }}>匹配回路 ({circuits.length})</div>
            {circuits.map(c => (
              <div key={c.id} onClick={() => handleSelect(c.id)}
                style={{ padding: 10, marginBottom: 8, cursor: 'pointer', borderRadius: 6,
                  opacity: 0.3 + c.match_score * 0.7,
                  borderLeft: `3px solid hsl(${Math.round(c.match_score * 240)},70%,${Math.round(30 + c.match_score * 40)}%)`,
                  background: selectedId === c.id ? '#f0f5ff' : '#fff',
                  boxShadow: selectedId === c.id ? '0 0 0 1px #2563eb' : '0 1px 3px rgba(0,0,0,0.06)' }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{c.circuit_name}</div>
                <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>{c.circuit_type || 'Unknown'} · {c.step_count} 步骤</div>
                <div style={{ fontSize: 11, color: '#2563eb', marginTop: 4 }}>{(c.match_score * 100).toFixed(0)}% 影响</div>
              </div>
            ))}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <ReactFlow nodes={graphNodes} edges={graphEdges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} fitView>
              <Background />
              <Controls />
            </ReactFlow>
          </div>
        </div>
      )}
      {!loading && circuits.length === 0 && stdFunctions.length > 0 && <div style={{ color: '#94a3b8', fontSize: 14, textAlign: 'center', padding: 40 }}>未找到匹配回路</div>}
    </div>
  )
}
