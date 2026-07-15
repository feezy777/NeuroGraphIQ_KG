import { useState, useCallback, useMemo, useEffect } from 'react'
import { DataTable, type Column } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { ActionButton } from '../components/ActionButton'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Notice, type NoticeState } from '../components/Notice'
import { useData } from '../hooks/useData'
import {
  runMirrorValidation,
  listMirrorValidationRuns,
  getMirrorValidationRun,
  listMirrorValidationResults,
  type MirrorValidationTargetType,
  type MirrorValidationRun,
  type MirrorValidationResult,
  type MirrorValidationResponse,
} from '../api/endpoints'
import { ApiError } from '../api/client'
import { useI18n } from '../i18n-context'
import { useGlobalGranularity } from '../hooks/useGlobalGranularity'

const ALL_TARGET_TYPES: { key: MirrorValidationTargetType; label: string; category: string }[] = [
  { key: 'connection', label: 'Connection', category: 'core' },
  { key: 'function', label: 'Function', category: 'core' },
  { key: 'circuit', label: 'Circuit', category: 'core' },
  { key: 'triple', label: 'Triple', category: 'core' },
  { key: 'projection', label: 'Projection', category: 'macro' },
  { key: 'circuit_step', label: 'Circuit Step', category: 'macro' },
  { key: 'projection_function', label: 'Projection Function', category: 'macro' },
  { key: 'circuit_projection_membership', label: 'Membership', category: 'macro' },
  { key: 'circuit_projection_cross_validation_result', label: 'Cross Val Result', category: 'signal' },
  { key: 'dual_model_verification_result', label: 'Dual Model Result', category: 'signal' },
]

function targetTypeLabel(tt: string): string {
  return ALL_TARGET_TYPES.find(t => t.key === tt)?.label ?? tt
}

