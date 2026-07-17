/**
 * ClinicalReportModal.tsx —炫酷的AI报告生成弹窗，集成进度条和回路展示。
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { postJson } from '../../api/client'
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
  onClose: () => void
}

type Stage = { key: string; label: string; icon: string }
const STAGES: Stage[] = [
  { key: 'collect', label: '收集中枢神经回路数据', icon: '🔍' },
  { key: 'analyze', label: 'AI深度多系统分析', icon: '🧠' },
  { key: 'format', label: '结构化报告生成', icon: '📝' },
  { key: 'render', label: '最终排版渲染', icon: '✨' },
]

export function ClinicalReportModal({ open, summary, circuits, graphNodes, graphEdges, onClose }: Props) {
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
    }).then(resp => {
      finishProgress()
      // Convert markdown-like report to styled HTML
      let body = resp.report_markdown
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/\n\n/g, '</p><p>')
        .replace(/^【(.+)】$/gm, '<h2>$1</h2>')
        .replace(/^- (.+)$/gm, '<li>$1</li>')
        .replace(/^```([\s\S]*?)```/gm, '<pre>$1</pre>')
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
            <div className="report-content-body" ref={reportRef}
              dangerouslySetInnerHTML={{ __html: reportHtml }} />
          </div>
        )}
      </div>
    </div>
  )
}
