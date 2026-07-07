import { useState, useMemo, useEffect, useRef, useCallback } from 'react'
import { DataTable, type Column } from '../../../components/DataTable'
import { StatusBadge } from '../../../components/StatusBadge'
import { useData } from '../../../hooks/useData'
import { ModelSelector } from './ModelSelector'
import { FieldCompletionStatsCards } from '../../data-center/FieldCompletionStatsCards'
import {
  listMirrorConnections,
  listMirrorCircuits,
  runUniversalFieldCompletion,
  cancelFieldCompletionRun,
  getFieldCompletionRun,
  type MirrorRegionConnection,
  type MirrorRegionCircuit,
  type UniversalFieldCompletionRequest,
  type FieldCompletionStartResponse,
  type FieldCompletionRunDetail,
} from '../../../api/endpoints'

type TargetType = 'connection' | 'circuit' | 'circuit_bundle'

interface FieldCompletionTabProps {
  providers: Array<{ name: string; configured: boolean; default_model: string }>
}

// ── Helpers ─────────────────────────────────────────────────────────────────

const TERMINAL_STATUSES = new Set([
  'succeeded',
  'partially_succeeded',
  'failed',
  'cancelled',
  'dry_run',
])

function isTerminal(status: string): boolean {
  return TERMINAL_STATUSES.has(status)
}

