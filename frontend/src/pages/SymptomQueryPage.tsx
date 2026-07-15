import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { PageHeader } from '../components/PageHeader'
import { useGlobalGranularity } from '../hooks/useGlobalGranularity'
import { useI18n } from '../i18n-context'
import { postJson } from '../api/client'
import { ForceGraph, type GNode, type GEdge, type LegendItem } from '../components/ForceGraph'

interface CircuitResult {
  id: string; circuit_name: string; circuit_type: string | null
  step_count: number; function_count: number; matched_functions: string[]; match_score: number
  steps: { id: string; step_order: number; step_name: string; step_type: string; role: string }[]
}
interface GraphData { nodes: { id: string; label: string; type: string }[]; edges: { id: string; source: string; target: string; label?: string }[] }

// ── Custom color/dash/legend maps for symptom query ──────────────────────────
const SYMPTOM_EDGE_COLOR: Record<string, string> = {
  step_flow: '#10b981', belongs_to: '#d1d5db', co_occurs: '#8b5cf6',
}
const SYMPTOM_EDGE_DASH: Record<string, string> = {
  step_flow: '2,2', belongs_to: '', co_occurs: '6,3',
}
const SYMPTOM_NODE_COLOR: Record<string, string> = { brain_region: '#3b82f6', circuit: '#f59e0b' }
const SYMPTOM_NODE_R: Record<string, number> = { brain_region: 7, circuit: 7 }
const SYMPTOM_LEGEND: LegendItem[] = [
  { color: '#3b82f6', dash: '', label: '● 脑区 (Brain Region)' },
  { color: '#f59e0b', dash: '', label: '● 回路 (Circuit)' },
  { color: '#10b981', dash: '2,2', label: '┈ step_flow (步骤流向)' },
  { color: '#8b5cf6', dash: '6,3', label: '╌ co_occurs (共享脑区)' },
  { color: '#d1d5db', dash: '', label: '━ belongs_to (回路归属)' },
]

// ── Page ─────────────────────────────────────────────────────────────────────

export function SymptomQueryPage() {
  const { t } = useI18n(); const { granularity } = useGlobalGranularity()
  const [mode, setMode] = useState<'single' | 'multi'>('multi')
  const [error, setError] = useState<string | null>(null)
  const [stdFunctions, setStdFunctions] = useState<string[]>([]); const [circuits, setCircuits] = useState<CircuitResult[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [graph, setGraph] = useState<GraphData | null>(null)

  const [phase, setPhase] = useState<'idle'|'chatting'|'summarizing'|'analyzing'|'results'>('idle')
  const [messages, setMessages] = useState<{role:string;content:string}[]>([])
  const [summary, setSummary] = useState('')
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)

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
    } catch { /* keep chatLoading visible briefly */ }
    finally { setChatLoading(false) }
    setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
  }, [chatInput, messages, phase, granularity])

  const handleConfirm = useCallback(async () => {
    if (!summary.trim()) return
    setPhase('analyzing'); setError(null)
    try {
      const ar = await postJson<{functions:string[]}>('/api/symptom-query/analyze', { symptom: summary.trim(), mode })
      const funcs = ar.functions || []; setStdFunctions(funcs)
      const er = await postJson<{expanded:string[]}>('/api/symptom-query/expand', { functions: funcs })
      const sr = await postJson<{circuits:CircuitResult[]}>('/api/symptom-query/search', {
        functions: er.expanded || funcs, granularity_level: granularity,
      })
      const found = sr.circuits || []; setCircuits(found)
      if (found.length > 0) {
        const gr = await postJson<GraphData>('/api/symptom-query/graph', {
          circuit_ids: found.map(c => c.id), granularity_level: granularity,
        })
        setGraph(gr)
      }
      setPhase('results')
    } catch (e: any) { setError(e?.message || String(e)); setPhase('idle') }
  }, [summary, mode, granularity])

  const handleContinueChat = useCallback(() => { setPhase('chatting'); setSummary('') }, [])
  const handleClear = useCallback(() => {
    setPhase('idle'); setMessages([]); setSummary(''); setChatInput('')
    setStdFunctions([]); setCircuits([]); setError(null); setGraph(null); setSelectedId(null)
  }, [])

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
              <button className={`btn btn-sm ${mode === 'single' ? 'btn-primary' : ''}`} onClick={() => setMode('single')}>单功能</button>
              <button className={`btn btn-sm ${mode === 'multi' ? 'btn-primary' : ''}`} onClick={() => setMode('multi')}>多功能</button>
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
              {graph ? (
                <ForceGraph
                  nodes={gNodes} edges={gEdges}
                  focusNode={selectedId}
                  onNodeClick={(id) => setSelectedId(selectedId === id ? null : id)}
                  edgeColors={SYMPTOM_EDGE_COLOR} edgeDashes={SYMPTOM_EDGE_DASH}
                  nodeColors={SYMPTOM_NODE_COLOR} nodeRadii={SYMPTOM_NODE_R}
                  legendItems={SYMPTOM_LEGEND}
                />
              ) : null}
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
      {phase === 'results' && circuits.length === 0 && stdFunctions.length > 0 && <div style={{ color: '#94a3b8', fontSize: 14, textAlign: 'center', padding: 40 }}>未找到匹配回路</div>}
    </div>
  )
}
