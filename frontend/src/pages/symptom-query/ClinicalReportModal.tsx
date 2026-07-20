/**
 * ClinicalReportModal.tsx — AI报告生成弹窗，集成进度条、回路图和影响路径。
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { postJson } from '../../api/client'
import { SymptomCircuitGraph } from './SymptomCircuitGraph'
import { normalizeSymptomGraph } from './normalizeSymptomGraph'
import type { RawGraphData } from './symptomGraphTypes'
import './ClinicalReportModal.css'

interface CircuitInfo {
  circuit_name: string
  circuit_type: string | null
  match_score: number
  step_count: number
  function_count: number
  matched_functions: string[]
  description: string | null
  steps: { id: string; step_order: number; step_name: string; step_type: string; role: string }[]
}

interface Props {
  open: boolean
  summary: string
  circuits: CircuitInfo[]
  graphNodes: number
  graphEdges: number
  graphData: RawGraphData | null
  syndrome: string
  implicatedRegions: string[]
  neurotransmitters: string[]
  pathwayLevel: string
  onClose: () => void
}

type Stage = { key: string; label: string; icon: string }
const STAGES: Stage[] = [
  { key: 'collect', label: '收集中枢神经回路数据', icon: '🔍' },
  { key: 'analyze', label: 'AI深度多系统分析', icon: '🧠' },
  { key: 'format', label: '结构化报告生成', icon: '📝' },
  { key: 'render', label: '最终排版渲染', icon: '✨' },
]

export function ClinicalReportModal({ open, summary, circuits, graphNodes, graphEdges, graphData, syndrome, implicatedRegions, neurotransmitters, pathwayLevel, onClose }: Props) {
  const [stage, setStage] = useState(0)
  const [progress, setProgress] = useState(0)
  const [reportHtml, setReportHtml] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const reportRef = useRef<HTMLDivElement>(null)

  // Simulate animated progress during the API call
  const startProgress = useCallback(() => {
    let s = 0; let p = 0
    timerRef.current = setInterval(() => {
      p += Math.random() * 8 + 2
      if (p >= 98) { p = 98; if (timerRef.current) clearInterval(timerRef.current) }
      if (p > 65 && s < 1) { s = 1; setStage(1) }
      if (p > 80 && s < 2) { s = 2; setStage(2) }
      if (p > 90 && s < 3) { s = 3; setStage(3) }
      setProgress(Math.floor(p))
    }, 300)
  }, [])

  const finishProgress = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current)
    setStage(3); setProgress(100)
    setTimeout(() => setDone(true), 500)
  }, [])

  useEffect(() => {
    if (!open) return
    setStage(0); setProgress(0); setReportHtml(''); setError(''); setDone(false)
    startProgress()

    postJson<{ report_markdown: string }>('/api/symptom-query/report', {
      summary,
      circuits: circuits.map(c => ({
        circuit_name: c.circuit_name, circuit_type: c.circuit_type,
        match_score: c.match_score, step_count: c.step_count,
        function_count: c.function_count, matched_functions: c.matched_functions || [],
        description: c.description || '', steps: c.steps || [],
      })),
      graph_nodes: graphNodes,
      graph_edges: graphEdges,
      syndrome,
      implicated_regions: implicatedRegions,
      neurotransmitters,
      pathway_level: pathwayLevel,
    }).then(resp => {
      finishProgress()
      let body = resp.report_markdown
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        // Clean artifacts
        .replace(/^[-*_]{3,}\s*$/gm, '')
        .replace(/\\\*\*\*/g, '')
        // Bold/italic
        .replace(/\*\*\*(.+?)\*\*\*/g, '<strong>$1</strong>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        // Section headers FIRST (before paragraph conversion): wrap in <h2>
        .replace(/^(【[^】]+】)\s*$/gm, '<h2>$1</h2>')
        // Sub-headers
        .replace(/^##\s+(.+)$/gm, '<h3>$1</h3>')
        // Bullet lists
        .replace(/^- (.+)$/gm, '<li>$1</li>')
        .replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>')
        // Code blocks
        .replace(/```([\s\S]*?)```/g, '<pre>$1</pre>')
        // Numbered items
        .replace(/^(\d+)\.\s+(.+)$/gm, '<p><strong>$1.</strong> $2</p>')
        // Paragraphs LAST
        .replace(/\n\n/g, '</p><p>')
      setReportHtml(body)
    }).catch(e => {
      if (timerRef.current) clearInterval(timerRef.current)
      setError(e?.message || '报告生成失败')
    })

    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [open])

  const [downloading, setDownloading] = useState(false)
  const handleDownload = async () => {
    if (!reportHtml || downloading) return
    setDownloading(true)
    try {
      const resp = await fetch('/api/symptom-query/report/pdf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ summary, circuits, graph_nodes: graphNodes, graph_edges: graphEdges }),
      })
      if (!resp.ok) throw new Error('PDF生成失败')
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = '脑部健康分析报告.pdf'; a.click()
      URL.revokeObjectURL(url)
    } catch (e: any) { alert(e.message || '下载失败') }
    finally { setDownloading(false) }
  }

  const handlePrint = () => {
    if (!reportHtml) return
    const w = window.open('', '_blank', 'width=900,height=800')
    if (w) {
      w.document.write(reportHtml)
      w.document.close()
      w.focus()
      setTimeout(() => w.print(), 500)
    }
  }

  if (!open) return null

  const circuitNames = circuits.slice(0, 6).map(c => (
    `<div class="circuit-chip"><span class="circuit-dot"></span>${c.circuit_name}</div>`
  )).join('')

  return (
    <div className="report-modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="report-modal-container">
        {/* Header */}
        <div className="report-modal-header">
          <div className="report-modal-header-left">
            <span className="report-modal-icon">🧠</span>
            <span className="report-modal-title">AI 脑部健康分析报告</span>
          </div>
          <div className="report-modal-header-right">
            {done && <button className="report-btn report-btn-print" onClick={handlePrint}>🖨️ 打印</button>}
            {done && <button className="report-btn report-btn-download" onClick={handleDownload} disabled={downloading}>{downloading ? '⏳ 生成中...' : '📥 下载PDF'}</button>}
            <button className="report-btn report-btn-close" onClick={onClose}>✕</button>
          </div>
        </div>

        {/* Progress phase */}
        {!done && !error && (
          <div className="report-progress-container">
            <div className="report-progress-spinner">
              <div className="report-progress-ring">
                <svg viewBox="0 0 120 120">
                  <circle cx="60" cy="60" r="52" fill="none" stroke="#1a2a4a" strokeWidth="6" />
                  <circle cx="60" cy="60" r="52" fill="none" stroke="url(#grad)" strokeWidth="6"
                    strokeDasharray={`${progress * 3.27} 327`} strokeLinecap="round"
                    transform="rotate(-90 60 60)" className="report-progress-arc" />
                  <defs>
                    <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
                      <stop offset="0%" stopColor="#00D4FF" />
                      <stop offset="100%" stopColor="#7B61FF" />
                    </linearGradient>
                  </defs>
                </svg>
                <div className="report-progress-pct">{progress}%</div>
              </div>
            </div>

            <div className="report-progress-stages">
              {STAGES.map((s, i) => (
                <div key={s.key} className={`report-stage ${i < stage ? 'done' : i === stage ? 'active' : 'pending'}`}>
                  <span className="report-stage-icon">{i < stage ? '✅' : s.icon}</span>
                  <span className="report-stage-label">{s.label}</span>
                  {i < stage && <span className="report-stage-check">✓</span>}
                  {i === stage && <div className="report-stage-pulse" />}
                </div>
              ))}
            </div>

            <div className="report-progress-info">
              <span>正在通过NeuroGraphIQ知识图谱分析 {circuits.length} 条脑回路</span>
              <span>涉及 {graphNodes} 个脑区节点 · {graphEdges} 条神经连接</span>
            </div>

            <div className="report-circuit-preview" dangerouslySetInnerHTML={{ __html: circuitNames }} />
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="report-error-container">
            <div className="report-error-icon">⚠️</div>
            <h3>报告生成失败</h3>
            <p>{error}</p>
            <button className="report-btn report-btn-retry" onClick={() => { setError(''); setStage(0); setProgress(0); startProgress() }}>重试</button>
          </div>
        )}

        {/* Report content */}
        {done && (
          <div className="report-content-container">
            {/* Split at section 二 to insert graph */}
            {(() => {
              const graphBlock = circuits.length > 0 && graphData ? (() => {
                const top = circuits[0]
                const model = normalizeSymptomGraph(graphData, new Set(circuits.slice(0,1).map(c => c.id)))
                const regionNames = model.nodes?.map((n: any) => n.label || n.name_en || '').filter(Boolean) || []
                return (
                  <div className="circuit-graph-section">
                    <h3>核心回路: {top.circuit_name}</h3>
                    {top.circuit_type && <span className="circuit-type-badge">{top.circuit_type}</span>}

                    <div className="circuit-explain">
                      <p><strong>{top.circuit_name}</strong> 是系统中与当前症状匹配度最高的神经回路（评分 {((top.match_score || 0) * 100).toFixed(0)} 分）。</p>
                      {top.description && <p>{top.description}</p>}
                      <p>该回路由 <strong>{top.step_count || 0} 个步骤</strong>组成，涉及 <strong>{regionNames.length} 个脑区</strong>，包含 <strong>{top.function_count || 0} 个功能模块</strong>。以下图谱展示该回路的完整连接结构，您可以拖拽、缩放查看每个脑区的具体位置和连接关系。</p>
                      {regionNames.length > 0 && (
                        <p>涉及脑区: {regionNames.map((r: string) => <code key={r}>{r}</code>)}</p>
                      )}
                    </div>

                    <div className="circuit-graph-wrapper"
                      ref={(el) => {
                        if (!el) return
                        // Let D3 handle zoom, but prevent parent scroll
                        const onWheel = (e: WheelEvent) => {
                          e.stopPropagation()
                        }
                        el.addEventListener('wheel', onWheel, { passive: false })
                      }}>
                      <SymptomCircuitGraph
                        model={model}
                        selectedCircuitId={top.id}
                        selectedCircuit={top as any}
                        selectedStepIndex={null}
                        onStepHover={() => {}}
                        onStepSelect={() => {}}
                        onEdgeSelect={() => {}}
                      />
                    </div>

                    <div className="circuit-stats">
                      <span>{top.step_count || 0} 步骤</span>
                      <span>{top.function_count || 0} 功能</span>
                      <span>{regionNames.length} 脑区</span>
                      <span>{model.edges?.length || 0} 连接</span>
                    </div>
                  </div>
                )
              })() : null

              // Split BEFORE section 三 — insert graph between 二 and 三
              const splitAt = /(?=<h2>【三[、,，])/
              let parts = reportHtml.split(splitAt)
              // Fallback: try raw markdown
              if (parts.length === 1) {
                const raw = reportHtml.split(/(?=【三[、,，])/)
                if (raw.length > 1) parts = raw
              }
              return (
                <>
                  <div className="report-content-body" ref={reportRef}
                    dangerouslySetInnerHTML={{ __html: (parts?.[0]) || reportHtml }} />
                  {graphBlock}
                  {parts?.[1] && (
                    <div className="report-content-body"
                      dangerouslySetInnerHTML={{ __html: parts[1] }} />
                  )}
                </>
              )
            })()}
          </div>
        )}
      </div>
    </div>
  )
}
