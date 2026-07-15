import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { PageHeader } from '../components/PageHeader'
import { useGlobalGranularity } from '../hooks/useGlobalGranularity'
import { useI18n } from '../i18n-context'
import { postJson } from '../api/client'
import { ForceGraph, type GNode, type GEdge, type LegendItem } from '../components/ForceGraph'

interface CircuitResult {
  id: string; circuit_name: string; circuit_type: string | null
  step_count: number; function_count: number; matched_functions: string[]; match_score: number
  relevance: number; matched_categories: string[]
  steps: { id: string; step_order: number; step_name: string; step_type: string; role: string }[]
}
interface GraphNode { id: string; label: string; type: string; circuit_ids?: string[]; [key: string]: any }
interface GraphEdge { id: string; source: string; target: string; type: string; label?: string; circuit_ids?: string[]; confidence?: number }
interface GraphData { nodes: GraphNode[]; edges: GraphEdge[] }

// ── Match GraphExplorerPage legend — connection types only ───────────────────
const SYMPTOM_EDGE_COLOR: Record<string, string> = {
  structural_connection: '#3b82f6', functional_connectivity: '#f59e0b', projection: '#10b981',
  association: '#8b5cf6', coactivation: '#ec4899', effective_connectivity: '#ef4444',
  uncertain_connection: '#9ca3af', step_flow: '#10b981', unknown: '#d1d5db',
}
const SYMPTOM_EDGE_DASH: Record<string, string> = {
  structural_connection: '', functional_connectivity: '6,3', projection: '2,2',
  association: '', coactivation: '', effective_connectivity: '', uncertain_connection: '', step_flow: '2,2',
}
const SYMPTOM_NODE_COLOR: Record<string, string> = { brain_region: '#3b82f6' }
const SYMPTOM_NODE_R: Record<string, number> = { brain_region: 7 }
const SYMPTOM_LEGEND: LegendItem[] = [
  { color: '#3b82f6', dash: '', label: '● 脑区(Region)' },
  { color: '#3b82f6', dash: '', label: '结构连接' },
  { color: '#f59e0b', dash: '6,3', label: '功能连接' },
  { color: '#10b981', dash: '2,2', label: '投射' },
  { color: '#8b5cf6', dash: '', label: '关联' },
  { color: '#ec4899', dash: '', label: '共激活' },
  { color: '#ef4444', dash: '', label: '有效连接' },
  { color: '#9ca3af', dash: '', label: '不确定' },
  { color: '#10b981', dash: '2,2', label: '步骤推断连接' },
]

// ── Page ─────────────────────────────────────────────────────────────────────