function elapsedStr(sec: number): string {
  if (sec < 60) return `${Math.round(sec)}s`
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}m ${s}s`
}

// ── Component ───────────────────────────────────────────────────────────────

export function FieldCompletionTab({ providers }: FieldCompletionTabProps) {
  const [targetType, setTargetType] = useState<TargetType>('connection')
  const [provider, setProvider] = useState('deepseek')
  const [modelName, setModelName] = useState('')
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [running, setRunning] = useState(false)
  const [runId, setRunId] = useState<string | null>(null)
  const [runStatus, setRunStatus] = useState<string>('')
  const [runDetail, setRunDetail] = useState<FieldCompletionRunDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [elapsedSec, setElapsedSec] = useState(0)
  const [cancelling, setCancelling] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const startRef = useRef<number>(0)

  const currentProvider = providers.find(p => p.name === provider)
  useEffect(() => {
    if (currentProvider && !modelName) setModelName(currentProvider.default_model)
  }, [currentProvider, modelName])

  const connParams = useMemo(() => ({ limit: 100 }), [])
  const circParams = useMemo(() => ({ limit: 100 }), [])
  const showConn = targetType === 'connection'
  const showCirc = targetType === 'circuit' || targetType === 'circuit_bundle'

  const { data: connections } = useData(
    () => showConn ? listMirrorConnections(connParams) : (Promise.resolve({ items: [], total: 0, limit: 100, offset: 0 }) as any),
    [showConn, connParams],
  )
  const { data: circuits } = useData(
    () => showCirc ? listMirrorCircuits(circParams) : (Promise.resolve({ items: [], total: 0, limit: 100, offset: 0 }) as any),
    [showCirc, circParams],
  )

  const connColumns: Column<MirrorRegionConnection>[] = useMemo(() => [
    { key: '_sel', header: '', width: 36, render: r => (
      <input type="checkbox" checked={selectedIds.includes(r.id)} onChange={() => {
        setSelectedIds(prev => prev.includes(r.id) ? prev.filter(x => x !== r.id) : [...prev, r.id])
      }} />
    )},
    { key: 'source_region_candidate_id', header: '源', render: r => (r.source_region_candidate_id || '—').slice(0, 10) },
    { key: 'target_region_candidate_id', header: '靶', render: r => (r.target_region_candidate_id || '—').slice(0, 10) },
    { key: 'connection_type', header: '类型', width: 120 },
    { key: 'confidence', header: '置信度', width: 70, render: r => r.confidence != null ? Math.round(r.confidence * 100) + '%' : '—' },
    { key: 'mirror_status', header: '状态', width: 80, render: r => <StatusBadge status={r.mirror_status} /> },
  ], [selectedIds])

  const circuitColumns: Column<MirrorRegionCircuit>[] = useMemo(() => [
    { key: '_sel', header: '', width: 36, render: r => (
      <input type="checkbox" checked={selectedIds.includes(r.id)} onChange={() => {
        setSelectedIds(prev => prev.includes(r.id) ? prev.filter(x => x !== r.id) : [...prev, r.id])
      }} />
    )},
    { key: 'circuit_name', header: '回路名称', width: 200 },
    { key: 'circuit_type', header: '类型', width: 120 },
    { key: 'function_association', header: '功能', render: r => r.function_association || '—' },
    { key: 'confidence', header: '置信度', width: 70, render: r => r.confidence != null ? Math.round(r.confidence * 100) + '%' : '—' },
    { key: 'mirror_status', header: '状态', width: 80, render: r => <StatusBadge status={r.mirror_status} /> },
  ], [selectedIds])

  const conns = (connections as any)?.items ?? []
  const circs = (circuits as any)?.items ?? []

  // ── Polling ───────────────────────────────────────────────────────────────

  const startPolling = useCallback((id: string) => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const detail = await getFieldCompletionRun(id)
        setRunDetail(detail)
        setRunStatus(detail.status)
        setElapsedSec(Math.round((Date.now() - startRef.current) / 1000))
        if (isTerminal(detail.status)) {
          if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
          setRunning(false)
          setCancelling(false)  // Clear cancelling state on terminal
        }
      } catch (e: any) {
        // polling error — ignore transient failures
      }
    }, 2000)
  }, [])

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  // ── Actions ───────────────────────────────────────────────────────────────

  const handleRun = async () => {
    if (selectedIds.length === 0) return
    setRunning(true)
    setError(null)
    setRunDetail(null)
    setRunStatus('pending')
    setElapsedSec(0)
    startRef.current = Date.now()

    try {
      if (targetType === 'circuit_bundle') {
        setError('回路 Bundle 补全请在 Data Center 中操作')
        setRunning(false)
        return
      }

      const apiTargetType = targetType === 'connection' ? 'projection' : 'circuit'

      const body: UniversalFieldCompletionRequest = {
        provider,
        model_name: modelName || undefined,
        target_type: apiTargetType as any,
        target_ids: selectedIds,
        dry_run: false,
      }

      const res = await runUniversalFieldCompletion(body)

      // Check if async start response
      if ('run_id' in res && res.status === 'pending') {
        setRunId(res.run_id)
        startPolling(res.run_id)
        setRunStatus('pending')
        return
      }

      // Legacy sync response (e.g. dry_run)
      setRunDetail(res as any)
      setRunStatus(res.status)
      setRunning(false)
    } catch (e: any) {
      setError(e.message || String(e))
      setRunning(false)
    }
  }

  const handleCancel = async () => {
    if (!runId || cancelling) return
    setCancelling(true)
    try {
      await cancelFieldCompletionRun(runId)
      // Let poller detect the status change — backend will check cancellation at next pack boundary
    } catch (e: any) {
      setError(e.message || String(e))
      setCancelling(false)
    }
  }

  const handleClose = () => {
    setRunning(false)
    setRunDetail(null)
    setRunStatus('')
    setRunId(null)
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  // ── Progress panel ────────────────────────────────────────────────────────

  const showProgressPanel = running && runId

  if (showProgressPanel) {
    return (
      <div className="field-completion-tab">
        <FieldCompletionStatsCards
          detail={runDetail}
          status={runStatus}
          targetCount={selectedIds.length}
          elapsedSec={elapsedSec}
          onCancel={!cancelling ? handleCancel : undefined}
          onClose={handleClose}
          cancelling={cancelling}
        />
        {error && (
          <div style={{ background: '#fff2f0', borderRadius: 6, padding: '8px 12px', border: '1px solid #ffccc7', margin: '10px 22px' }}>
            <div style={{ fontSize: 13, color: '#cf1322' }}>{error}</div>
          </div>
        )}
      </div>
    )
  }

  // ── Normal mode: target selection + run button ────────────────────────────

  return (
    <div className="field-completion-tab">
      <div className="field-completion-targets">
        <h4 className="panel-title">补全对象</h4>
        <div className="field-completion-type-row">
          {(['connection', 'circuit', 'circuit_bundle'] as TargetType[]).map(t => (
            <button
              key={t}
              className={`field-completion-type-btn${targetType === t ? ' active' : ''}`}
              onClick={() => { setTargetType(t); setSelectedIds([]) }}
            >
              {t === 'connection' ? '连接 (Projection)' : t === 'circuit' ? '回路 (Circuit)' : '回路 Bundle (Circuit + Steps + Functions)'}
            </button>
          ))}
        </div>
      </div>

      <ModelSelector
        provider={provider}
        modelName={modelName}
        onProviderChange={setProvider}
        onModelChange={setModelName}
        providers={providers}
      />

      <div className="field-completion-selection">
        <h4 className="panel-title">选择对象 ({selectedIds.length} 项已选)</h4>
        {showConn ? (
          <DataTable columns={connColumns} rows={conns} getKey={r => r.id} emptyText="暂无连接数据" />
        ) : (
          <DataTable columns={circuitColumns} rows={circs} getKey={r => r.id} emptyText="暂无回路数据" />
        )}
      </div>

      <div className="field-completion-actions">
        <button
          className="btn btn-primary"
          disabled={selectedIds.length === 0 || running || !currentProvider?.configured}
          onClick={handleRun}
        >
          {running ? '补全中…' : `✨ 执行字段补全 (${selectedIds.length})`}
        </button>
        {!currentProvider?.configured && (
          <span style={{ fontSize: 12, color: '#dc2626', marginLeft: 8 }}>
            请先在设置中配置 {provider} API Key
          </span>
        )}
      </div>

      {error && !running && (
        <div className="field-completion-result">
          <div style={{ background: '#fff2f0', borderRadius: 6, padding: '10px 14px', border: '1px solid #ffccc7' }}>
            <div style={{ fontSize: 13, color: '#cf1322' }}>{error}</div>
          </div>
        </div>
      )}

      {/* Show last completed run result even when not actively running */}
      {runDetail && !running && (
        <div className="field-completion-result" style={{ marginTop: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 8, marginBottom: 12 }}>
            {([
              { label: '已更新', value: (runDetail.summary_json as any)?.updated_count ?? 0, color: '#16a34a', bg: '#f0fdf4' },
              { label: '已建议', value: (runDetail.summary_json as any)?.suggested_count ?? 0, color: '#2563eb', bg: '#eff6ff' },
              { label: '已跳过', value: (runDetail.summary_json as any)?.skipped_count ?? 0, color: '#d97706', bg: '#fffbeb' },
              { label: '失败', value: (runDetail.summary_json as any)?.failed_count ?? 0, color: '#dc2626', bg: '#fef2f2' },
            ] as const).map((item, i) => (
              <div key={i} style={{ background: item.bg, borderRadius: 8, padding: '12px 8px', textAlign: 'center', border: '1px solid #e5e7eb' }}>
                <div style={{ fontSize: 24, fontWeight: 700, color: item.color }}>{item.value}</div>
                <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>{item.label}</div>
              </div>
            ))}
          </div>
          <button className="btn btn-secondary" onClick={() => setRunDetail(null)} style={{ fontSize: 12 }}>
            清除结果
          </button>
        </div>
      )}
    </div>
  )
}