export function MirrorValidationTab() {
  const { t } = useI18n()
  const { granularity } = useGlobalGranularity()
  const [tick, setTick] = useState(0)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const onClose = useCallback(() => setNotice(null), [])

  // ── Run form state ──────────────────────────────────────────────────────
  const [selectedTypes, setSelectedTypes] = useState<Set<MirrorValidationTargetType>>(
    new Set(['connection', 'function', 'circuit', 'triple']),
  )
  const [resourceId, setResourceId] = useState('')
  const [batchId, setBatchId] = useState('')
  const [sourceAtlas, setSourceAtlas] = useState('')
  const [granularityLevel, setGranularityLevel] = useState<string>(granularity)
  const [dryRun, setDryRun] = useState(false)
  const [applyStatusUpdate, setApplyStatusUpdate] = useState(false)
  const [limit, setLimit] = useState('')
  const [running, setRunning] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [runResponse, setRunResponse] = useState<MirrorValidationResponse | null>(null)

  // ── Runs table state ────────────────────────────────────────────────────
  const [statusFilter, setStatusFilter] = useState('')
  const [runTypeFilter, setRunTypeFilter] = useState('')
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)

  // ── Results table state ─────────────────────────────────────────────────
  const [resultSeverityFilter, setResultSeverityFilter] = useState('')
  const [resultStatusFilter, setResultStatusFilter] = useState('')

  const hasScope = !!(resourceId.trim() || batchId.trim() || sourceAtlas.trim() || granularityLevel.trim())

  // Keep local granularityLevel in sync with global selector
  useEffect(() => {
    setGranularityLevel(granularity)
  }, [granularity])

  function toggleType(tt: MirrorValidationTargetType) {
    setSelectedTypes(prev => {
      const next = new Set(prev)
      if (next.has(tt)) next.delete(tt)
      else next.add(tt)
      return next
    })
  }

  function toggleCategory(category: string) {
    const types = ALL_TARGET_TYPES.filter(t => t.category === category).map(t => t.key)
    const allSelected = types.every(tt => selectedTypes.has(tt))
    setSelectedTypes(prev => {
      const next = new Set(prev)
      for (const tt of types) {
        if (allSelected) next.delete(tt)
        else next.add(tt)
      }
      return next
    })
  }

  async function doRun() {
    if (selectedTypes.size === 0) {
      setNotice({ type: 'error', message: t('mirrorValidation.needTargetTypes') })
      return
    }
    setRunning(true)
    setShowConfirm(false)
    try {
      const body: Parameters<typeof runMirrorValidation>[0] = {
        target_types: Array.from(selectedTypes),
        dry_run: dryRun,
        apply_status_update: applyStatusUpdate,
      }
      if (resourceId.trim()) body.scope = { ...body.scope, resource_id: resourceId.trim() }
      if (batchId.trim()) body.scope = { ...body.scope, batch_id: batchId.trim() }
      if (sourceAtlas.trim()) body.scope = { ...body.scope, source_atlas: sourceAtlas.trim() }
      if (granularityLevel.trim()) body.scope = { ...body.scope, granularity_level: granularityLevel.trim() }
      if (limit.trim()) body.limit = Number(limit.trim())

      const res = await runMirrorValidation(body)
      setRunResponse(res)
      setNotice({
        type: 'success',
        message: t('mirrorValidation.runSuccess', {
          passed: String(res.passed_count),
          failed: String(res.failed_count),
          blocked: String(res.blocked_count),
          total: String(res.result_count),
        }),
      })
      setTick(t => t + 1)
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setRunning(false)
    }
  }

  // ── Fetch runs ──────────────────────────────────────────────────────────
  const { data: runsData, loading: runsLoading, error: runsError } = useData(
    () => listMirrorValidationRuns({
      status: statusFilter || undefined,
      target_type: runTypeFilter || undefined,
      granularity_level: granularityLevel || undefined,
      limit: 50,
    }),
    [statusFilter, runTypeFilter, granularityLevel, tick],
  )

  const runColumns = useMemo<Column<MirrorValidationRun>[]>(() => [
    {
      key: 'id', header: t('common.id'),
      render: r => (
        <code
          className="text-mono"
          style={{ fontSize: 11, cursor: 'pointer', color: 'var(--primary)' }}
          onClick={() => setSelectedRunId(selectedRunId === r.id ? null : r.id)}
        >
          {r.id.slice(0, 10)}…
        </code>
      ),
    },
    {
      key: 'target_types', header: t('mirrorValidation.colTargetTypes'),
      render: r => (
        <span style={{ fontSize: 11 }}>
          {(r.target_types ?? []).map(tt => targetTypeLabel(tt)).join(', ')}
        </span>
      ),
    },
    { key: 'status', header: t('common.status'), render: r => <StatusBadge status={r.status} /> },
    { key: 'object_count', header: t('mirrorValidation.colObjects') },
    {
      key: 'passed_count', header: t('common.passed'),
      render: r => <span style={{ color: '#389e0d' }}>{r.passed_count}</span>,
    },
    {
      key: 'failed_count', header: t('common.failed'),
      render: r => <span style={{ color: '#cf1322' }}>{r.failed_count}</span>,
    },
    { key: 'warning_count', header: t('common.warning') },
    {
      key: 'blocked_count', header: t('mirrorValidation.colBlocked'),
      render: r => <span style={{ color: r.blocked_count > 0 ? '#d4380d' : undefined }}>{r.blocked_count}</span>,
    },
    {
      key: 'dry_run', header: t('mirrorValidation.colDryRun'),
      render: r => r.dry_run ? <span style={{ color: '#fa8c16' }}>DRY</span> : null,
    },
    {
      key: 'created_at', header: t('common.createdAt'),
      render: r => r.created_at?.slice(0, 16).replace('T', ' ') ?? '',
    },
  ], [t, selectedRunId])

  // ── Fetch results for selected run ──────────────────────────────────────
  const { data: resultsData, loading: resultsLoading } = useData(
    () => selectedRunId
      ? listMirrorValidationResults({
          run_id: selectedRunId,
          severity: resultSeverityFilter || undefined,
          status: resultStatusFilter || undefined,
          limit: 200,
        })
      : Promise.resolve({ items: [], total: 0, limit: 0, offset: 0 }),
    [selectedRunId, resultSeverityFilter, resultStatusFilter],
  )

  const resultColumns = useMemo<Column<MirrorValidationResult>[]>(() => [
    { key: 'target_type', header: t('mirrorValidation.colType'), render: r => targetTypeLabel(r.target_type) },
    {
      key: 'target_id', header: t('mirrorValidation.colTargetId'),
      render: r => <code className="text-mono" style={{ fontSize: 10 }}>{r.target_id.slice(0, 10)}…</code>,
    },
    { key: 'rule_code', header: t('mirrorValidation.colRuleCode') },
    {
      key: 'severity', header: t('mirrorValidation.colSeverity'),
      render: r => {
        const colors: Record<string, string> = { info: '#1890ff', warning: '#fa8c16', error: '#cf1322', blocker: '#d4380d' }
        return <span style={{ color: colors[r.severity] ?? '#888', fontWeight: 600, fontSize: 12 }}>{r.severity.toUpperCase()}</span>
      },
    },
    {
      key: 'status', header: t('common.status'),
      render: r => <StatusBadge status={r.status} />,
    },
    { key: 'message', header: t('mirrorValidation.colMessage') },
  ], [t])

  // Build confirm message
  const confirmMsg = useMemo(() => {
    const types = Array.from(selectedTypes).map(tt => targetTypeLabel(tt)).join(', ')
    let extra = ''
    if (hasScope) extra = `\nScope: ${[resourceId && `resource=${resourceId}`, batchId && `batch=${batchId}`, sourceAtlas && `atlas=${sourceAtlas}`, granularityLevel && `gran=${granularityLevel}`].filter(Boolean).join(', ')}`
    if (dryRun) extra += '\n⚠ Dry Run mode'
    if (applyStatusUpdate) extra += '\n⚠ Will update mirror_status → rule_checked'
    return t('mirrorValidation.confirmMessage', { types, extra })
  }, [selectedTypes, resourceId, batchId, sourceAtlas, granularityLevel, dryRun, applyStatusUpdate, hasScope, t])

  return (
    <div>
      <Notice notice={notice} onClose={onClose} />

      {/* ── Run Section ──────────────────────────────────────────────────── */}
      <div className="card">
        <h3 style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>{t('mirrorValidation.runTitle')}</h3>
        <p style={{ fontSize: 12, color: '#888', marginBottom: 12 }}>{t('mirrorValidation.runHint')}</p>

        {/* Target type selection */}
        <div style={{ marginBottom: 12 }}>
          <label className="form-label" style={{ marginBottom: 6, display: 'block' }}>
            {t('mirrorValidation.targetTypes')} *
          </label>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
            {(['core', 'macro', 'signal'] as const).map(cat => {
              const catTypes = ALL_TARGET_TYPES.filter(t => t.category === cat)
              const allSel = catTypes.every(tt => selectedTypes.has(tt.key))
              const someSel = catTypes.some(tt => selectedTypes.has(tt.key))
              return (
                <label
                  key={cat}
                  className="checkbox-label"
                  style={{
                    fontSize: 11,
                    padding: '2px 8px',
                    border: '1px solid var(--border)',
                    borderRadius: 4,
                    cursor: 'pointer',
                    background: allSel ? 'var(--primary-light, #e6f7ff)' : someSel ? '#fafafa' : undefined,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={allSel}
                    ref={el => { if (el) el.indeterminate = someSel && !allSel }}
                    onChange={() => toggleCategory(cat)}
                    style={{ marginRight: 4 }}
                  />
                  {t(`mirrorValidation.cat${cat.charAt(0).toUpperCase() + cat.slice(1)}`)}
                </label>
              )
            })}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {ALL_TARGET_TYPES.map(tt => (
              <label
                key={tt.key}
                className="checkbox-label"
                style={{
                  fontSize: 11,
                  padding: '1px 6px',
                  border: '1px solid var(--border)',
                  borderRadius: 3,
                  cursor: 'pointer',
                  background: selectedTypes.has(tt.key) ? 'var(--primary-light, #e6f7ff)' : undefined,
                }}
              >
                <input
                  type="checkbox"
                  checked={selectedTypes.has(tt.key)}
                  onChange={() => toggleType(tt.key)}
                  style={{ marginRight: 3 }}
                />
                {tt.label}
              </label>
            ))}
          </div>
        </div>

        {/* Scope fields */}
        <div style={{ marginBottom: 12 }}>
          <label className="form-label" style={{ marginBottom: 4, display: 'block' }}>
            {t('mirrorValidation.scope')} <span style={{ color: '#888', fontWeight: 400 }}>({t('common.optional')})</span>
          </label>
          <div className="form-row" style={{ gap: 8 }}>
            <div className="form-field" style={{ flex: 1 }}>
              <label className="form-label" style={{ fontSize: 11 }}>{t('mirrorValidation.resourceId')}</label>
              <input className="form-input" placeholder="UUID" value={resourceId} onChange={e => setResourceId(e.target.value)} />
            </div>
            <div className="form-field" style={{ flex: 1 }}>
              <label className="form-label" style={{ fontSize: 11 }}>{t('mirrorValidation.batchId')}</label>
              <input className="form-input" placeholder="UUID" value={batchId} onChange={e => setBatchId(e.target.value)} />
            </div>
            <div className="form-field" style={{ flex: 1 }}>
              <label className="form-label" style={{ fontSize: 11 }}>{t('mirrorValidation.sourceAtlas')}</label>
              <input className="form-input" placeholder="e.g. AAL3" value={sourceAtlas} onChange={e => setSourceAtlas(e.target.value)} />
            </div>
            <div className="form-field" style={{ flex: 1 }}>
              <label className="form-label" style={{ fontSize: 11 }}>{t('mirrorValidation.granularityLevel')}</label>
              <input className="form-input" placeholder="e.g. macro_clinical" value={granularityLevel} onChange={e => setGranularityLevel(e.target.value)} />
            </div>
          </div>
        </div>

        {/* Advanced options */}
        <div style={{ marginBottom: 12 }}>
          <details style={{ fontSize: 12 }}>
            <summary style={{ cursor: 'pointer', color: '#888', marginBottom: 8 }}>
              {t('mirrorValidation.advanced')}
            </summary>
            <div className="form-row" style={{ gap: 12, alignItems: 'center', marginTop: 8 }}>
              <label className="checkbox-label" style={{ fontSize: 12 }}>
                <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} style={{ marginRight: 4 }} />
                {t('mirrorValidation.dryRun')}
              </label>
              <label className="checkbox-label" style={{ fontSize: 12 }}>
                <input type="checkbox" checked={applyStatusUpdate} onChange={e => setApplyStatusUpdate(e.target.checked)} style={{ marginRight: 4 }} />
                {t('mirrorValidation.applyStatusUpdate')}
              </label>
              <div className="form-field" style={{ maxWidth: 100 }}>
                <label className="form-label" style={{ fontSize: 11 }}>{t('mirrorValidation.limit')}</label>
                <input className="form-input" type="number" min={1} max={5000} placeholder="1000" value={limit} onChange={e => setLimit(e.target.value)} />
              </div>
            </div>
          </details>
        </div>

        <ActionButton
          label={t('mirrorValidation.runBtn')}
          variant="primary"
          onClick={() => {
            if (selectedTypes.size === 0) {
              setNotice({ type: 'error', message: t('mirrorValidation.needTargetTypes') })
            } else {
              setShowConfirm(true)
            }
          }}
          loading={running}
        />

        {/* Run result summary */}
        {runResponse && (
          <div className="result-box" style={{ marginTop: 12 }}>
            <strong>{runResponse.dry_run ? t('mirrorValidation.dryRunResult') : t('mirrorValidation.runResult')}</strong>
            <div style={{ marginTop: 4, fontSize: 12 }}>
              {runResponse.run_id && (
                <div>{t('mirrorValidation.runIdField')}: <code className="text-mono">{runResponse.run_id}</code></div>
              )}
              <div>
                {t('mirrorValidation.resultSummary', {
                  passed: String(runResponse.passed_count),
                  warning: String(runResponse.warning_count),
                  failed: String(runResponse.failed_count),
                  blocked: String(runResponse.blocked_count),
                  total: String(runResponse.result_count),
                })}
              </div>
              {runResponse.target_counts && Object.keys(runResponse.target_counts).length > 0 && (
                <div style={{ marginTop: 4, fontSize: 11, color: '#888' }}>
                  {Object.entries(runResponse.target_counts).map(([tt, count]) => (
                    <span key={tt} style={{ marginRight: 10 }}>{targetTypeLabel(tt)}: {count}</span>
                  ))}
                </div>
              )}
              {runResponse.warnings && runResponse.warnings.length > 0 && (
                <div style={{ marginTop: 4, fontSize: 11, color: '#fa8c16' }}>
                  {runResponse.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* ── Runs Table ────────────────────────────────────────────────────── */}
      <div className="card">
        <div className="filter-bar">
          <span className="filter-label">{t('common.status')}:</span>
          <select className="filter-select" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="">{t('common.all')}</option>
            {['pending', 'running', 'completed', 'failed'].map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <span className="filter-label" style={{ marginLeft: 12 }}>{t('mirrorValidation.filterTargetType')}:</span>
          <select className="filter-select" value={runTypeFilter} onChange={e => setRunTypeFilter(e.target.value)}>
            <option value="">{t('common.all')}</option>
            {ALL_TARGET_TYPES.map(tt => <option key={tt.key} value={tt.key}>{tt.label}</option>)}
          </select>
          <button className="btn" style={{ marginLeft: 8 }} onClick={() => setTick(t => t + 1)}>
            {t('common.refresh')}
          </button>
        </div>

        <DataTable
          columns={runColumns}
          rows={runsData?.items ?? []}
          loading={runsLoading}
          error={runsError}
          total={runsData?.total}
          getKey={r => r.id}
          emptyText={t('mirrorValidation.emptyRuns')}
        />

        {/* ── Results detail for selected run ────────────────────────────── */}
        {selectedRunId && (
          <div style={{ marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <h4 style={{ fontSize: 12, fontWeight: 600, margin: 0 }}>
                {t('mirrorValidation.resultsForRun')}: <code className="text-mono" style={{ fontSize: 11 }}>{selectedRunId.slice(0, 12)}…</code>
              </h4>
              <button className="btn" style={{ fontSize: 11 }} onClick={() => setSelectedRunId(null)}>
                ✕ {t('common.close')}
              </button>
            </div>
            <div className="filter-bar">
              <span className="filter-label">{t('mirrorValidation.colSeverity')}:</span>
              <select className="filter-select" value={resultSeverityFilter} onChange={e => setResultSeverityFilter(e.target.value)}>
                <option value="">{t('common.all')}</option>
                {['info', 'warning', 'error', 'blocker'].map(s => <option key={s} value={s}>{s.toUpperCase()}</option>)}
              </select>
              <span className="filter-label" style={{ marginLeft: 12 }}>{t('common.status')}:</span>
              <select className="filter-select" value={resultStatusFilter} onChange={e => setResultStatusFilter(e.target.value)}>
                <option value="">{t('common.all')}</option>
                {['passed', 'warning', 'failed', 'blocked'].map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <DataTable
              columns={resultColumns}
              rows={resultsData?.items ?? []}
              loading={resultsLoading}
              total={resultsData?.total}
              getKey={r => r.id}
              emptyText={t('mirrorValidation.emptyResults')}
            />
          </div>
        )}
      </div>

      <ConfirmDialog
        open={showConfirm}
        title={t('mirrorValidation.confirmTitle')}
        message={confirmMsg}
        onConfirm={doRun}
        onCancel={() => setShowConfirm(false)}
        confirmLabel={t('mirrorValidation.confirmBtn')}
        loading={running}
      />
    </div>
  )
}