export function SymptomQueryPage() {
  const { t } = useI18n(); const { granularity } = useGlobalGranularity()
  const [mode, setMode] = useState<'focused' | 'exploratory'>('focused')
  const [error, setError] = useState<string | null>(null)
  const [stdFunctions, setStdFunctions] = useState<string[]>([]); const [circuits, setCircuits] = useState<CircuitResult[]>([])
  const [selectedCircuitId, setSelectedCircuitId] = useState<string | null>(null)
  const [graph, setGraph] = useState<GraphData | null>(null)
  const [graphMode, setGraphMode] = useState<'all' | 'step'>('all')

  const [phase, setPhase] = useState<'idle'|'chatting'|'summarizing'|'analyzing'|'results'>('idle')
  const [messages, setMessages] = useState<{role:string;content:string}[]>([])
  const [summary, setSummary] = useState('')
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)
  const analysisRunRef = useRef(0)

  useEffect(() => () => { analysisRunRef.current += 1 }, [])

  const handleSend = useCallback(async () => {
    const text = chatInput.trim(); if (!text) return
    setChatInput('')
    const newMessages = [...messages, { role: 'user', content: text }]
    setMessages(newMessages)
    if (phase === 'idle') setPhase('chatting')
    setChatLoading(true)
    try {
      const resp = await postJson<{stage:string;content:string|null;summary:string|null}>(
        '/api/symptom-query/conversation',
        { messages: newMessages, granularity_level: granularity },
      )
      if (resp.stage === 'asking' && resp.content) {
        setMessages([...newMessages, { role: 'assistant', content: resp.content }])
      } else if (resp.stage === 'summarizing' && resp.summary) {
        setMessages([...newMessages, { role: 'assistant', content: '我已收集足够信息。请查看下方的症状总结，确认后开始分析。' }])
        setSummary(resp.summary)
        setPhase('summarizing')
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '发送失败，请重试')
    }
    finally { setChatLoading(false) }
    setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
  }, [chatInput, messages, phase, granularity])

  const handleConfirm = useCallback(async () => {
    if (!summary.trim()) return
    const runId = analysisRunRef.current + 1
    analysisRunRef.current = runId
    setPhase('analyzing'); setError(null); setGraph(null); setSelectedCircuitId(null)
    setCircuits([]); setStdFunctions([])
    try {
      const ar = await postJson<{functions:string[];categories:string[];primary_category:string}>('/api/symptom-query/analyze', { symptom: summary.trim(), mode })
      if (analysisRunRef.current !== runId) return
      const funcs = ar.functions || []; const cats = ar.categories || []
      setStdFunctions(funcs)
      const er = await postJson<{expanded:string[]}>('/api/symptom-query/expand', { functions: funcs })
      if (analysisRunRef.current !== runId) return
      // Combine expanded terms + original functions for maximum coverage
      const allFuncs = [...new Set([...(er.expanded || []), ...funcs])]
      const sr = await postJson<{circuits:CircuitResult[]}>('/api/symptom-query/search', {
        functions: allFuncs, categories: cats, mode, granularity_level: granularity,
      })
      if (analysisRunRef.current !== runId) return
      const found = sr.circuits || []; setCircuits(found)
      if (found.length > 0) {
        const gr = await postJson<GraphData>('/api/symptom-query/graph', {
          circuit_ids: found.map(c => c.id), granularity_level: granularity,
        })
        if (analysisRunRef.current !== runId) return
        setGraph(gr)
      } else {
        setGraph(null)
      }
      setPhase('results')
    } catch (e: any) {
      if (analysisRunRef.current !== runId) return
      setError(e?.message || String(e)); setPhase('idle')
    }
  }, [summary, mode, granularity])

  const handleContinueChat = useCallback(() => { setPhase('chatting'); setSummary('') }, [])
  const handleClear = useCallback(() => {
    analysisRunRef.current += 1
    setPhase('idle'); setMessages([]); setSummary(''); setChatInput('')
    setStdFunctions([]); setCircuits([]); setError(null); setGraph(null); setSelectedCircuitId(null)
  }, [])

  const matchedCircuitIds = useMemo(
    () => new Set(circuits.map(circuit => circuit.id)),
    [circuits],
  )
  const scopedNodeIds = useMemo(() => {
    if (!graph) return new Set<string>()
    return new Set(
      graph.nodes
        .filter(node => (node.circuit_ids || []).some(id => matchedCircuitIds.has(id)))
        .map(node => node.id),
    )
  }, [graph, matchedCircuitIds])

  const gNodes: GNode[] = useMemo(() => {
    if (!graph) return []
    return graph.nodes
      .filter(node => scopedNodeIds.has(node.id))
      .map(node => ({ ...node, circuit_ids: node.circuit_ids || [] }))
  }, [graph, scopedNodeIds])

  const gEdges: GEdge[] = useMemo(() => {
    if (!graph) return []
    // Defense in depth: never render edges outside the function-matched circuits,
    // even if an old or malformed backend response contains global graph data.
    return graph.edges
      .filter(edge =>
        (edge.circuit_ids || []).some(id => matchedCircuitIds.has(id))
        && scopedNodeIds.has(edge.source)
        && scopedNodeIds.has(edge.target),
      )
      .map(e => ({
        ...e,
        id: e.id,
        source: e.source,
        target: e.target,
        type: e.type || 'unknown',
        label: e.label || `${(e as any).source_name || e.source} → ${(e as any).target_name || e.target}`,
        circuit_ids: e.circuit_ids || [],
        confidence: e.confidence,
      }))
  }, [graph, matchedCircuitIds, scopedNodeIds])

  // Compute highlight sets when a circuit is selected
  const hlNodeIds = useMemo(() => {
    if (!selectedCircuitId) return undefined
    return new Set(gNodes.filter(n => ((n as any).circuit_ids || []).includes(selectedCircuitId)).map(n => n.id))
  }, [gNodes, selectedCircuitId])
  const hlEdgeIds = useMemo(() => {
    if (!selectedCircuitId) return undefined
    return new Set(gEdges.filter(e => ((e as any).circuit_ids || []).includes(selectedCircuitId)).map(e => e.id))
  }, [gEdges, selectedCircuitId])

  // Step-mode: only show nodes/edges belonging to the selected circuit
  const stepNodes = useMemo(() => {
    if (!selectedCircuitId) return gNodes
    return gNodes.filter(n => ((n as any).circuit_ids || []).includes(selectedCircuitId))
  }, [gNodes, selectedCircuitId])
  const stepEdges = useMemo(() => {
    if (!selectedCircuitId) return gEdges
    return gEdges.filter(e => ((e as any).circuit_ids || []).includes(selectedCircuitId))
  }, [gEdges, selectedCircuitId])

  const displayNodes = graphMode === 'step' ? stepNodes : gNodes
  const displayEdges = graphMode === 'step' ? stepEdges : gEdges

  const selectedCircuit = useMemo(
    () => circuits.find(c => c.id === selectedCircuitId),
    [circuits, selectedCircuitId],
  )

  return (
    <div className="page">
      <PageHeader title="症状回路查询" description="输入症状，AI 转化为标准功能并检索关联回路" readonly />
      <div className="card" style={{ padding: 16, marginBottom: 16 }}>
        {phase !== 'results' && (
          <>
            {messages.length > 0 && (
              <div style={{ maxHeight: 280, overflow: 'auto', marginBottom: 12 }}>
                {messages.map((m, i) => (
                  <div key={i} style={{
                    display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start', marginBottom: 8,
                  }}>
                    <div style={{
                      maxWidth: '75%', padding: '8px 12px', borderRadius: 12, fontSize: 13,
                      background: m.role === 'user' ? '#eef4ff' : '#f3f4f6',
                      color: m.role === 'user' ? '#1e40af' : '#374151',
                      whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                    }}>{m.content}</div>
                  </div>
                ))}
                <div ref={chatEndRef} />
              </div>
            )}
            {phase === 'summarizing' && (
              <div style={{ background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: 8, padding: 12, marginBottom: 12 }}>
                <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6, color: '#92400e' }}>AI 症状分析总结</div>
                <textarea className="form-input" value={summary} onChange={e => setSummary(e.target.value)}
                  style={{ width: '100%', minHeight: 80, fontSize: 12, marginBottom: 8 }} />
                <div style={{ display: 'flex', gap: 8 }}>
                  <button className="btn btn-primary btn-sm" onClick={handleConfirm}>确认并开始分析</button>
                  <button className="btn btn-sm" onClick={handleContinueChat}>继续对话</button>
                </div>
              </div>
            )}
            {phase !== 'summarizing' && (
              <div style={{ display: 'flex', gap: 8 }}>
                <input className="form-input" style={{ flex: 1 }}
                  placeholder={messages.length === 0 ? '描述你的症状，如：头晕眼花走路不稳…' : '输入回复…'}
                  value={chatInput} onChange={e => setChatInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleSend()}
                  disabled={chatLoading || phase === 'analyzing'} />
                <button className="btn btn-primary" onClick={handleSend} disabled={chatLoading || !chatInput.trim()}>
                  {chatLoading ? '…' : '发送'}
                </button>
                {messages.length > 0 && <button className="btn" onClick={handleClear}>清空</button>}
              </div>
            )}
          </>
        )}
        {phase === 'analyzing' && (
          <div style={{ textAlign: 'center', padding: 20, color: '#888', fontSize: 14 }}>
            正在分析症状并检索回路…
          </div>
        )}
        {phase === 'results' && (
          <details style={{ fontSize: 12, color: '#888' }}>
            <summary>重新查询</summary>
            <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
              <button className={`btn btn-sm ${mode === 'focused' ? 'btn-primary' : ''}`} onClick={() => setMode('focused')}>🎯 聚焦</button>
              <button className={`btn btn-sm ${mode === 'exploratory' ? 'btn-primary' : ''}`} onClick={() => setMode('exploratory')}>🔍 探索</button>
              <button className="btn btn-sm" onClick={handleClear}>新查询</button>
            </div>
          </details>
        )}
        {error && <div style={{ color: '#cf1322', marginTop: 8, fontSize: 13 }}>{error}</div>}
      </div>
      {stdFunctions.length > 0 && (
        <div style={{ marginBottom: 12, fontSize: 13, color: '#64748b' }}>
          标准化功能: {stdFunctions.map((f, i) => (
            <span key={i} style={{ display: 'inline-block', marginRight: 6, padding: '2px 8px', background: '#eef4ff', color: '#2563eb', borderRadius: 4, fontSize: 12 }}>{f}</span>
          ))}
        </div>
      )}
      {phase === 'results' && circuits.length > 0 && (
        <div style={{ display: 'flex', gap: 16, height: 'calc(100vh - 280px)' }}>
          {/* Left: circuit list */}
          <div style={{ width: 320, overflow: 'auto', flexShrink: 0 }}>
            <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 14 }}>匹配回路 ({circuits.length})</div>
            {circuits.map(c => (
              <button type="button" key={c.id} aria-pressed={selectedCircuitId === c.id}
                onClick={() => setSelectedCircuitId(selectedCircuitId === c.id ? null : c.id)}
                style={{ display: 'block', width: '100%', textAlign: 'left', font: 'inherit', padding: 10, marginBottom: 8, cursor: 'pointer', border: 0, borderRadius: 6,
                  borderLeft: `3px solid hsl(${Math.round(c.match_score * 240)},70%,${Math.round(30 + c.match_score * 40)}%)`,
                  background: selectedCircuitId === c.id ? '#fef3c7' : '#fff',
                  boxShadow: selectedCircuitId === c.id ? '0 0 0 2px #f59e0b' : '0 1px 3px rgba(0,0,0,0.06)' }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{c.circuit_name}</div>
                <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>{c.circuit_type || 'Unknown'} · {c.step_count}步 · {c.function_count}功能</div>
                <div style={{ fontSize: 11, marginTop: 4, display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span style={{ color: '#f59e0b', fontWeight: 600 }}>{(c.relevance || c.match_score * 100).toFixed(0)}分</span>
                  {(c.matched_categories || []).slice(0, 2).map(cat => (
                    <span key={cat} style={{ fontSize: 10, padding: '1px 6px', background: '#eef4ff', color: '#2563eb', borderRadius: 3 }}>{cat}</span>
                  ))}
                </div>
              </button>
            ))}
          </div>

          {/* Right: graph + detail sidebar */}
          <div style={{ flex: 1, minWidth: 0, display: 'flex', gap: 12 }}>
            <div style={{ flex: 1, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', background: '#f8fafc', minWidth: 0, display: 'flex', flexDirection: 'column' }}>
              <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)', fontSize: 11, color: '#64748b', display: 'flex', justifyContent: 'space-between' }}>
                <span>脑区 {displayNodes.length} · 连接 {displayEdges.length}</span>
                <button className={`btn btn-sm ${graphMode === 'all' ? 'btn-primary' : ''}`} onClick={() => setGraphMode('all')}>全部相关</button>
                <button className={`btn btn-sm ${graphMode === 'step' ? 'btn-primary' : ''}`} onClick={() => setGraphMode('step')} disabled={!selectedCircuitId}>步骤聚焦</button>
                {selectedCircuit && <span>已高亮：{selectedCircuit.circuit_name}</span>}
              </div>
              {graph && gNodes.length > 0 ? (
                <>
                  <div style={{ flex: 1, minHeight: 0 }}>
                    <ForceGraph
                      nodes={displayNodes} edges={displayEdges}
                      focusNode={null}
                      highlightedNodeIds={hlNodeIds}
                      highlightedEdgeIds={hlEdgeIds}
                      edgeColors={SYMPTOM_EDGE_COLOR} edgeDashes={SYMPTOM_EDGE_DASH}
                      nodeColors={SYMPTOM_NODE_COLOR} nodeRadii={SYMPTOM_NODE_R}
                      legendItems={SYMPTOM_LEGEND}
                    />
                  </div>
                  {selectedCircuit && (hlEdgeIds?.size || 0) === 0 && (
                    <div style={{ padding: '6px 12px', color: '#92400e', background: '#fffbeb', fontSize: 11 }}>
                      该回路暂无可连接的已解析步骤，仅高亮相关脑区。
                    </div>
                  )}
                </>
              ) : (
                <div style={{ flex: 1, display: 'grid', placeItems: 'center', color: '#94a3b8', fontSize: 13 }}>
                  匹配回路暂无已解析的脑区图数据
                </div>
              )}
            </div>

            {/* Circuit detail sidebar */}
            {selectedCircuit && (
              <div style={{ width: 280, flexShrink: 0, overflow: 'auto', border: '1px solid var(--border)', borderRadius: 8, padding: 14, background: '#fff' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 14, color: '#1f2937' }}>{selectedCircuit.circuit_name}</div>
                    <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>{selectedCircuit.circuit_type || 'Unknown'} · 匹配 {(selectedCircuit.match_score * 100).toFixed(0)}%</div>
                  </div>
                  <button className="btn btn-sm" onClick={() => setSelectedCircuitId(null)} style={{ fontSize: 11 }}>✕</button>
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
      {phase === 'results' && circuits.length === 0 && stdFunctions.length > 0 && <div style={{ color: '#94a3b8', fontSize: 14, textAlign: 'center', padding: 40 }}>未找到匹配回路</div>}
    </div>
  )
}
