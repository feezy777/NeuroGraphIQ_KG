import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { StatusBadge } from '../../components/StatusBadge'
import { ModelBadge } from '../../components/ModelBadge'
import { FieldCompletionStatsCards } from './FieldCompletionStatsCards'
import { useI18n } from '../../i18n-context'
import {
  cancelFieldCompletionRun,
  getFieldCompletionRun,
  listFieldCompletionRuns,
  runUniversalFieldCompletion,
  type FieldCompletionItem,
  type FieldCompletionRun,
  type FieldCompletionRunDetail,
  type FieldCompletionScope,
  type FieldCompletionTargetType,
  type UniversalFieldCompletionResponse,
} from '../../api/endpoints'
import {
  type FormalFieldMapping,
  computeMissingFields,
} from './formalFieldMappings'
import {
  DEFAULT_FIELD_COMPLETION_OPTIONS,
  type FieldCompletionFormOptions,
  type FormalRow,
  buildFieldCompletionRequest,
  classifyFieldCompletionError,
  countTotalMissing,
  formatCellValue,
  formatFieldCompletionErrorMessage,
  getEnrichableColumns,
  hasCompletableFields,
  shortId,
  type OverlayPatch,
  extractOverlayPatchFromFieldUpdates,
  extractOverlayPatchFromItems,
} from './fieldCompletionUtils'

// ── Types ───────────────────────────────────────────────────────────────────

type Step = 0 | 1 | 2 | 3 // select, configure, dry_run, execute

const STEP_LABELS = ['选择对象', '配置参数', '预览', '执行补全'] as const

