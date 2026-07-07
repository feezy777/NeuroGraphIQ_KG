import { useState, useCallback, useRef, useEffect } from 'react'
import { StatusBadge } from '../../../components/StatusBadge'
import {
  runCircuitExtraction,
  getCircuitExtractionRun,
  cancelCircuitExtractionRun,
  type CandidatePool,
  type CircuitExtractionRunRead,
} from '../../../api/endpoints'

interface Props {
  pool: CandidatePool
  provider: string
  modelName: string
  onClose: () => void
  onCompleted?: () => void
}

const TERMINAL = new Set(['succeeded', 'partially_succeeded', 'failed', 'cancelled'])

function elapsedStr(sec: number): string {
  if (sec < 60) return `${Math.round(sec)}s`
  return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`
}

export function CircuitExtractionPanel({ pool, provider, modelName, onClose, onCompleted }: Props) {
  const [runId, setRunId] = useState<string | null>(null)
  const [status, setStatus] = useState('idle')
  const [detail, setDetail] = useState<CircuitExtractionRunRead | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const startRef = useRef(0)
  const candidateIds = pool.memberships?.map(m => m.candidate_id) ?? []

  const handleRun = useCallback(async () => {
    if (candidateIds.length < 2) return
    setStatus('pending')
    setError(null)
    setDetail(null)
    setElapsed(0)
    startRef.current = Date.now()
    try {
      const res = await runCircuitExtraction({
        provider,
        model_name: modelName || undefined,
        candidate_ids: candidateIds,
        pool_id: pool.id,
        candidates_per_pack: 10,
      })
      setRunId(res.run_id)
      setStatus('pending')
    } catch (e: any) {
      setError(e.message || String(e))
      setStatus('idle')
    }
  }, [candidateIds, provider, modelName, pool.id])

  // Polling
  useEffect(() => {
    if (!runId || status === 'idle') return
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const d = await getCircuitExtractionRun(runId)
        setDetail(d)
        setStatus(d.status)
        setElapsed((Date.now() - startRef.current) / 1000)
        if (TERMINAL.has(d.status)) {
          if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
          setCancelling(false)
          onCompleted?.()
        }
      } catch { /* polling error */ }
    }, 2000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [runId]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleCancel = useCallback(async () => {
    if (!runId || cancelling) return
    setCancelling(true)
    try { await cancelCircuitExtractionRun(runId) } catch { setCancelling(false) }
  }, [runId, cancelling])

  const handleClose = () => {
    if (pollRef.current) clearInterval(pollRef.current)
    onClose()
  }

  const isRunning = status === 'pending' || status === 'running'
  const terminal = TERMINAL.has(status)
  const summary = detail?.result_summary_json || {}
  const processed = (summary as any)?.processed_packs ?? 0
  const total = (summary as any)?.total_packs ?? 0

  return (
    <div className="circuit-extraction-panel card" style={{ padding: 20, marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h3 style={{ margin: 0, fontSize: 16 }}>⭕ 回路提取</h3>
        <button className="btn-close" onClick={handleClose}>✕</button>
      </div>

      {status === 'idle' && (
        <div style={{ textAlign: 'center', padding: 24 }}>
          <p>从脑区池 <strong>{pool.name || pool.source_atlas}</strong> 提取回路</p>
          <p style={{ color: '#888', fontSize: 13 }}>
            {candidateIds.length} 个脑区 · 预估 {Math.max(1, Math.ceil(candidateIds.length / 10))} pack
          </p>
          <button className="btn btn-primary" onClick={handleRun}>
            ⚡ 开始提取
          </button>
          {error && <p style={{ color: '#cf1322', marginTop: 8 }}>{error}</p>}
        </div>
      )}

      {(isRunning || terminal) && (
        <>
          <div className={`dc-fc-stats-banner ${terminal ? (status === 'succeeded' ? 'success' : status === 'cancelled' ? 'error' : 'warning') : 'running'}`}>
            <div className="dc-fc-stats-banner-title">
              {status === 'pending' ? '⏳ 排队等待...' :
               status === 'running' ? `⭕ 提取中 · ${elapsedStr(elapsed)}` :
               status === 'succeeded' ? '✅ 回路提取完成' :
               status === 'cancelled' ? '已取消' :
               status === 'partially_succeeded' ? '⚠️ 部分完成' : `状态: ${status}`}
            </div>
            {isRunning && total > 0 && (
              <div className="dc-fc-stats-banner-sub">
                pack {processed}/{total} · {elapsedStr(elapsed)}
              </div>
            )}
          </div>

          {isRunning && total > 0 && (
            <div className="dc-fc-progress" style={{ marginBottom: 12 }}>
              <div className="dc-fc-progress-track">
                <div className="dc-fc-progress-fill" style={{ width: `${total > 0 ? Math.round((processed / total) * 100) : 0}%` }} />
              </div>
            </div>
          )}

          {terminal && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginTop: 12 }}>
              {[
                { label: '回路', value: detail?.circuit_count ?? 0, color: '#7c3aed' },
                { label: '步骤', value: detail?.step_count ?? 0, color: '#2563eb' },
                { label: '功能', value: detail?.function_count ?? 0, color: '#16a34a' },
              ].map((s, i) => (
                <div key={i} style={{ background: '#f9fafb', borderRadius: 8, padding: 12, textAlign: 'center', border: '1px solid #e5e7eb' }}>
                  <div style={{ fontSize: 24, fontWeight: 700, color: s.color }}>{s.value}</div>
                  <div style={{ fontSize: 12, color: '#6b7280' }}>{s.label}</div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
        {isRunning && (
          <button className="btn" onClick={handleCancel} disabled={cancelling}>
            {cancelling ? '取消中…' : '取消'}
          </button>
        )}
        {isRunning && <button className="btn" onClick={handleClose}>后台运行</button>}
        {terminal && <button className="btn btn-primary" onClick={handleClose}>关闭</button>}
      </div>
    </div>
  )
}
