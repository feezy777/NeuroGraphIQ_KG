import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../../i18n-context'
import { StatusBadge } from '../../../components/StatusBadge'
import { ModelBadge } from '../../../components/ModelBadge'
import { DataTable } from '../../../components/DataTable'
import { FieldCompletionStatsCards } from '../../data-center/FieldCompletionStatsCards'
import {
  listMirrorCircuits,
  runCircuitConnectionExtraction,
  getCircuitConnectionExtractionRun,
  cancelCircuitConnectionExtractionRun,
  type MirrorRegionCircuit,
  type CircuitConnectionExtractionRun,
  type CircuitConnectionExtractionRunDetail,
} from '../../../api/endpoints'
import { useData } from '../../../hooks/useData'
import { shortId } from '../../data-center/fieldCompletionUtils'

type Step = 0 | 1 | 2 | 3
const STEP_LABELS = ['选择回路', '配置参数', 'Dry Run 预览', '执行提取']
const DS_MODELS = [
  { value: 'deepseek-chat', label: 'deepseek-chat（推荐）' },
  { value: 'deepseek-v4-pro', label: 'deepseek-v4-pro（高精度）' },
  { value: 'deepseek-reasoner', label: 'deepseek-reasoner（推理模型）' },
]

interface Props {
  open: boolean
  mode: 'multi_connection' | 'main_pair'
  preSelectedIds?: string[]
  onClose: () => void
}

