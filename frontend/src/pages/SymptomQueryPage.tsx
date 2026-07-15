import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as d3 from 'd3'
import { PageHeader } from '../components/PageHeader'
import { useGlobalGranularity } from '../hooks/useGlobalGranularity'
import { useI18n } from '../i18n-context'
import { postJson } from '../api/client'

interface CircuitResult {
  id: string; circuit_name: string; circuit_type: string | null
  step_count: number; function_count: number; matched_functions: string[]; match_score: number
  steps: { id: string; step_order: number; step_name: string; step_type: string; role: string }[]
}
interface GraphData { nodes: { id: string; label: string; type: string }[]; edges: { id: string; source: string; target: string; label?: string }[] }

// ── D3 graph types ───────────────────────────────────────────────────────────
interface GNode { id: string; type: string; label: string }
interface GEdge { id: string; source: string; target: string; type: string; label: string }

const NODE_COLOR: Record<string, string> = { region: '#3b82f6', circuit: '#f59e0b' }
const NODE_R: Record<string, number> = { region: 7, circuit: 7 }
const EDGE_COLOR: Record<string, string> = { belongs_to: '#cbd5e1', connected_to: '#fbbf24', default: '#d1d5db' }
const EDGE_DASH: Record<string, string> = { belongs_to: '5,4', connected_to: '3,3' }

// ── Force Graph ──────────────────────────────────────────────────────────────

