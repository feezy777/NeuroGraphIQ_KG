/**
 * ClinicalReportModal.tsx — AI报告生成弹窗，集成进度条、回路图和影响路径。
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { postJson } from '../../api/client'
import { SymptomCircuitGraph } from './SymptomCircuitGraph'
import { normalizeSymptomGraph } from './normalizeSymptomGraph'
import type { RawGraphData } from './symptomGraphTypes'
import { Brain, Download, Printer, X, CheckCircle2, Database, Sparkles, FileText, Loader2 } from 'lucide-react'
import './ClinicalReportModal.css'

interface CircuitInfo {
  id: string
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
  matchedCircuitIds: Set<string>
  syndrome: string
  implicatedRegions: string[]
  neurotransmitters: string[]
  pathwayLevel: string
  onClose: () => void
}

type Stage = { key: string; label: string; icon: typeof Database }
const STAGES: Stage[] = [
  { key: 'collect', label: '收集中枢神经回路数据', icon: Database },
  { key: 'analyze', label: 'AI深度多系统分析', icon: Brain },
  { key: 'format', label: '结构化报告生成', icon: FileText },
  { key: 'render', label: '最终排版渲染', icon: Sparkles },
]

export function ClinicalReportModal({ open, summary, circuits, graphNodes, graphEdges, graphData, matchedCircuitIds, syndrome, implicatedRegions, neurotransmitters, pathwayLevel, onClose }: Props) {
  const [stage, setStage] = useState(0)
  const [progress, setProgress] = useState(0)
  const [reportHtml, setReportHtml] = useState('')
  const [reportMd, setReportMd] = useState('')
  const [circuitDescription, setCircuitDescription] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const reportRef = useRef<HTMLDivElement>(null)
  const graphCaptureRef = useRef<HTMLDivElement>(null)

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
    setStage(0); setProgress(0); setReportHtml(''); setReportMd(''); setError(''); setDone(false)
    startProgress()

    Promise.all([
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
      }),
      // Generate circuit description separately
      circuits.length > 0 ? postJson<{ description: string }>('/api/symptom-query/circuit-describe', {
        circuit_name: circuits[0].circuit_name,
        circuit_type: circuits[0].circuit_type || '',
        steps: circuits[0].steps || [],
        functions: circuits[0].matched_functions || [],
        syndrome,
      }).then(r => r.description).catch(() => '') : Promise.resolve(''),
    ]).then(([resp, circDesc]) => {
      finishProgress()
      setCircuitDescription(circDesc || '')
      const md = resp.report_markdown || ''
      const cleanReportText = (raw: string) => {
        const boldHold: string[] = []
        const park = (_: string, inner: string) => {
          boldHold.push(inner)
          return `\u0001B${boldHold.length - 1}\u0001`
        }
        let t = raw.replace(/\r/g, '')
        t = t.replace(/\*\*\*(.+?)\*\*\*/g, park)
        t = t.replace(/\*\*(.+?)\*\*/g, park)
        t = t.replace(/\*{1,3}/g, '')
        // Remove technical snake_case ids in parentheses
        t = t.replace(/（[a-z][a-z0-9_]{2,}）/g, '')
        t = t.replace(/\([a-z][a-z0-9_]{2,}\)/g, '')
        t = t.replace(/（\s*）/g, '').replace(/\(\s*\)/g, '')
        // Strip orphan 】 only outside 【标题】 lines
        t = t.split('\n').map((ln) => {
          const s = ln.trim()
          if (/^【.+】/.test(s)) return ln
          return ln.replace(/】+/g, '')
        }).join('\n')
        t = t.replace(/[ \t]{2,}/g, ' ')
        t = t.replace(/\u0001B(\d+)\u0001/g, (_, i: string) => `**${boldHold[Number(i)]}**`)
        return t
      }
      const cleanedMd = cleanReportText(md)
      setReportMd(cleanedMd)
      // Line-oriented markdown → HTML
      const htmlLines: string[] = []
      let inList = false
      const closeList = () => {
        if (inList) { htmlLines.push('</ul>'); inList = false }
      }
      for (const rawLine of cleanedMd.split('\n')) {
        const line = rawLine.trim()
        if (!line || /^[-*_]{3,}$/.test(line)) {
          closeList()
          continue
        }
        const stripLeadPunct = (s: string) => s
          .replace(/^[-–—*•·|#]+\s*/, '')
          .replace(/^[。，、；：！？‥…》」』）\]）)}\%}‰℃,.;:!?'"’”•·【】《「『（(\[{“‘\s\-–—]+/, '')
        const inline = (s: string) => {
          const hold: string[] = []
          let t = stripLeadPunct(s)
          t = t.replace(/\*\*\*(.+?)\*\*\*/g, (_, inner: string) => {
            hold.push(inner)
            return `\u0001${hold.length - 1}\u0001`
          })
          t = t.replace(/\*\*(.+?)\*\*/g, (_, inner: string) => {
            hold.push(inner)
            return `\u0001${hold.length - 1}\u0001`
          })
          t = t.replace(/\*/g, '')
          const esc = (x: string) => x.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
          t = esc(t)
          t = t.replace(/\u0001(\d+)\u0001/g, (_, i: string) => `<strong>${esc(hold[Number(i)])}</strong>`)
          return t
        }

        const section = line.match(/^【(.+?)】(.*)$/)
        if (section) {
          closeList()
          htmlLines.push(`<h2>${inline(section[1])}</h2>`)
          const rest = stripLeadPunct(section[2].trim())
          if (rest) htmlLines.push(`<p>${inline(rest)}</p>`)
          continue
        }
        if (/^##\s+/.test(line)) {
          closeList()
          htmlLines.push(`<h3>${inline(line.replace(/^##\s+/, '').replace(/^[【\[]|[】\]]$/g, ''))}</h3>`)
          continue
        }
        if (/^[-•*]\s+/.test(line)) {
          closeList()
          htmlLines.push(`<p>${inline(line.replace(/^[-•*]\s+/, ''))}</p>`)
          continue
        }
        closeList()
        const num = line.match(/^(\d+)[.)、．]\s+(.+)$/)
        if (num) {
          htmlLines.push(`<p>${num[1]}. ${inline(num[2])}</p>`)
          continue
        }
        htmlLines.push(`<p>${inline(line)}</p>`)
      }
      closeList()
      setReportHtml(htmlLines.join('\n'))
    }).catch(e => {
      if (timerRef.current) clearInterval(timerRef.current)
      setError(e?.message || '报告生成失败')
    })

    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [open])

  const [downloading, setDownloading] = useState(false)

  const captureGraphPngBase64 = useCallback(async (): Promise<string> => {
    const wrapper = graphCaptureRef.current
      || document.querySelector('.report-content-container .circuit-graph-wrapper') as HTMLDivElement | null
    const svgEl = wrapper?.querySelector('svg') as SVGSVGElement | null
    if (!svgEl) return ''

    // getBBox() ignores the element's own transform — pan/zoom lives on the first <g>.
    // Strip that transform on the clone so viewBox matches node coordinates (avoids blank PNG).
    const content = svgEl.querySelector('g') as SVGGElement | null
    let bbox = { x: 0, y: 0, width: 800, height: 560 }
    try {
      const raw = content?.getBBox?.()
      if (raw && raw.width > 1 && raw.height > 1) {
        bbox = { x: raw.x, y: raw.y, width: raw.width, height: raw.height }
      }
    } catch {
      /* getBBox can throw if SVG not rendered */
    }

    const pad = 36
    const vbX = bbox.x - pad
    const vbY = bbox.y - pad
    const vbW = Math.max(bbox.width + pad * 2, 100)
    const vbH = Math.max(bbox.height + pad * 2, 80)
    const outW = 1400
    const outH = Math.max(700, Math.round(outW * (vbH / vbW)))

    const clone = svgEl.cloneNode(true) as SVGSVGElement
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
    clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink')
    const zoomG = clone.querySelector('g')
    if (zoomG) zoomG.removeAttribute('transform')

    // Unique marker ids inside blob URL (avoid collisions with live SVG)
    const uid = `pdf-${Date.now()}`
    clone.querySelectorAll('marker[id]').forEach((m) => {
      const oldId = m.getAttribute('id') || ''
      const nextId = `${uid}-${oldId}`
      m.setAttribute('id', nextId)
      clone.querySelectorAll(`[marker-end="url(#${oldId})"]`).forEach((el) => {
        el.setAttribute('marker-end', `url(#${nextId})`)
      })
    })

    clone.setAttribute('viewBox', `${vbX} ${vbY} ${vbW} ${vbH}`)
    clone.setAttribute('width', String(outW))
    clone.setAttribute('height', String(outH))
    clone.style.width = `${outW}px`
    clone.style.height = `${outH}px`
    clone.style.background = '#ffffff'

    const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
    bg.setAttribute('x', String(vbX))
    bg.setAttribute('y', String(vbY))
    bg.setAttribute('width', String(vbW))
    bg.setAttribute('height', String(vbH))
    bg.setAttribute('fill', '#ffffff')
    clone.insertBefore(bg, clone.firstChild)

    // Force label visibility in export (inline fill already set; bump font for readability)
    clone.querySelectorAll('text').forEach((t) => {
      const el = t as SVGTextElement
      el.style.fontSize = '12px'
      el.style.fontFamily = 'Segoe UI, Microsoft YaHei, sans-serif'
      if (!el.getAttribute('fill') && !el.style.fill) el.setAttribute('fill', '#334155')
    })

    const svgData = new XMLSerializer().serializeToString(clone)
    const blob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' })
    const url = URL.createObjectURL(blob)

    try {
      const img = new Image()
      img.decoding = 'sync'
      await new Promise<void>((resolve, reject) => {
        img.onload = () => resolve()
        img.onerror = () => reject(new Error('SVG rasterize failed'))
        img.src = url
      })

      const canvas = document.createElement('canvas')
      canvas.width = outW
      canvas.height = outH
      const ctx = canvas.getContext('2d')
      if (!ctx) return ''
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, outW, outH)
      ctx.drawImage(img, 0, 0, outW, outH)
      const dataUrl = canvas.toDataURL('image/png')
      return dataUrl.includes(',') ? dataUrl.split(',')[1] : ''
    } finally {
      URL.revokeObjectURL(url)
    }
  }, [])

  const handleDownload = async () => {
    if (!reportHtml || downloading) return
    setDownloading(true)
    try {
      let graphB64 = ''
      try {
        graphB64 = await captureGraphPngBase64()
      } catch (e) {
        console.warn('Graph capture failed:', e)
      }

      const resp = await fetch('/api/symptom-query/report/pdf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          summary,
          report_markdown: reportMd,
          circuits: circuits.map(c => ({
            id: c.id,
            circuit_name: c.circuit_name, circuit_type: c.circuit_type,
            match_score: c.match_score, step_count: c.step_count,
            function_count: c.function_count, matched_functions: c.matched_functions || [],
            description: c.description || '', steps: c.steps || [],
          })),
          graph_nodes: graphNodes, graph_edges: graphEdges,
          syndrome, implicated_regions: implicatedRegions,
          neurotransmitters, pathway_level: pathwayLevel,
          graph_image: graphB64,
        }),
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
            <Brain size={22} color="#1677ff" />
            <span className="report-modal-title">AI 脑部健康分析报告</span>
          </div>
          <div className="report-modal-header-right">
            {done && <button className="report-btn report-btn-print" onClick={handlePrint}><Printer size={14} /> 打印</button>}
            {done && <button className="report-btn report-btn-download" onClick={handleDownload} disabled={downloading}>{downloading ? <Loader2 size={14} className="spin" /> : <Download size={14} />} {downloading ? '生成中…' : '下载PDF'}</button>}
            <button className="report-btn report-btn-close" onClick={onClose}><X size={18} /></button>
          </div>
        </div>

        {/* Progress phase */}
        {!done && !error && (
          <div className="report-progress-container">
            <div className="report-progress-spinner">
              <div className="report-progress-ring">
                <svg viewBox="0 0 120 120">
                  <circle cx="60" cy="60" r="52" fill="none" stroke="#e8ecf0" strokeWidth="6" />
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
              {STAGES.map((s, i) => {
                const Done = CheckCircle2
                const Icon = s.icon
                const isActive = i === stage
                const isDone = i < stage
                return (
                <div key={s.key} className={`report-stage ${isDone ? 'done' : isActive ? 'active' : 'pending'}`}>
                  <span className="report-stage-icon">
                    {isDone ? <Done size={18} color="#52c41a" /> : isActive ? <Loader2 size={18} className="spin" color="#1677ff" /> : <Icon size={18} />}
                  </span>
                  <span className="report-stage-label">{s.label}</span>
                  {isActive && <div className="report-stage-pulse" />}
                </div>
              )})}
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
            <X size={48} color="#cf1322" />
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
                const model = normalizeSymptomGraph(graphData, matchedCircuitIds)
                const regionNames = model.nodes?.map((n: any) => n.label || n.name_en || '').filter(Boolean) || []
                return (
                  <div className="circuit-graph-section">
                    <h3>核心回路: {top.circuit_name}</h3>
                    {top.circuit_type && <span className="circuit-type-badge">{top.circuit_type}</span>}

                    <div className="circuit-explain">
                      {circuitDescription ? (
                        <p>{circuitDescription}</p>
                      ) : (
                        <>
                          <p><strong>{top.circuit_name}</strong> 是系统中与当前症状匹配度最高的神经回路。</p>
                          {top.description && <p>{top.description}</p>}
                        </>
                      )}
                      <p>该回路包含 <strong>{top.step_count || 0} 个步骤</strong>、<strong>{regionNames.length} 个脑区</strong>、<strong>{top.function_count || 0} 个功能模块</strong>。下方图谱展示完整连接结构。</p>
                    </div>

                    <div
                      className="circuit-graph-wrapper"
                      ref={(el) => {
                        graphCaptureRef.current = el
                        if (!el) return
                        const onWheel = (e: WheelEvent) => { e.stopPropagation() }
                        el.addEventListener('wheel', onWheel, { passive: false })
                      }}
                    >
                      <SymptomCircuitGraph
                        model={model}
                        selectedCircuitId={top.id}
                        selectedCircuit={top as any}
                        selectedStepIndex={null}
                        onSelectedStepIndexChange={() => {}}
                        onEdgeSelect={() => {}}
                      />
                    </div>
                    <div className="circuit-graph-hint">拖拽平移 · 滚轮缩放 · 点击查看脑区详情</div>

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
              const splitAt = /(?=<h2>(?:【)?三[、,，])/
              let parts = reportHtml.split(splitAt)
              // Fallback: try raw markdown
              if (parts.length === 1) {
                const raw = reportHtml.split(/(?=【?三[、,，])/)
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
