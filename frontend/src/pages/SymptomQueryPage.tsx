import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { PageHeader } from '../components/PageHeader'
import { useGlobalGranularity } from '../hooks/useGlobalGranularity'
import { useI18n } from '../i18n-context'
import { postJson } from '../api/client'
import { SymptomCircuitGraph } from './symptom-query/SymptomCircuitGraph'
import { normalizeSymptomGraph } from './symptom-query/normalizeSymptomGraph'
import type { NormalizedEdge, RawGraphData } from './symptom-query/symptomGraphTypes'

interface CircuitResult {
  id: string; circuit_name: string; circuit_type: string | null
  description?: string | null
  step_count: number; function_count: number; matched_functions: string[]; match_score: number
  relevance: number; matched_categories: string[]
  steps: { id: string; step_order: number; step_name: string; step_type: string; role: string }[]
  function_descriptions?: Record<string, string>
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function SymptomQueryPage() {
  const { t } = useI18n(); const { granularity } = useGlobalGranularity()
  const [mode, setMode] = useState<'focused' | 'exploratory'>('focused')
  const [error, setError] = useState<string | null>(null)
  const [stdFunctions, setStdFunctions] = useState<string[]>([]); const [circuits, setCircuits] = useState<CircuitResult[]>([])
  const [selectedCircuitId, setSelectedCircuitId] = useState<string | null>(null)
  const [graph, setGraph] = useState<RawGraphData | null>(null)
  const [selectedStepIndex, setSelectedStepIndex] = useState<number | null>(null)
  const [selectedGraphEdge, setSelectedGraphEdge] = useState<NormalizedEdge | null>(null)

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
    setPhase('analyzing'); setError(null); setGraph(null); setSelectedCircuitId(null); setSelectedStepIndex(null); setSelectedGraphEdge(null)
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
        const gr = await postJson<RawGraphData>('/api/symptom-query/graph', {
          circuit_ids: found.map(c => c.id), granularity_level: granularity,
        })
        if (analysisRunRef.current !== runId) return
        setGraph(gr)
        // Default to a single matched circuit so the first render remains
        // bounded instead of showing every query-related relationship.
        setSelectedCircuitId(found[0].id)
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
    setStdFunctions([]); setCircuits([]); setError(null); setGraph(null); setSelectedCircuitId(null); setSelectedStepIndex(null); setSelectedGraphEdge(null)
  }, [])

  const matchedCircuitIds = useMemo(
    () => new Set(circuits.map(circuit => circuit.id)),
    [circuits],
  )
  const graphModel = useMemo(
    () => normalizeSymptomGraph(graph, matchedCircuitIds),
    [graph, matchedCircuitIds],
  )

  const selectedCircuit = useMemo(
    () => circuits.find(c => c.id === selectedCircuitId),
    [circuits, selectedCircuitId],
  )

  return (
    <div className="page">
      <PageHeader title="症状回路查询" description="输入症状，AI 转化为标准功能并检索关联回路" readonly />
      <div className="card" style={{ padding: 16, marginBottom: 16 }}>
        {(phase === 'idle' || phase === 'chatting') && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
            <span style={{ fontSize: 12, color: '#888', lineHeight: '24px' }}>模式：</span>
            <button className={`btn btn-sm ${mode === 'focused' ? 'btn-primary' : ''}`} onClick={() => setMode('focused')}>🎯 聚焦</button>
            <button className={`btn btn-sm ${mode === 'exploratory' ? 'btn-primary' : ''}`} onClick={() => setMode('exploratory')}>🔍 探索</button>
          </div>
        )}
        {phase !== 'results' && (
          <>
            {messages.length > 0 && (
              <div style={{ maxHeight: 420, overflow: 'auto', marginBottom: 16 }}>
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
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 260px) minmax(420px, 1fr) minmax(220px, 250px)', gap: 12, height: 'calc(100vh - 250px)', minHeight: 560 }}>
          {/* Left: circuit list */}
          <div style={{ overflow: 'auto', minWidth: 0 }}>
            <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 14 }}>匹配回路 ({circuits.length})</div>
            {circuits.map(c => (
              <button type="button" key={c.id} aria-pressed={selectedCircuitId === c.id}
                onClick={() => {
                  setSelectedCircuitId(selectedCircuitId === c.id ? null : c.id)
                  setSelectedStepIndex(null)
                  setSelectedGraphEdge(null)
                }}
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

          <div style={{ minWidth: 0, minHeight: 0 }}>
            <SymptomCircuitGraph
              model={graphModel}
              selectedCircuit={selectedCircuit || null}
              selectedCircuitId={selectedCircuitId}
              selectedStepIndex={selectedStepIndex}
              onSelectedStepIndexChange={setSelectedStepIndex}
              onEdgeSelect={setSelectedGraphEdge}
            />
          </div>

          {/* Circuit detail sidebar */}
          <div style={{ minWidth: 0, overflow: 'auto', border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
            {selectedCircuit ? (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 14, color: '#1f2937' }}>{selectedCircuit.circuit_name}</div>
                    <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>{selectedCircuit.circuit_type || 'Unknown'} · 匹配 {(selectedCircuit.match_score * 100).toFixed(0)}%</div>
                  </div>
                  <button className="btn btn-sm" onClick={() => { setSelectedCircuitId(null); setSelectedStepIndex(null) }} style={{ fontSize: 11 }}>✕</button>
                </div>

                <div style={{ marginBottom: 12 }}>
                  {/* Circuit overview */}
                  {selectedCircuit.description && (
                    <div style={{ marginBottom: 12, padding: 8, background: '#f8fafc', borderRadius: 6, fontSize: 11, color: '#475569', lineHeight: 1.5 }}>
                      {selectedCircuit.description}
                    </div>
                  )}
                  {selectedCircuit.function_count > 0 && (
                    <div style={{ marginBottom: 12, fontSize: 11, color: '#555' }}>
                      {selectedCircuit.step_count} 步骤 · {selectedCircuit.function_count} 功能 · {selectedCircuit.matched_functions.length} 匹配
                    </div>
                  )}
                  <div style={{ fontSize: 11, fontWeight: 600, color: '#6b7280', marginBottom: 4 }}>关联功能</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {selectedCircuit.matched_functions.map((f, i) => {
                      const desc = selectedCircuit.function_descriptions?.[f]
                      return (
                        <span key={i} title={desc || f}
                          style={{ fontSize: 11, padding: '2px 6px', background: '#fef3c7', color: '#92400e', borderRadius: 4, cursor: 'help' }}>
                          {f}
                        </span>
                      )
                    })}
                  </div>
                </div>

                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: '#6b7280', marginBottom: 4 }}>步骤 ({selectedCircuit.step_count})</div>
                  {selectedCircuit.steps.map((s, i) => (
                    <button type="button" key={s.id} onClick={() => setSelectedStepIndex(i)}
                      style={{ width: '100%', border: 0, background: selectedStepIndex === i ? '#fff7ed' : 'transparent', color: 'inherit', cursor: 'pointer', textAlign: 'left', fontSize: 11, padding: '5px 3px', borderBottom: i < selectedCircuit.steps.length - 1 ? '1px solid #f3f4f6' : 'none', display: 'flex', justifyContent: 'space-between' }}>
                      <span>{s.step_order}. {s.step_name}</span>
                      <span style={{ color: '#888', fontSize: 10, textTransform: 'uppercase' }}>{s.role}</span>
                    </button>
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
                {selectedGraphEdge && (
                  <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid #e2e8f0' }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: '#6b7280', marginBottom: 5 }}>当前连接</div>
                    <div style={{ fontSize: 11, color: '#334155', lineHeight: 1.7, wordBreak: 'break-word' }}>
                      <div>{selectedGraphEdge.label}</div>
                      <div>类型：{selectedGraphEdge.type} · 方向：{selectedGraphEdge.source} → {selectedGraphEdge.target}</div>
                      <div>置信度：{(selectedGraphEdge.confidence * 100).toFixed(0)}%{selectedGraphEdge.strength ? ` · 强度：${selectedGraphEdge.strength}` : ''}</div>
                      {selectedGraphEdge.evidenceText && <div>证据：{selectedGraphEdge.evidenceText}</div>}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div style={{ color: '#94a3b8', fontSize: 13, paddingTop: 24, textAlign: 'center' }}>选择左侧回路后查看步骤、功能和统计信息</div>
            )}
          </div>
        </div>
      )}
      {phase === 'results' && circuits.length === 0 && stdFunctions.length > 0 && <div style={{ color: '#94a3b8', fontSize: 14, textAlign: 'center', padding: 40 }}>未找到匹配回路</div>}
    </div>
  )
}