interface Props {
  open: boolean
  mapping: FormalFieldMapping
  selectedObjects: FormalRow[]
  selectedIds: string[]
  onClose: () => void
  onCompleted?: (overlayPatch?: OverlayPatch) => void
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function elapsedStr(sec: number): string {
  if (sec < 60) return `${Math.round(sec)}s`
  return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`
}

function formatValue(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'string') return v.length > 60 ? v.slice(0, 60) + '…' : v
  return JSON.stringify(v).slice(0, 60)
}

// ── Component ───────────────────────────────────────────────────────────────

export function FieldCompletionModal({
  open,
  mapping,
  selectedObjects,
  selectedIds,
  onClose,
  onCompleted,
}: Props) {
  const { t } = useI18n()
  const [step, setStep] = useState<Step>(0)
  const [options, setOptions] = useState<FieldCompletionFormOptions>(DEFAULT_FIELD_COMPLETION_OPTIONS)
  const [selProvider, setSelProvider] = useState('deepseek')
  const [selModel, setSelModel] = useState('deepseek-chat')
  const [customModel, setCustomModel] = useState('')
  const [loading, setLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // Dry run result
  const [dryRunResponse, setDryRunResponse] = useState<UniversalFieldCompletionResponse | null>(null)
  const [dryRunElapsed, setDryRunElapsed] = useState(0)

  // Async execute state
  const [asyncRunId, setAsyncRunId] = useState<string | null>(null)
  const [asyncStatus, setAsyncStatus] = useState('')
  const [execDetail, setExecDetail] = useState<FieldCompletionRunDetail | null>(null)
  const [execElapsed, setExecElapsed] = useState(0)
  const execStartRef = useRef(0)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [execDone, setExecDone] = useState(false)
  const [execOverlayPatch, setExecOverlayPatch] = useState<OverlayPatch>({})
  const mountedRef = useRef(true)
  const notifiedRef = useRef(false)       // C1: prevent double onCompleted
  const onCompletedRef = useRef(onCompleted)  // H3: stabilize poller deps
  onCompletedRef.current = onCompleted

  // Side drawer
  const [drawerRun, setDrawerRun] = useState<FieldCompletionRunDetail | null>(null)
  const [drawerLoading, setDrawerLoading] = useState(false)
  const [recentRuns, setRecentRuns] = useState<FieldCompletionRun[]>([])
  const [runsFetched, setRunsFetched] = useState(false)

  // ── Model presets ───────────────────────────────────────────────────
  const DS_MODELS = [
    { value: 'deepseek-chat', label: 'deepseek-chat（推荐，速度快）' },
    { value: 'deepseek-v4-pro', label: 'deepseek-v4-pro（高精度）' },
    { value: 'deepseek-reasoner', label: 'deepseek-reasoner（推理模型）' },
  ]
  const KIMI_MODELS = [
    { value: 'moonshot-v1-auto', label: 'moonshot-v1-auto' },
    { value: 'moonshot-v1-8k', label: 'moonshot-v1-8k' },
    { value: 'moonshot-v1-32k', label: 'moonshot-v1-32k' },
  ]
  const modelOptions = selProvider === 'kimi' ? KIMI_MODELS : DS_MODELS
  const effectiveModel = customModel || selModel

  const handleProviderChange = (p: string) => {
    setSelProvider(p)
    setSelModel(p === 'kimi' ? 'moonshot-v1-auto' : 'deepseek-chat')
  }

  const unsupported = !mapping.implemented
  const enrichableCols = useMemo(() => getEnrichableColumns(mapping), [mapping])
  const totalMissing = useMemo(() => countTotalMissing(selectedObjects, mapping), [selectedObjects, mapping])
  const canSubmit = useMemo(
    () => selectedIds.length > 0 && hasCompletableFields(selectedObjects, mapping, options.fieldScope, options.selectedFieldKeys),
    [selectedIds, selectedObjects, mapping, options.fieldScope, options.selectedFieldKeys],
  )

  // ── Reset on open ──────────────────────────────────────────────────────
  useEffect(() => {
    if (!open) return
    setStep(0)
    setSelProvider('deepseek')
    setSelModel('deepseek-chat')
    setCustomModel('')
    setOptions(DEFAULT_FIELD_COMPLETION_OPTIONS)
    setLoading(false)
    setErrorMessage(null)
    setDryRunResponse(null)
    setDryRunElapsed(0)
    setAsyncRunId(null)
    setAsyncStatus('')
    setExecDetail(null)
    setExecElapsed(0)
    setExecDone(false)
    setExecOverlayPatch({})
    setDrawerRun(null)
    setRecentRuns([])
    setRunsFetched(false)
    dryRunTriggered.current = false
    if (dryRunTimerRef.current) { clearInterval(dryRunTimerRef.current); dryRunTimerRef.current = null }
  }, [open, mapping.targetType])

  // ── Cleanup poller + mount tracking ─────────────────────────────────────
  useEffect(() => () => {
    mountedRef.current = false
    if (pollRef.current) clearInterval(pollRef.current)
  }, [])

  // ── Non-blocking async poller ──────────────────────────────────────────
  useEffect(() => {
    if (!asyncRunId) return
    if (pollRef.current) clearInterval(pollRef.current)
    execStartRef.current = Date.now()
    pollRef.current = setInterval(async () => {
      try {
        const detail = await getFieldCompletionRun(asyncRunId)
        setExecDetail(detail)
        setAsyncStatus(detail.status)
        setExecElapsed((Date.now() - execStartRef.current) / 1000)
        if (['succeeded', 'partially_succeeded', 'failed', 'cancelled'].includes(detail.status)) {
          if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
          setExecDone(true)
          setLoading(false)
          setCancelling(false)  // Clear cancelling state on terminal
          const items = detail.items ?? []
          const patch = extractOverlayPatchFromItems(items)
          setExecOverlayPatch(patch)
          // Push to recent
          const newRun: FieldCompletionRun = {
            id: detail.id, provider: detail.provider, model_name: detail.model_name,
            target_type: detail.target_type, target_count: detail.target_count,
            field_scope: detail.field_scope, selected_fields_json: detail.selected_fields_json,
            overwrite_policy: detail.overwrite_policy, dry_run: detail.dry_run,
            create_mirror_updates: detail.create_mirror_updates, create_evidence: detail.create_evidence,
            status: detail.status, request_json: detail.request_json, summary_json: detail.summary_json,
            warnings_json: detail.warnings_json, errors_json: detail.errors_json,
            created_at: detail.created_at, started_at: detail.started_at,
            completed_at: detail.completed_at, updated_at: detail.updated_at,
          }
          setRecentRuns(prev => [newRun, ...prev.filter(r => r.id !== newRun.id)].slice(0, 20))
          setRunsFetched(true)
          // C1: guard against double onCompleted (handleClose may also fire)
          if (!notifiedRef.current) {
            notifiedRef.current = true
            setTimeout(() => {
              if (mountedRef.current) onCompletedRef.current?.(patch)
            }, 500)
          }
        }
      } catch { /* polling error — transient, continue polling */ }
    }, 2000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [asyncRunId])  // H3: removed onCompleted from deps; uses stable ref

  // ── Auto-trigger dry run on step 2 ─────────────────────────────────────
  const dryRunTriggered = useRef(false)
  const dryRunTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  useEffect(() => {
    if (step !== 2 || dryRunTriggered.current) return
    dryRunTriggered.current = true
    setLoading(true)
    setDryRunElapsed(0)
    setErrorMessage(null)
    const t0 = Date.now()
    const timer = setInterval(() => setDryRunElapsed((Date.now() - t0) / 1000), 200)
    dryRunTimerRef.current = timer
    const req = buildFieldCompletionRequest(mapping, selectedIds, { ...options, provider: selProvider, modelName: effectiveModel, dryRun: true, promptOverrides: {} })
    runUniversalFieldCompletion(req)
      .then(res => {
        setDryRunResponse(res as UniversalFieldCompletionResponse)
        setLoading(false)
        clearInterval(timer)
        dryRunTimerRef.current = null
      })
      .catch(err => {
        setErrorMessage(formatFieldCompletionErrorMessage(err, t))
        setLoading(false)
        clearInterval(timer)
        dryRunTimerRef.current = null
      })
    return () => {
      // M2: clean up dry run timer on unmount / step change
      if (dryRunTimerRef.current) {
        clearInterval(dryRunTimerRef.current)
        dryRunTimerRef.current = null
      }
    }
  }, [step, mapping, selectedIds, options, selProvider, selModel, customModel])

  // ── Execute ────────────────────────────────────────────────────────────
  const handleExecute = useCallback(async () => {
    setLoading(true)
    setErrorMessage(null)
    setExecDone(false)
    setExecDetail(null)
    setExecOverlayPatch({})
    const req = buildFieldCompletionRequest(mapping, selectedIds, { ...options, provider: selProvider, modelName: effectiveModel, dryRun: false, promptOverrides: {} })
    try {
      const res = await runUniversalFieldCompletion(req)
      if ('run_id' in res && !('field_updates' in res)) {
        setAsyncRunId(res.run_id)
        setAsyncStatus('pending')
        return
      }
      // Sync fallback
      setExecDone(true)
      setLoading(false)
      const items = (res as any).items ?? []
      const patch = extractOverlayPatchFromItems(items)
      onCompleted?.(patch)
    } catch (err) {
      setErrorMessage(formatFieldCompletionErrorMessage(err, t))
      setLoading(false)
    }
  }, [mapping, selectedIds, options, onCompleted, t, selProvider, selModel, customModel])

  const [cancelling, setCancelling] = useState(false)

  const handleCancel = useCallback(async () => {
    if (!asyncRunId || cancelling) return
    setCancelling(true)  // Show "cancelling" state, keep poller running
    try {
      await cancelFieldCompletionRun(asyncRunId)
      // API succeeded — stop poller, poller will pick up final status next tick
      // or we set it now if the backend already confirmed
    } catch {
      // API failed — keep running, revert cancelling
      setCancelling(false)
    }
  }, [asyncRunId, cancelling])

  const handleClose = () => {
    // C1: only notify if poller hasn't already done so
    if (execDone && Object.keys(execOverlayPatch).length > 0 && !notifiedRef.current) {
      notifiedRef.current = true
      onCompletedRef.current?.(execOverlayPatch)
    }
    onClose()
  }

  // ── Load recent runs ───────────────────────────────────────────────────
  const loadRecentRuns = useCallback(async () => {
    setRunsFetched(true)
    try {
      const res = await listFieldCompletionRuns({ target_type: mapping.targetType as FieldCompletionTargetType, limit: 20 })
      setRecentRuns(res.items)
    } catch { /* ignore */ }
  }, [mapping.targetType])

  if (!open) return null

  const isExecuting = step === 3 && loading && !execDone
  const isExecDone = step === 3 && (execDone || (execDetail && ['succeeded', 'partially_succeeded', 'failed', 'cancelled'].includes(execDetail.status)))

  return (
    <div className="data-center-field-completion-modal">
      <div className="data-center-field-completion-backdrop" onClick={handleClose} />
      <div className="data-center-field-completion-panel data-center-field-completion-modal-panel">
        {/* ── Header ──────────────────────────────────────────────────── */}
        <div className="data-center-field-completion-modal-header">
          <h3>{t('dataCenter.fieldCompletionModalTitle')}</h3>
          <button type="button" className="btn" onClick={handleClose}>×</button>
        </div>

        {/* ── Step indicator ──────────────────────────────────────────── */}
        {!isExecuting && !isExecDone && (
          <div className="dc-wizard-steps">
            {STEP_LABELS.map((label, i) => (
              <div key={i} className={`dc-wizard-step${i === step ? ' active' : i < step ? ' done' : ''}`}>
                <div className="dc-wizard-step-dot" />
                <span>{label}</span>
              </div>
            ))}
          </div>
        )}

        {/* ── Step 0: Select ──────────────────────────────────────────── */}
        {step === 0 && (
          <div className="data-center-field-completion-modal-body">
            <div className="data-center-field-completion-section">
              <h4>目标类型</h4>
              <code>{mapping.targetType}</code>
              <span className="data-center-field-completion-meta">
                {mapping.label} · 已选 {selectedIds.length} 个对象 · {totalMissing} 个缺失字段
              </span>
            </div>
            {selectedObjects.length > 0 && (
              <div className="data-center-field-completion-section">
                <h4>缺失字段预览</h4>
                <ul className="data-center-field-completion-missing-list">
                  {selectedObjects.slice(0, 8).map(obj => (
                    <li key={obj.id}>
                      <code>{shortId(obj.id)}</code>
                      {' — '}
                      {computeMissingFields(obj, mapping).join(', ') || '✅ 完整'}
                    </li>
                  ))}
                  {selectedObjects.length > 8 && <li>… +{selectedObjects.length - 8} 个对象</li>}
                </ul>
              </div>
            )}
            {!canSubmit && <p className="data-center-field-completion-warning">当前选择无可补全字段</p>}
          </div>
        )}

        {/* ── Step 1: Configure ───────────────────────────────────────── */}
        {step === 1 && (
          <div className="data-center-field-completion-modal-body">
            <h4 style={{ fontSize: 12, fontWeight: 600, color: '#8c8c8c', margin: '0 0 8px' }}>模型配置</h4>
            <div className="data-center-field-completion-options">
              <div className="data-center-field-completion-options-row">
                <label>Provider
                  <select className="form-input" value={selProvider}
                    onChange={e => handleProviderChange(e.target.value)}>
                    <option value="deepseek">deepseek</option>
                    <option value="kimi">kimi（未配置）</option>
                  </select>
                </label>
                <label>Model
                  <select className="form-input" value={selModel}
                    onChange={e => setSelModel(e.target.value)}>
                    {modelOptions.map(m => (
                      <option key={m.value} value={m.value}>{m.label}</option>
                    ))}
                  </select>
                </label>
              </div>
              <label style={{ display: 'block', marginBottom: 12 }}>
                自定义模型名
                <input className="form-input" value={customModel}
                  placeholder="留空则使用上方选择的模型"
                  onChange={e => setCustomModel(e.target.value)}
                  style={{ width: '100%', marginTop: 4 }} />
              </label>
              {selProvider === 'kimi' && (
                <div className="data-center-field-completion-warning" style={{ marginBottom: 12 }}>
                  该 Provider 尚未配置 API Key，无法执行正式补全。
                </div>
              )}

              <h4 style={{ fontSize: 12, fontWeight: 600, color: '#8c8c8c', margin: '0 0 8px' }}>补全策略</h4>
              <div className="data-center-field-completion-options-row">
                <label>补全范围
                  <select className="form-input" value={options.fieldScope}
                    onChange={e => setOptions(p => ({ ...p, fieldScope: e.target.value as FieldCompletionScope }))}>
                    <option value="missing_only">仅缺失字段</option>
                    <option value="selected_fields">指定字段</option>
                    <option value="all_enrichable_fields">全部可补全字段</option>
                  </select>
                </label>
                <label>覆盖策略
                  <select className="form-input" value={options.overwritePolicy}
                    onChange={e => setOptions(p => ({ ...p, overwritePolicy: e.target.value as any }))}>
                    <option value="fill_missing_only">仅填充空值</option>
                    <option value="overwrite_with_review">覆盖写入</option>
                    <option value="suggest_only">仅建议不写入</option>
                  </select>
                </label>
              </div>
              {options.fieldScope === 'selected_fields' && (
                <div className="data-center-field-completion-checkbox-grid">
                  {enrichableCols.map(col => (
                    <label key={col.key} className="data-center-field-completion-check">
                      <input type="checkbox" checked={options.selectedFieldKeys.includes(col.key)}
                        onChange={e => setOptions(p => ({
                          ...p,
                          selectedFieldKeys: e.target.checked
                            ? [...p.selectedFieldKeys, col.key]
                            : p.selectedFieldKeys.filter(k => k !== col.key),
                        }))} />
                      {col.label}
                    </label>
                  ))}
                </div>
              )}
              <label className="data-center-field-completion-check">
                <input type="checkbox" checked={options.createMirrorUpdates}
                  onChange={e => setOptions(p => ({ ...p, createMirrorUpdates: e.target.checked }))} />
                写入 Mirror 数据库
              </label>
            </div>
            {errorMessage && <div className="data-center-field-completion-error"><p>{errorMessage}</p></div>}
          </div>
        )}

        {/* ── Step 2: Dry Run ─────────────────────────────────────────── */}
        {step === 2 && (
          <div className="data-center-field-completion-modal-body">
            {loading ? (
              <div style={{ textAlign: 'center', padding: 40 }}>
                <div className="dc-wizard-loading" />
                <p style={{ marginTop: 16, color: '#888' }}>正在分析… {elapsedStr(dryRunElapsed)}</p>
              </div>
            ) : dryRunResponse ? (
              <>
                <div className="dc-fc-stats-banner success" style={{ marginBottom: 12 }}>
                  <div className="dc-fc-stats-banner-title">Dry Run 预览完成</div>
                </div>
                <div className="dc-fc-stats-grid">
                  <div className="dc-fc-stats-col">
                    <div className="dc-fc-stats-col-title">预估概览</div>
                    <div className="dc-fc-stats-cards">
                      <MiniCard label="字段数" value={(dryRunResponse.summary_json as any)?.llm_fields_count ?? (dryRunResponse.summary_json as any)?.field_count ?? 0} color="#1e40af" />
                      <MiniCard label="LLM 调用" value={(dryRunResponse.summary_json as any)?.estimated_model_calls ?? 0} color="#7c3aed" />
                      <MiniCard label="包数" value={(dryRunResponse.summary_json as any)?.pack_count ?? 0} color="#0891b2" />
                    </div>
                  </div>
                  <div className="dc-fc-stats-col">
                    <div className="dc-fc-stats-col-title">费用估算</div>
                    <div className="dc-fc-stats-cards">
                      <MiniCard label="输入" value={`~${((dryRunResponse.summary_json as any)?.estimated_input_tokens ?? 0).toLocaleString()}`} color="#2563eb" />
                      <MiniCard label="输出" value={`~${((dryRunResponse.summary_json as any)?.estimated_output_tokens ?? 0).toLocaleString()}`} color="#16a34a" />
                      <MiniCard label="费用" value={(() => {
                        const inp = (dryRunResponse.summary_json as any)?.estimated_input_tokens ?? 0
                        const out = (dryRunResponse.summary_json as any)?.estimated_output_tokens ?? 0
                        const c = (inp / 1_000_000) * 1.0 + (out / 1_000_000) * 2.0
                        return c < 0.01 ? '<¥0.01' : `¥${c.toFixed(2)}`
                      })()} color="#dc2626" />
                    </div>
                  </div>
                </div>
                {dryRunResponse.field_updates && dryRunResponse.field_updates.length > 0 && (
                  <div className="dc-fc-stats-table-wrap" style={{ marginTop: 12 }}>
                    <table className="dc-fc-stats-table">
                      <thead><tr><th>字段</th><th>建议值</th></tr></thead>
                      <tbody>
                        {dryRunResponse.field_updates.slice(0, 10).map((u, i) => (
                          <tr key={i}>
                            <td className="dc-fc-stats-field">{u.field_name}</td>
                            <td className="dc-fc-stats-value">{formatValue(u.suggested_value)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            ) : (
              <p style={{ color: '#888', textAlign: 'center', padding: 40 }}>Dry run 结果将在这里展示</p>
            )}
            {errorMessage && <div className="data-center-field-completion-error"><p>{errorMessage}</p></div>}
          </div>
        )}

        {/* ── Step 3: Execute ─────────────────────────────────────────── */}
        {step === 3 && (isExecuting || isExecDone ? (
          <FieldCompletionStatsCards
            detail={execDetail}
            status={isExecDone ? (execDetail?.status ?? asyncStatus) : asyncStatus || 'running'}
            targetCount={selectedIds.length}
            elapsedSec={execElapsed}
            onCancel={!isExecDone && !cancelling ? handleCancel : undefined}
            cancelling={cancelling}
            onClose={handleClose}
          />
        ) : (
          <div className="data-center-field-completion-modal-body" style={{ textAlign: 'center', padding: 40 }}>
            <p style={{ fontSize: 16, color: '#1a1a2e', marginBottom: 8 }}>确认执行字段补全</p>
            <p style={{ color: '#888' }}>
              将对 {selectedIds.length} 个对象执行 LLM 字段补全，结果写入 Mirror 数据库。
            </p>
            <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={handleExecute} disabled={loading}>
              {loading ? '启动中…' : '✨ 开始执行'}
            </button>
          </div>
        ))}

        {/* ── Footer navigation ────────────────────────────────────────── */}
        {!(isExecuting || isExecDone) && (
          <div className="data-center-field-completion-footer">
            <button type="button" className="btn" onClick={handleClose} disabled={loading}>取消</button>
            <div style={{ display: 'flex', gap: 8 }}>
              {step > 0 && (
                <button type="button" className="btn" onClick={() => setStep(s => (s - 1) as Step)} disabled={loading}>
                  上一步
                </button>
              )}
              {step < 2 && (
                <button type="button" className="btn btn-primary"
                  onClick={() => { setStep(s => (s + 1) as Step); if (step === 1) dryRunTriggered.current = false }}
                  disabled={loading || (step === 0 && !canSubmit)}>
                  {step === 1 ? 'Dry Run 预览 →' : '下一步 →'}
                </button>
              )}
              {step === 2 && (
                <button type="button" className="btn btn-primary"
                  onClick={() => setStep(3)}
                  disabled={!dryRunResponse || loading}>
                  执行补全 →
                </button>
              )}
            </div>
          </div>
        )}

        {/* ── Recent runs tab ─────────────────────────────────────────── */}
        <details style={{ borderTop: '1px solid var(--border)', padding: '8px 22px', fontSize: 12 }}
          onToggle={e => { if ((e.target as HTMLDetailsElement).open && !runsFetched) loadRecentRuns() }}>
          <summary style={{ cursor: 'pointer', color: '#888' }}>最近补全记录 ({recentRuns.length})</summary>
          <div style={{ maxHeight: 160, overflow: 'auto', marginTop: 8 }}>
            {recentRuns.map(run => (
              <button key={run.id} type="button" className="btn btn-sm"
                style={{ display: 'block', width: '100%', textAlign: 'left', marginBottom: 2 }}
                onClick={async () => {
                  setDrawerLoading(true); setDrawerRun(null)
                  try { setDrawerRun(await getFieldCompletionRun(run.id)) } catch { /* ignore */ }
                  setDrawerLoading(false)
                }}>
                <code>{shortId(run.id)}</code>{' '}
                <ModelBadge provider={run.provider} modelName={run.model_name ?? undefined} />{' '}
                <StatusBadge status={run.status} />
                {' '}<span style={{ color: '#888' }}>{run.created_at?.slice(0, 19)}</span>
              </button>
            ))}
          </div>
        </details>

        {/* ── Side drawer ─────────────────────────────────────────────── */}
        {(drawerRun || drawerLoading) && (
          <div className="data-center-run-detail-drawer">
            <div className="data-center-run-detail-backdrop" onClick={() => { setDrawerRun(null); setDrawerLoading(false) }} />
            <div className="data-center-run-detail-panel">
              {drawerLoading ? (
                <div style={{ padding: 24, textAlign: 'center', color: '#888' }}>加载中…</div>
              ) : drawerRun ? (
                <>
                  <div className="data-center-run-detail-header">
                    <h3>补全记录详情</h3>
                    <button type="button" className="btn" onClick={() => setDrawerRun(null)}>✕</button>
                  </div>
                  <div className="data-center-run-detail-meta">
                    <span><strong>ID:</strong> <code>{shortId(drawerRun.id)}</code></span>
                    <span><ModelBadge provider={drawerRun.provider} modelName={drawerRun.model_name ?? undefined} /></span>
                    <span><StatusBadge status={drawerRun.status} /></span>
                    <span><strong>类型:</strong> {drawerRun.target_type}</span>
                    <span><strong>目标数:</strong> {drawerRun.target_count}</span>
                    <span>{drawerRun.created_at?.slice(0, 19)}</span>
                  </div>
                  <div className="data-center-run-detail-body">
                    {drawerRun.items?.length ? (
                      <FieldCompletionItemsTable items={drawerRun.items} t={t} />
                    ) : <p style={{ color: '#888' }}>暂无 items 数据</p>}
                  </div>
                </>
              ) : null}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Mini stat card ──────────────────────────────────────────────────────────

function MiniCard({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div className="dc-fc-stat-card" style={{ borderColor: `${color}20` }}>
      <div className="dc-fc-stat-value" style={{ color, fontSize: 18 }}>{value}</div>
      <div className="dc-fc-stat-label">{label}</div>
    </div>
  )
}

// ── Sub-components ──────────────────────────────────────────────────────────

function FieldCompletionStatusBadge({ status, t }: { status: string; t: (k: string) => string }) {
  if (status === 'applied_overlay' || status === 'applied') return <span className="data-center-overlay-badge">{t('dataCenter.appliedOverlay')}</span>
  if (status === 'applied_direct') return <span className="data-center-direct-badge">{t('dataCenter.appliedDirect')}</span>
  if (status === 'suggested') return <span className="data-center-suggest-badge">{t('dataCenter.suggestOnlyBadge')}</span>
  if (status.startsWith('skipped')) return <span className="data-center-skipped-badge">{t('dataCenter.skippedBadge')}</span>
  if (status === 'failed') return <span className="data-center-failed-badge">{t('dataCenter.failedBadge')}</span>
  // ── Model-tier LLM statuses ─────────────────────────────────────────────
  if (status === 'llm_v4_pro') return <span className="data-center-suggest-badge" style={{ background: '#eef2ff', color: '#4338ca', border: '1px solid #c7d2fe' }}>DeepSeek V4P 建议</span>
  if (status === 'llm_reasoner') return <span className="data-center-suggest-badge" style={{ background: '#f5f3ff', color: '#6d28d9', border: '1px solid #ddd6fe' }}>DeepSeek R1 建议</span>
  if (status === 'llm_suggested') return <span className="data-center-suggest-badge">DeepSeek V3 建议</span>
  if (status === 'llm_kimi') return <span className="data-center-suggest-badge" style={{ background: '#ecfdf5', color: '#059669', border: '1px solid #a7f3d0' }}>Kimi 建议</span>
  return <StatusBadge status={status} />
}

function FieldCompletionUpdatesTable({ updates, t }: { updates: UniversalFieldCompletionResponse['field_updates']; t: (k: string) => string }) {
  return (
    <div className="data-center-field-completion-items">
      <h4>{t('dataCenter.completionItems')}</h4>
      <div className="data-center-table-scroll">
        <table>
          <thead><tr><th>target_id</th><th>field_name</th><th>suggested</th><th>applied</th><th>status</th></tr></thead>
          <tbody>
            {updates.map((u, i) => (
              <tr key={`${u.target_id}-${u.field_name}-${i}`}>
                <td><code>{shortId(u.target_id)}</code></td>
                <td>{u.field_name}</td>
                <td>{formatCellValue(u.suggested_value)}</td>
                <td>{formatCellValue(u.applied_value)}</td>
                <td><FieldCompletionStatusBadge status={u.update_status} t={t} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function FieldCompletionItemsTable({ items, t }: { items: FieldCompletionItem[]; t: (k: string) => string }) {
  return (
    <div className="data-center-field-completion-items">
      <h4>{t('dataCenter.completionItems')}</h4>
      <div className="data-center-table-scroll">
        <table>
          <thead><tr><th>target_id</th><th>field_name</th><th>old</th><th>suggested</th><th>applied</th><th>conf</th><th>status</th></tr></thead>
          <tbody>
            {items.map(item => (
              <tr key={item.id}>
                <td><code>{shortId(item.target_id)}</code></td>
                <td>{item.field_name}</td>
                <td>{formatCellValue(item.old_value_json)}</td>
                <td>{formatCellValue(item.suggested_value_json)}</td>
                <td>{formatCellValue(item.applied_value_json)}</td>
                <td>{item.confidence ?? '—'}</td>
                <td><FieldCompletionStatusBadge status={item.update_status} t={t} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