function ForceGraph({ nodes: _nodes, edges: _edges, focusNode, onNodeClick }: {
  nodes: GNode[]; edges: GEdge[]; focusNode: string | null; onNodeClick?: (id: string) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const {
  nodes, edges } = useMemo(() => {
    const nm = new Map<string, GNode>()
    for (const n of _nodes) nm.set(n.id, n)
    for (const e of _edges) {
      if (!nm.has(e.source)) nm.set(e.source, { id: e.source, type: 'region', label: e.source.slice(0, 12) })
      if (!nm.has(e.target)) nm.set(e.target, { id: e.target, type: 'region', label: e.target.slice(0, 12) })
    }
    const validEdges = _edges.filter(e => nm.has(e.source) && nm.has(e.target))
    return { nodes: [...nm.values()], edges: validEdges }
  }, [_nodes, _edges])

  useEffect(() => {
    const el = ref.current; if (!el || nodes.length === 0) return
    const W = el.clientWidth || 800; const H = el.clientHeight || 600
    d3.select(el).html('')
    setTimeout(() => {
      d3.select(el).html('')
      drawGraph(el, nodes, edges, W, H, focusNode, onNodeClick)
    }, 10)
    return () => {}
  }, [nodes.length, edges.length, focusNode])

  return <div ref={ref} style={{ width: '100%', height: '100%' }} />
}

function drawGraph(
  el: HTMLDivElement, nodes: GNode[], edges: GEdge[],
  W: number, H: number, focusNode: string | null, onNodeClick?: (id: string) => void,
) {
  d3.select(el).html('')
  const svg = d3.select(el).append('svg').attr('width', W).attr('height', H)
  const g = svg.append('g')
  svg.call(d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.1, 5]).on('zoom', (ev) => g.attr('transform', ev.transform)))

  const tip = d3.select(el).append('div').style('position', 'absolute').style('pointer-events', 'none')
    .style('background', '#1f2937').style('color', '#f9fafb').style('padding', '6px 10px')
    .style('border-radius', '6px').style('font-size', '11px').style('opacity', '0')
    .style('transition', 'opacity 0.15s').style('max-width', '300px').style('z-index', '100')

  nodes.forEach((n: any) => { n.x = W / 2 + (Math.random() - 0.5) * 200; n.y = H / 2 + (Math.random() - 0.5) * 200 })

  const link = g.append('g').selectAll('line').data(edges).join('line')
    .attr('stroke', (d: any) => EDGE_COLOR[d.type] || EDGE_COLOR.default)
    .attr('stroke-width', 1.5).attr('stroke-opacity', 0.4)
    .attr('stroke-dasharray', (d: any) => EDGE_DASH[d.type] || '')
    .on('mouseenter', (ev: any, d: any) => {
      tip.style('opacity', '1').html(`<strong>${d.type}</strong><br/>${d.label || ''}`)
    })
    .on('mousemove', (ev: any) => { tip.style('left', (ev.offsetX + 12) + 'px').style('top', (ev.offsetY - 10) + 'px') })
    .on('mouseleave', () => { tip.style('opacity', '0') })

  const isHL = (d: any) => !focusNode || d.id === focusNode

  const ng = g.append('g').selectAll('g').data(nodes).join('g')
    .attr('cursor', 'pointer')
    .on('click', (ev: any, d: any) => { ev.stopPropagation(); onNodeClick?.(d.id) })
    .on('mouseenter', (ev: any, d: any) => {
      tip.style('opacity', '1').html(`<strong>${d.type}</strong>: ${d.label}`)
    })
    .on('mousemove', (ev: any) => { tip.style('left', (ev.offsetX + 12) + 'px').style('top', (ev.offsetY - 10) + 'px') })
    .on('mouseleave', () => { tip.style('opacity', '0') })

  ng.append('circle')
    .attr('r', (d: any) => isHL(d) ? (focusNode ? 12 : NODE_R[d.type] || 6) : NODE_R[d.type] || 6)
    .attr('fill', (d: any) => isHL(d) ? (focusNode && d.id === focusNode ? '#ef4444' : NODE_COLOR[d.type] || '#999') : NODE_COLOR[d.type] || '#999')
    .attr('stroke', (d: any) => isHL(d) ? '#fff' : 'none').attr('stroke-width', 2).attr('opacity', 1)

  ng.append('text').text((d: any) => (d.label || '').slice(0, 12))
    .attr('dx', 10).attr('dy', 4).style('font-size', '7px').style('fill', '#374151').style('opacity', 1)

  const sim = d3.forceSimulation(nodes as any)
    .force('link', d3.forceLink(edges).id((d: any) => d.id).distance(140))
    .force('charge', d3.forceManyBody().strength(-500))
    .force('center', d3.forceCenter(W / 2, H / 2))
    .force('collision', d3.forceCollide(30))
    .on('tick', () => {
      link.attr('x1', (d: any) => d.source.x).attr('y1', (d: any) => d.source.y)
          .attr('x2', (d: any) => d.target.x).attr('y2', (d: any) => d.target.y)
      ng.attr('transform', (d: any) => `translate(${d.x},${d.y})`)
    })

  sim.alpha(1).restart()
  for (let i = 0; i < 300; i++) sim.tick()
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function SymptomQueryPage() {
  const { t } = useI18n(); const { granularity } = useGlobalGranularity()
  const [symptom, setSymptom] = useState(''); const [mode, setMode] = useState<'single' | 'multi'>('multi')
  const [loading, setLoading] = useState(false); const [error, setError] = useState<string | null>(null)
  const [stdFunctions, setStdFunctions] = useState<string[]>([]); const [circuits, setCircuits] = useState<CircuitResult[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [graph, setGraph] = useState<GraphData | null>(null)

  const handleQuery = useCallback(async () => {
    if (!symptom.trim()) return
    setLoading(true); setError(null); setStdFunctions([]); setCircuits([]); setSelectedId(null); setGraph(null)
    try {
      const ar = await postJson<{ functions: string[] }>('/api/symptom-query/analyze', { symptom: symptom.trim(), mode })
      const funcs = ar.functions || []; setStdFunctions(funcs)
      const er = await postJson<{ expanded: string[] }>('/api/symptom-query/expand', { functions: funcs })
      const sr = await postJson<{ circuits: CircuitResult[] }>('/api/symptom-query/search', { functions: er.expanded || funcs, granularity_level: granularity })
      const found = sr.circuits || []; setCircuits(found)
      if (found.length > 0) {
        const gr = await postJson<GraphData>('/api/symptom-query/graph', { circuit_ids: found.map(c => c.id), granularity_level: granularity })
        setGraph(gr)
      }
    } catch (e: any) { setError(e?.message || String(e)) } finally { setLoading(false) }
  }, [symptom, mode, granularity])

  const gNodes: GNode[] = useMemo(() => {
    if (!graph) return []
    return graph.nodes.map(n => ({ id: n.id, type: n.type, label: n.label }))
  }, [graph])

  const gEdges: GEdge[] = useMemo(() => {
    if (!graph) return []
    return graph.edges.map(e => ({ id: e.id, source: e.source, target: e.target, type: e.label || 'connected_to', label: e.label || '' }))
  }, [graph])

  const selectedCircuit = useMemo(() => circuits.find(c => c.id === selectedId), [circuits, selectedId])

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
          <button className="btn" onClick={() => { setSymptom(''); setCircuits([]); setStdFunctions([]); setError(null); setGraph(null); setSelectedId(null) }}>清空</button>
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
          {/* Left: circuit list */}
          <div style={{ width: 320, overflow: 'auto', flexShrink: 0 }}>
            <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 14 }}>匹配回路 ({circuits.length})</div>
            {circuits.map(c => (
              <div key={c.id} onClick={() => setSelectedId(selectedId === c.id ? null : c.id)}
                style={{ padding: 10, marginBottom: 8, cursor: 'pointer', borderRadius: 6,
                  borderLeft: `3px solid hsl(${Math.round(c.match_score * 240)},70%,${Math.round(30 + c.match_score * 40)}%)`,
                  background: selectedId === c.id ? '#fef3c7' : '#fff',
                  boxShadow: selectedId === c.id ? '0 0 0 2px #f59e0b' : '0 1px 3px rgba(0,0,0,0.06)' }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{c.circuit_name}</div>
                <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>{c.circuit_type || 'Unknown'} · {c.step_count} 步骤 · {c.function_count} 功能</div>
                <div style={{ fontSize: 11, color: '#f59e0b', marginTop: 4 }}>匹配 {(c.match_score * 100).toFixed(0)}%</div>
              </div>
            ))}
          </div>

          {/* Right: graph + detail sidebar */}
          <div style={{ flex: 1, minWidth: 0, display: 'flex', gap: 12 }}>
            <div style={{ flex: 1, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', background: '#f8fafc', minWidth: 0 }}>
              {graph ? <ForceGraph nodes={gNodes} edges={gEdges} focusNode={selectedId} onNodeClick={(id) => setSelectedId(selectedId === id ? null : id)} /> : null}
            </div>

            {/* Circuit detail sidebar */}
            {selectedCircuit && (
              <div style={{ width: 280, flexShrink: 0, overflow: 'auto', border: '1px solid var(--border)', borderRadius: 8, padding: 14, background: '#fff' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 14, color: '#1f2937' }}>{selectedCircuit.circuit_name}</div>
                    <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>{selectedCircuit.circuit_type || 'Unknown'} · 匹配 {(selectedCircuit.match_score * 100).toFixed(0)}%</div>
                  </div>
                  <button className="btn btn-sm" onClick={() => setSelectedId(null)} style={{ fontSize: 11 }}>✕</button>
                </div>

                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: '#6b7280', marginBottom: 4 }}>关联功能</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {selectedCircuit.matched_functions.map((f, i) => (
                      <span key={i} style={{ fontSize: 11, padding: '2px 6px', background: '#fef3c7', color: '#92400e', borderRadius: 4 }}>{f}</span>
                    ))}
                  </div>
                </div>

                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: '#6b7280', marginBottom: 4 }}>步骤 ({selectedCircuit.step_count})</div>
                  {selectedCircuit.steps.map((s, i) => (
                    <div key={s.id} style={{ fontSize: 11, padding: '3px 0', borderBottom: i < selectedCircuit.steps.length - 1 ? '1px solid #f3f4f6' : 'none', display: 'flex', justifyContent: 'space-between' }}>
                      <span>{s.step_order}. {s.step_name}</span>
                      <span style={{ color: '#888', fontSize: 10, textTransform: 'uppercase' }}>{s.role}</span>
                    </div>
                  ))}
                </div>

                {selectedCircuit.function_count > 0 && (
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 600, color: '#6b7280', marginBottom: 4 }}>统计</div>
                    <div style={{ fontSize: 11, color: '#555', lineHeight: 1.6 }}>
                      {selectedCircuit.step_count} 步骤 · {selectedCircuit.function_count} 功能 · {selectedCircuit.matched_functions.length} 匹配功能
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
      {!loading && circuits.length === 0 && stdFunctions.length > 0 && <div style={{ color: '#94a3b8', fontSize: 14, textAlign: 'center', padding: 40 }}>未找到匹配回路</div>}
    </div>
  )
}
