import { useState, useCallback, useMemo, useEffect } from 'react'
import { PageHeader } from '../components/PageHeader'
import { DataTable, type Column } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { ActionButton } from '../components/ActionButton'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Notice, type NoticeState } from '../components/Notice'
import { PipelineFilterBanner } from '../components/pipeline/PipelineFilterBanner'
import { useData } from '../hooks/useData'
import {
  fetchRuleValidationRuns, validateByBatch, validateByGenRun, validateSingleCandidate,
  type RuleValidationRun, type ValidateResult,
} from '../api/endpoints'
import { ApiError } from '../api/client'
import { readSessionIds, useSessionIds } from '../hooks/useSessionIds'
import { resolvePipelineFilters, pipelineReturnUrl } from '../utils/pipelineNavigation'
import { useI18n } from '../i18n-context'
import { MirrorValidationTab } from './MirrorValidationTab'

type Scope = 'batch' | 'gen_run' | 'candidate'
type ValidationTab = 'candidate' | 'mirror'

export function RuleValidationPage() {
  const { t } = useI18n()
  const [activeTab, setActiveTab] = useState<ValidationTab>('candidate')
  const initial = useMemo(() => resolvePipelineFilters(), [])
  const [statusFilter, setStatusFilter] = useState('')
  const [queryBatchId] = useState(initial.batch_id ?? '')
  const [queryValidationRunId] = useState(initial.validation_run_id ?? '')
  const [fromPipeline] = useState(initial.fromPipeline && Boolean(initial.batch_id))
  const [tick, setTick] = useState(0)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const onClose = useCallback(() => setNotice(null), [])

  const sess = readSessionIds()
  const { setIds } = useSessionIds()
  const [scope, setScope] = useState<Scope>('batch')
  const [idInput, setIdInput] = useState(initial.batch_id ?? sess.batch_id ?? '')
  const [running, setRunning] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [runResult, setRunResult] = useState<ValidateResult | null>(null)

  const scopeField = useMemo(() => {
    if (scope === 'batch') return t('ruleValidation.fieldBatchId')
    if (scope === 'gen_run') return t('ruleValidation.fieldGenRunId')
    return t('ruleValidation.fieldCandidateId')
  }, [scope, t])

  const columns = useMemo<Column<RuleValidationRun>[]>(() => [
    { key: 'id', header: t('common.id'), render: r => <code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code> },
    { key: 'status', header: t('common.status'), render: r => <StatusBadge status={r.status} /> },
    { key: 'candidate_count', header: t('common.total') },
    { key: 'passed_count', header: t('common.passed'), render: r => <span style={{ color: '#389e0d' }}>{r.passed_count}</span> },
    { key: 'failed_count', header: t('common.failed'), render: r => <span style={{ color: '#cf1322' }}>{r.failed_count}</span> },
    { key: 'warning_count', header: t('common.warning') },
    { key: 'skipped_count', header: t('common.skipped') },
    { key: 'created_at', header: t('common.createdAt'), render: r => r.created_at.slice(0, 16).replace('T', ' ') },
  ], [t])

  const { data, loading, error } = useData(
    () => fetchRuleValidationRuns({
      status: statusFilter || undefined,
      batch_id: queryBatchId || undefined,
      limit: 100,
    }),
    [statusFilter, queryBatchId, tick],
  )

  useEffect(() => {
    if (fromPipeline && initial.batch_id) {
      setIds({ batch_id: initial.batch_id, validation_run_id: initial.validation_run_id })
    }
  }, [fromPipeline, initial, setIds])

  function clearFilters() {
    setTick(x => x + 1)
  }

  async function doValidate() {
    const id = idInput.trim()
    if (!id) { setNotice({ type: 'error', message: t('ruleValidation.needId', { field: scopeField }) }); return }
    setRunning(true)
    setShowConfirm(false)
    try {
      let res: ValidateResult
      if (scope === 'batch') res = await validateByBatch(id)
      else if (scope === 'gen_run') res = await validateByGenRun(id)
      else res = await validateSingleCandidate(id)
      setRunResult(res)
      setNotice({ type: 'success', message: t('ruleValidation.runSuccess', { passed: res.passed_count, failed: res.failed_count, total: res.candidate_count }) })
      setTick(tick => tick + 1)
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setRunning(false)
    }
  }

  const tabs = useMemo(() => [
    { key: 'candidate' as const, label: t('ruleValidation.tabCandidate') },
    { key: 'mirror' as const, label: t('ruleValidation.tabMirror') },
  ], [t])

  return (
    <div>
      <PageHeader title={t('ruleValidation.title')} description={t('ruleValidation.description')} readonly={false} />
      <Notice notice={notice} onClose={onClose} />

      {fromPipeline && queryBatchId && (
        <PipelineFilterBanner
          batchId={queryBatchId}
          onClear={clearFilters}
          extra={queryValidationRunId ? `val_run=${queryValidationRunId.slice(0, 8)}…` : undefined}
        />
      )}

      {/* ── Tab bar ──────────────────────────────────────────────────────── */}
      <div className="card" style={{ marginBottom: 0, borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}>
        <div className="tabs">
          {tabs.map(item => (
            <button
              key={item.key}
              className={`tab-btn${activeTab === item.key ? ' active' : ''}`}
              onClick={() => setActiveTab(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {activeTab === 'mirror' ? (
        <MirrorValidationTab />
      ) : (
        <>
          <div className="card" style={{ borderTopLeftRadius: 0 }}>
        <h3 style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>{t('ruleValidation.runTitle')}</h3>
        <p style={{ fontSize: 12, color: '#888', marginBottom: 12 }}>{t('ruleValidation.runHint')}</p>
        <div className="form-row">
          <div className="form-field">
            <label className="form-label">{t('ruleValidation.scope')}</label>
            <select className="form-select" style={{ width: 180 }} value={scope} onChange={e => setScope(e.target.value as Scope)}>
              <option value="batch">{t('ruleValidation.scopeBatch')}</option>
              <option value="gen_run">{t('ruleValidation.scopeGenRun')}</option>
              <option value="candidate">{t('ruleValidation.scopeCandidate')}</option>
            </select>
          </div>
          <div className="form-field" style={{ flex: 1 }}>
            <label className="form-label">{scopeField} *</label>
            <input className="form-input" style={{ minWidth: 280 }} placeholder={t('ruleValidation.inputPlaceholder', { field: scopeField })}
              value={idInput} onChange={e => setIdInput(e.target.value)} />
          </div>
          <ActionButton label={t('ruleValidation.runBtn')} variant="primary"
            onClick={() => { if (idInput.trim()) { setShowConfirm(true) } else { setNotice({ type: 'error', message: t('ruleValidation.needId', { field: scopeField }) }) } }}
            loading={running} />
        </div>
        {runResult && (
          <div className="result-box" style={{ marginTop: 12 }}>
            <strong>{t('ruleValidation.runResult')}</strong>
            <div style={{ marginTop: 4, fontSize: 12 }}>
              <div>{t('ruleValidation.runIdField')}: <code className="text-mono">{runResult.validation_run.id}</code></div>
              <div>{t('ruleValidation.resultSummary', { passed: runResult.passed_count, failed: runResult.failed_count, total: runResult.candidate_count })}</div>
            </div>
          </div>
        )}
        {runResult?.passed_count != null && runResult.passed_count > 0 && (
          <p style={{ fontSize: 12, color: '#888', marginTop: 8 }}>
            {t('common.nextStep')}：{t('ruleValidation.nextHumanReview')}
          </p>
        )}
      </div>

      <div className="card">
        <div className="filter-bar">
          <span className="filter-label">{t('common.status')}：</span>
          <select className="filter-select" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="">{t('common.all')}</option>
            {['pending','running','completed','failed'].map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <button className="btn" style={{ marginLeft: 8 }} onClick={() => setTick(tick => tick + 1)}>{t('common.refresh')}</button>
          {fromPipeline && queryBatchId && (
            <ActionButton
              label={t('pipeline.backToPipeline')}
              variant="default"
              onClick={() => { window.location.hash = pipelineReturnUrl(queryBatchId) }}
            />
          )}
        </div>
        <DataTable
          columns={columns}
          rows={(queryValidationRunId
            ? (data?.items ?? []).filter(r => r.id === queryValidationRunId)
            : (data?.items ?? []))}
          loading={loading}
          error={error}
          total={queryValidationRunId ? (data?.items ?? []).filter(r => r.id === queryValidationRunId).length : data?.total}
          getKey={r => r.id}
          emptyText={t('ruleValidation.empty')}
        />
      </div>

      <ConfirmDialog open={showConfirm} title={t('ruleValidation.confirmTitle')}
        message={t('ruleValidation.confirmMessage', { field: scopeField, id: idInput.slice(0, 12) })}
        onConfirm={doValidate} onCancel={() => setShowConfirm(false)} confirmLabel={t('ruleValidation.confirmBtn')} loading={running} />
        </>
      )}
    </div>
  )
}