export function CircuitConnectionExtractionModal({ open, mode, preSelectedIds = [], onClose }: Props) {
  const { t } = useI18n()
  const [step, setStep] = useState<Step>(0)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [provider, setProvider] = useState('deepseek')
  const [model, setModel] = useState('deepseek-chat')
  const [temperature, setTemperature] = useState(0.2)
  const [maxTokens, setMaxTokens] = useState(2000)
  const [createMirrorUpdates, setCreateMirrorUpdates] = useState(true)
  const [overwritePolicy, setOverwritePolicy] = useState('fill_missing_only')
  const [running, setRunning] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [execDone, setExecDone] = useState(false)
  const [execElapsed, setExecElapsed] = useState(0)
  const [execDetail, setExecDetail] = useState<CircuitConnectionExtractionRunDetail | CircuitConnectionExtractionRun | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const execStartRef = useRef(0)

  const [dryRunResult, setDryRunResult] = useState<any>(null)
  const [dryRunLoading, setDryRunLoading] = useState(false)

  const { data: circuitsData } = useData(
    () => listMirrorCircuits({ limit: 200 }),
    [open],
  )
  const circuits = (circuitsData as any)?.items ?? []

  const modelOptions = provider === 'kimi'
    ? [{ value: 'moonshot-v1-auto', label: 'moonshot-v1-auto' }]
    : DS_MODELS

  // Reset on open
  useEffect(() => {
    if (!open) return
    setStep(0)
    setSelectedIds([...preSelectedIds])
    setProvider('deepseek')
    setModel('deepseek-chat')
    setTemperature(0.2)
    setMaxTokens(2000)
    setCreateMirrorUpdates(true)
    setOverwritePolicy('fill_missing_only')
    setRunning(false)
    setCancelling(false)
    setExecDone(false)
    setExecElapsed(0)
    setExecDetail(null)
    setRunId(null)
    setErrorMessage(null)
    setDryRunResult(null)
    setDryRunLoading(false)
  }, [open])

  // Cleanup poller
  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current)
  }, [])

  const cols = useMemo(() => [
    {
      key: '_sel', header: '', width: 36,
      render: (r: MirrorRegionCircuit) => (
        <input type="checkbox" checked={selectedIds.includes(r.id)}
          onChange={() => setSelectedIds(prev =>
            prev.includes(r.id) ? prev.filter(x => x !== r.id) : [...prev, r.id]
          )} />
      ),
    },
    { key: 'circuit_name', header: '回路名称', width: 220 },
    { key: 'circuit_type', header: '类型', width: 120 },
    { key: 'mirror_status', header: '状态', width: 80, render: (r: MirrorRegionCircuit) => <StatusBadge status={r.mirror_status} /> },
  ], [selectedIds])

  const handleDryRun = async () => {
    setDryRunLoading(true)
    setDryRunResult(null)
    try {
      const res = await runCircuitConnectionExtraction({
        mode, circuit_ids: selectedIds,
        dry_run: true, provider, model_name: model,
        temperature, max_tokens: maxTokens, create_mirror_updates: false,
      })
      setDryRunResult(res)
      setStep(2)
    } catch (e: any) {
      setErrorMessage(e.message || String(e))
    } finally {
      setDryRunLoading(false)
    }
  }

  const handleExecute = async () => {
    setRunning(true)
    setExecDone(false)
    setExecElapsed(0)
    setErrorMessage(null)
    execStartRef.current = Date.now()

    try {
      const res = await runCircuitConnectionExtraction({
        mode, circuit_ids: selectedIds,
        dry_run: false, provider, model_name: model,
        temperature, max_tokens: maxTokens, create_mirror_updates: createMirrorUpdates,
        overwrite_policy: overwritePolicy,
      })
      if ('run_id' in res) {
        setRunId(res.run_id)
        // Start polling
        pollRef.current = setInterval(async () => {
          try {
            const detail = await getCircuitConnectionExtractionRun(res.run_id)
            setExecDetail(detail)
            setExecElapsed(Math.round((Date.now() - execStartRef.current) / 1000))
            if (['succeeded', 'partially_succeeded', 'failed', 'cancelled'].includes(detail.status)) {
              if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
              setRunning(false)
              setExecDone(true)
            }
          } catch { /* ignore poll errors */ }
        }, 2000)
      } else {
        setExecDetail(res)
        setRunning(false)
        setExecDone(true)
      }
    } catch (e: any) {
      setErrorMessage(e.message || String(e))
      setRunning(false)
    }
  }

  const handleCancel = async () => {
    if (!runId || cancelling) return
    setCancelling(true)
    try {
      await cancelCircuitConnectionExtractionRun(runId)
    } catch {
      setCancelling(false)
    }
  }

  if (!open) return null

  const isExecuting = step === 3 && running && !execDone
  const isExecDone = step === 3 && execDone
  const modeLabel = mode === 'multi_connection' ? '多连接提取' : '主连接对提取'

  return (
    <div className="data-center-field-completion-modal">
      <div className="data-center-field-completion-backdrop" onClick={onClose} />
      <div className="data-center-field-completion-panel data-center-field-completion-modal-panel">
        <div className="data-center-field-completion-modal-header">
          <h3>回路 → 连接提取 — {modeLabel}</h3>
          <button type="button" className="btn" onClick={onClose}>×</button>
        </div>

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

        <div className="data-center-field-completion-modal-body">
          {step === 0 && (
            <>
              <div className="data-center-field-completion-section">
                <h4>{modeLabel} — 选择回路</h4>
                <span className="data-center-field-completion-meta">
                  {circuits.length} 个回路可用 · 已选 {selectedIds.length} 个
                </span>
              </div>
              <DataTable columns={cols} rows={circuits} getKey={r => r.id} emptyText="暂无回路数据" />
            </>
          )}

          {step === 1 && (
            <>
              <h4 style={{ fontSize: 12, fontWeight: 600, color: '#8c8c8c', margin: '0 0 8px' }}>模型配置</h4>
              <div className="data-center-field-completion-options">
                <div className="data-center-field-completion-options-row">
                  <label>Provider
                    <select className="form-input" value={provider} onChange={e => { setProvider(e.target.value); setModel(e.target.value === 'kimi' ? 'moonshot-v1-auto' : 'deepseek-chat') }}>
                      <option value="deepseek">deepseek</option>
                      <option value="kimi">kimi（未配置）</option>
                    </select>
                  </label>
                  <label>Model
                    <select className="form-input" value={model} onChange={e => setModel(e.target.value)}>
                      {modelOptions.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                    </select>
                  </label>
                </div>
                <div className="data-center-field-completion-options-row">
                  <label>温度
                    <input type="number" className="form-input" value={temperature} min={0} max={2} step={0.1}
                      onChange={e => setTemperature(parseFloat(e.target.value) || 0.2)} style={{ width: 80 }} />
                  </label>
                  <label>Max Tokens
                    <input type="number" className="form-input" value={maxTokens} min={100} max={65536} step={100}
                      onChange={e => setMaxTokens(parseInt(e.target.value) || 2000)} style={{ width: 100 }} />
                  </label>
                </div>
                <label className="data-center-field-completion-check">
                  <input type="checkbox" checked={createMirrorUpdates}
                    onChange={e => setCreateMirrorUpdates(e.target.checked)} />
                  写入 Mirror 数据库（取消勾选 = Dry Run）
                </label>
              </div>
              {errorMessage && <div className="data-center-field-completion-error"><p>{errorMessage}</p></div>}
            </>
          )}

          {step === 2 && (
            <>
              {dryRunLoading ? (
                <div style={{ textAlign: 'center', padding: 40 }}>
                  <div className="dc-wizard-loading" />
                  <p style={{ marginTop: 16, color: '#888' }}>分析中…</p>
                </div>
              ) : dryRunResult ? (
                <>
                  <div className="dc-fc-stats-banner success" style={{ marginBottom: 12 }}>
                    <div className="dc-fc-stats-banner-title">Dry Run 预览完成</div>
                  </div>
                  <div className="dc-fc-stats-grid">
                    <div className="dc-fc-stats-col">
                      <div className="dc-fc-stats-col-title">预估</div>
                      <div className="dc-fc-stats-cards">
                        <MiniCard label="回路数" value={selectedIds.length} color="#1e40af" />
                        <MiniCard label="LLM 调用" value={(dryRunResult.summary_json as any)?.estimated_model_calls ?? selectedIds.length} color="#7c3aed" />
                        <MiniCard label="输入 Token" value={`~${((dryRunResult.summary_json as any)?.estimated_input_tokens ?? 0).toLocaleString()}`} color="#2563eb" />
                        <MiniCard label="费用" value={(() => {
                          const inp = (dryRunResult.summary_json as any)?.estimated_input_tokens ?? 0
                          const cost = (inp / 1_000_000) * 1.0
                          return cost < 0.01 ? '<¥0.01' : `¥${cost.toFixed(2)}`
                        })()} color="#dc2626" />
                      </div>
                    </div>
                  </div>
                </>
              ) : (
                <p style={{ color: '#888', textAlign: 'center', padding: 40 }}>Dry run 结果将在这里展示</p>
              )}
            </>
          )}

          {step === 3 && (isExecuting || isExecDone ? (
            <FieldCompletionStatsCards
              detail={execDetail as any}
              status={isExecDone ? (execDetail?.status ?? 'succeeded') : 'running'}
              targetCount={selectedIds.length}
              elapsedSec={execElapsed}
              onCancel={!isExecDone && !cancelling ? handleCancel : undefined}
              cancelling={cancelling}
              onClose={onClose}
            />
          ) : (
            <div style={{ textAlign: 'center', padding: 40 }}>
              <p style={{ fontSize: 16, color: '#1a1a2e', marginBottom: 8 }}>确认执行提取</p>
              <p style={{ color: '#888', marginBottom: 8 }}>
                将对 {selectedIds.length} 个回路执行 LLM 连接提取（{modeLabel}）。
              </p>
              <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={handleExecute} disabled={running}>
                {running ? '启动中…' : '✨ 开始执行'}
              </button>
            </div>
          ))}
        </div>

        {!(isExecuting || isExecDone) && (
          <div className="data-center-field-completion-footer">
            <button type="button" className="btn" onClick={onClose}>取消</button>
            <div style={{ display: 'flex', gap: 8 }}>
              {step > 0 && <button type="button" className="btn" onClick={() => setStep(s => (s - 1) as Step)}>上一步</button>}
              {step === 0 && <button type="button" className="btn btn-primary" onClick={() => setStep(1)} disabled={selectedIds.length === 0}>下一步 →</button>}
              {step === 1 && <button type="button" className="btn btn-primary" onClick={() => { setStep(2); void handleDryRun() }} disabled={selectedIds.length === 0}>Dry Run 预览 →</button>}
              {step === 2 && <button type="button" className="btn btn-primary" onClick={() => setStep(3)} disabled={!dryRunResult}>执行提取 →</button>}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function MiniCard({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div className="dc-fc-stat-card" style={{ borderColor: `${color}20` }}>
      <div className="dc-fc-stat-value" style={{ color, fontSize: 18 }}>{value}</div>
      <div className="dc-fc-stat-label">{label}</div>
    </div>
  )
}
