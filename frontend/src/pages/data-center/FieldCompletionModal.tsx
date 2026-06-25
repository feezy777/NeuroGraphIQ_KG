import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CopyButton } from '../../components/CopyButton'
import { StatusBadge } from '../../components/StatusBadge'
import { useI18n } from '../../i18n-context'
import {
  getFieldCompletionRun,
  listFieldCompletionRuns,
  runUniversalFieldCompletion,
  type FieldCompletionItem,
  type FieldCompletionRun,
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
import { PromptWorkbenchSection } from './PromptWorkbenchSection'

type ModalMode = 'preview_input' | 'dry_run_result' | 'execution_result' | 'error'
type ModalTab = 'current' | 'recent_runs'

interface Props {
  open: boolean
  mapping: FormalFieldMapping
  selectedObjects: FormalRow[]
  selectedIds: string[]
  onClose: () => void
  onCompleted?: (overlayPatch?: OverlayPatch) => void
}

export function FieldCompletionModal({
  open,
  mapping,
  selectedObjects,
  selectedIds,
  onClose,
  onCompleted,
}: Props) {
  const { t } = useI18n()
  const [tab, setTab] = useState<ModalTab>('current')
  const [mode, setMode] = useState<ModalMode>('preview_input')
  const [options, setOptions] = useState<FieldCompletionFormOptions>(DEFAULT_FIELD_COMPLETION_OPTIONS)
  const [promptOverrides, setPromptOverrides] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [response, setResponse] = useState<UniversalFieldCompletionResponse | null>(null)
  const [dryRunDone, setDryRunDone] = useState(false)
  const [showPromptPreview, setShowPromptPreview] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [elapsedMs, setElapsedMs] = useState(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [recentRuns, setRecentRuns] = useState<FieldCompletionRun[]>([])
  const [runsLoading, setRunsLoading] = useState(false)
  const [runsApiUnavailable, setRunsApiUnavailable] = useState(false)
  const [runsFetchAttempted, setRunsFetchAttempted] = useState(false)
  const [selectedRunItems, setSelectedRunItems] = useState<FieldCompletionItem[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [executionItems, setExecutionItems] = useState<FieldCompletionItem[]>([])

  const unsupported = !mapping.implemented
  const enrichableCols = useMemo(() => getEnrichableColumns(mapping), [mapping])
  const totalMissing = useMemo(
    () => countTotalMissing(selectedObjects, mapping),
    [selectedObjects, mapping],
  )
  const canSubmit = useMemo(
    () => selectedIds.length > 0 && hasCompletableFields(
      selectedObjects,
      mapping,
      options.fieldScope,
      options.selectedFieldKeys,
    ),
    [selectedIds, selectedObjects, mapping, options.fieldScope, options.selectedFieldKeys],
  )

  useEffect(() => {
    if (!open) return
    setTab('current')
    setMode('preview_input')
    setOptions(DEFAULT_FIELD_COMPLETION_OPTIONS)
    setPromptOverrides({})
    setLoading(false)
    setErrorMessage(null)
    setResponse(null)
    setDryRunDone(false)
    setShowPromptPreview(false)
    setShowConfirm(false)
    setRecentRuns([])
    setRunsApiUnavailable(false)
    setRunsFetchAttempted(false)
    setSelectedRunItems([])
    setSelectedRunId(null)
    setExecutionItems([])
  }, [open, mapping.targetType, selectedIds.join(',')])

  const patchOptions = useCallback((patch: Partial<FieldCompletionFormOptions>) => {
    setOptions(prev => ({ ...prev, ...patch }))
  }, [])

  const runCompletion = useCallback(async (dryRun: boolean) => {
    if (unsupported || selectedIds.length === 0) return
    setLoading(true)
    setErrorMessage(null)
    setShowConfirm(false)
    // Start timer
    const startTime = Date.now()
    timerRef.current = setInterval(() => setElapsedMs(Date.now() - startTime), 200)
    const req = buildFieldCompletionRequest(mapping, selectedIds, {
      ...options,
      dryRun,
      promptOverrides,
    })
    try {
      const res = await runUniversalFieldCompletion(req)
      setResponse(res)
      if (dryRun) {
        setDryRunDone(true)
        setMode('dry_run_result')
        setExecutionItems([])
      } else {
        setMode('execution_result')
        setExecutionItems([])
        let overlayPatch: OverlayPatch = {}
        if (res.run_id) {
          try {
            const detail = await getFieldCompletionRun(res.run_id)
            setExecutionItems(detail.items)
            overlayPatch = extractOverlayPatchFromItems(detail.items)
          } catch {
            overlayPatch = extractOverlayPatchFromFieldUpdates(res.field_updates)
          }
        } else {
          overlayPatch = extractOverlayPatchFromFieldUpdates(res.field_updates)
        }
        onCompleted?.(overlayPatch)
      }
    } catch (err) {
      setErrorMessage(formatFieldCompletionErrorMessage(err, t))
      setMode('error')
    } finally {
      if (timerRef.current) clearInterval(timerRef.current)
      setLoading(false)
      setElapsedMs(0)
    }
  }, [unsupported, selectedIds, mapping, options, promptOverrides, onCompleted, t])

  const loadRecentRuns = useCallback(async () => {
    setRunsLoading(true)
    setRunsFetchAttempted(true)
    try {
      const res = await listFieldCompletionRuns({
        target_type: mapping.targetType as FieldCompletionTargetType,
        limit: 20,
      })
      setRecentRuns(res.items)
      setRunsApiUnavailable(false)
    } catch (err) {
      if (classifyFieldCompletionError(err) === 'api_not_enabled') {
        setRunsApiUnavailable(true)
        setRecentRuns([])
      } else {
        setErrorMessage(formatFieldCompletionErrorMessage(err, t))
      }
    } finally {
      setRunsLoading(false)
    }
  }, [mapping.targetType, t])

  const loadRunDetail = useCallback(async (runId: string) => {
    setRunsLoading(true)
    setSelectedRunId(runId)
    try {
      const detail = await getFieldCompletionRun(runId)
      setSelectedRunItems(detail.items)
    } catch (err) {
      setErrorMessage(formatFieldCompletionErrorMessage(err, t))
    } finally {
      setRunsLoading(false)
    }
  }, [t])

  useEffect(() => {
    if (
      open
      && tab === 'recent_runs'
      && !unsupported
      && !runsFetchAttempted
      && !runsApiUnavailable
    ) {
      void loadRecentRuns()
    }
  }, [open, tab, unsupported, runsFetchAttempted, runsApiUnavailable, loadRecentRuns])

  if (!open) return null

  const promptPreviewText = response?.prompt_preview
    ? JSON.stringify(response.prompt_preview, null, 2)
    : ''

  return (
    <div className="data-center-field-completion-modal">
      <div className="data-center-field-completion-backdrop" onClick={onClose} />
      <div className="data-center-field-completion-panel data-center-field-completion-modal-panel">
        <div className="data-center-field-completion-modal-header">
          <h3>{t('dataCenter.fieldCompletionModalTitle')}</h3>
          <button type="button" className="btn" onClick={onClose}>×</button>
        </div>

        <div className="data-center-field-completion-boundary">
          <p>{t('dataCenter.mirrorOnlyBoundary')}</p>
          <p>{t('dataCenter.noFinalNoKg')}</p>
          <p>{t('dataCenter.noAutoApprovePromotion')}</p>
        </div>

        <PromptWorkbenchSection
          modeLabel={t('dataCenter.fieldCompletionModalTitle')}
          dryRunPreview={(response?.prompt_preview as Record<string, unknown> | undefined) ?? null}
          promptOverrides={promptOverrides}
          onPromptOverridesChange={setPromptOverrides}
        />

        <div className="data-center-field-completion-tabs">
          <button
            type="button"
            className={`data-center-tab${tab === 'current' ? ' data-center-tab-active' : ''}`}
            onClick={() => setTab('current')}
          >
            {mode === 'execution_result' || mode === 'dry_run_result'
              ? t('dataCenter.completionRun')
              : t('dataCenter.fieldCompletion')}
          </button>
          <button
            type="button"
            className={`data-center-tab${tab === 'recent_runs' ? ' data-center-tab-active' : ''}`}
            onClick={() => setTab('recent_runs')}
          >
            {t('dataCenter.recentCompletionRuns')}
          </button>
        </div>

        {tab === 'current' && (
          <div className="data-center-field-completion-modal-body">
            {unsupported ? (
              <div className="data-center-field-completion-error">
                <p>{t('dataCenter.unsupportedTarget')}</p>
                <p>{mapping.mirrorTable} — {mapping.label}</p>
              </div>
            ) : (
              <>
                <div className="data-center-field-completion-grid">
                  <div className="data-center-field-completion-section">
                    <h4>{t('dataCenter.fieldCompletionTargetType')}</h4>
                    <code>{mapping.targetType}</code>
                    <span className="data-center-field-completion-meta">
                      {mapping.label} · {t('dataCenter.fieldCompletionSelectedCount', { count: selectedIds.length })}
                      · {t('dataCenter.missingFields')} {totalMissing}
                    </span>
                  </div>

                  {selectedObjects.length > 0 && (
                    <div className="data-center-field-completion-section">
                      <h4>{t('dataCenter.missingFields')}</h4>
                      <ul className="data-center-field-completion-missing-list">
                        {selectedObjects.slice(0, 8).map(obj => (
                          <li key={obj.id}>
                            <code>{shortId(obj.id)}</code>
                            {' — '}
                            {computeMissingFields(obj, mapping).join(', ') || t('dataCenter.complete')}
                          </li>
                        ))}
                        {selectedObjects.length > 8 && (
                          <li>… +{selectedObjects.length - 8}</li>
                        )}
                      </ul>
                    </div>
                  )}
                </div>

                {(mode === 'preview_input' || mode === 'error') && (
                  <div className="data-center-field-completion-options">
                    <div className="data-center-field-completion-options-row">
                      <label>
                        {t('dataCenter.fieldCompletionProvider')}
                        <input
                          className="form-input"
                          value={options.provider}
                          onChange={e => patchOptions({ provider: e.target.value })}
                        />
                      </label>
                      <label>
                        {t('dataCenter.fieldCompletionModel')}
                        <input
                          className="form-input"
                          value={options.modelName}
                          onChange={e => patchOptions({ modelName: e.target.value })}
                        />
                      </label>
                    </div>
                    <div className="data-center-field-completion-options-row">
                      <label>
                        {t('dataCenter.fieldScope')}
                        <select
                          className="form-input"
                          value={options.fieldScope}
                          onChange={e => patchOptions({ fieldScope: e.target.value as FieldCompletionScope })}
                        >
                          <option value="missing_only">{t('dataCenter.fieldScopeMissingOnly')}</option>
                          <option value="selected_fields">{t('dataCenter.fieldScopeSelectedFields')}</option>
                          <option value="all_enrichable_fields">{t('dataCenter.fieldScopeAllEnrichable')}</option>
                        </select>
                      </label>
                      <label>
                        {t('dataCenter.overwritePolicy')}
                        <select
                          className="form-input"
                          value={options.overwritePolicy}
                          onChange={e => patchOptions({
                            overwritePolicy: e.target.value as FieldCompletionFormOptions['overwritePolicy'],
                          })}
                        >
                          <option value="fill_missing_only">{t('dataCenter.overwriteFillMissingOnly')}</option>
                          <option value="suggest_only">{t('dataCenter.overwriteSuggestOnly')}</option>
                          <option value="overwrite_with_review">{t('dataCenter.overwriteWithReview')}</option>
                        </select>
                      </label>
                    </div>

                    {options.fieldScope === 'selected_fields' && (
                      <div className="data-center-field-completion-section">
                        <h4>{t('dataCenter.selectedFields')}</h4>
                        <div className="data-center-field-completion-checkbox-grid">
                          {enrichableCols.map(col => (
                            <label key={col.key} className="data-center-field-completion-check">
                              <input
                                type="checkbox"
                                checked={options.selectedFieldKeys.includes(col.key)}
                                onChange={e => {
                                  const next = e.target.checked
                                    ? [...options.selectedFieldKeys, col.key]
                                    : options.selectedFieldKeys.filter(k => k !== col.key)
                                  patchOptions({ selectedFieldKeys: next })
                                }}
                              />
                              {col.label}
                            </label>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="data-center-field-completion-checkbox-grid">
                      <label className="data-center-field-completion-check">
                        <input
                          type="checkbox"
                          checked={options.includeExistingEvidence}
                          onChange={e => patchOptions({ includeExistingEvidence: e.target.checked })}
                        />
                        {t('dataCenter.includeEvidence')}
                      </label>
                      <label className="data-center-field-completion-check">
                        <input
                          type="checkbox"
                          checked={options.includeRelatedObjects}
                          onChange={e => patchOptions({ includeRelatedObjects: e.target.checked })}
                        />
                        {t('dataCenter.includeRelatedObjects')}
                      </label>
                      <label className="data-center-field-completion-check">
                        <input
                          type="checkbox"
                          checked={options.includeProvenance}
                          onChange={e => patchOptions({ includeProvenance: e.target.checked })}
                        />
                        {t('dataCenter.includeProvenance')}
                      </label>
                      <label className="data-center-field-completion-check">
                        <input
                          type="checkbox"
                          checked={options.createMirrorUpdates}
                          onChange={e => patchOptions({ createMirrorUpdates: e.target.checked })}
                        />
                        {t('dataCenter.createMirrorUpdates')}
                      </label>
                      <label className="data-center-field-completion-check">
                        <input
                          type="checkbox"
                          checked={options.createEvidence}
                          onChange={e => patchOptions({ createEvidence: e.target.checked })}
                        />
                        {t('dataCenter.createEvidence')}
                      </label>
                    </div>

                    {!canSubmit && (
                      <p className="data-center-field-completion-warning">{t('dataCenter.noCompletableFields')}</p>
                    )}
                  </div>
                )}

                {errorMessage && (
                  <div className="data-center-field-completion-error">
                    <p>{errorMessage}</p>
                  </div>
                )}

                {response && (mode === 'dry_run_result' || mode === 'execution_result') && (
                  <FieldCompletionResultView
                    response={response}
                    items={executionItems}
                    t={t}
                  />
                )}

                {response?.prompt_preview && (mode === 'dry_run_result' || mode === 'execution_result') && (
                  <div className="data-center-field-completion-preview">
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => setShowPromptPreview(v => !v)}
                    >
                      {t('dataCenter.promptPreview')} {showPromptPreview ? '▾' : '▸'}
                    </button>
                    {showPromptPreview && (
                      <div className="data-center-field-completion-preview-body">
                        <CopyButton value={promptPreviewText} label={t('dataCenter.copyId')} />
                        <pre>{promptPreviewText.slice(0, 8000)}{promptPreviewText.length > 8000 ? '\n…' : ''}</pre>
                      </div>
                    )}
                  </div>
                )}

                {showConfirm && (
                  <div className="data-center-field-completion-confirm">
                    <h4>{t('dataCenter.confirmFieldCompletion')}</h4>
                    <ul>
                      <li>{t('dataCenter.confirmFieldCompletionDeepSeek')}</li>
                      <li>{options.provider} / {options.modelName}</li>
                      <li>{mapping.targetType} · {selectedIds.length} objects</li>
                      <li>{options.fieldScope} · {options.overwritePolicy}</li>
                      <li>{t('dataCenter.confirmFieldCompletionMirrorOnly')}</li>
                      <li>{t('dataCenter.confirmFieldCompletionNoFinalKg')}</li>
                      <li>{t('dataCenter.confirmFieldCompletionFillMissing')}</li>
                      <li>{t('dataCenter.mirrorOnlyBoundary')}</li>
                    </ul>
                    <div className="data-center-field-completion-footer">
                      <button type="button" className="btn" onClick={() => setShowConfirm(false)}>
                        {t('llm.workflow.closeCandidateDetail')}
                      </button>
                      <button
                        type="button"
                        className="btn btn-primary"
                        disabled={loading}
                        onClick={() => void runCompletion(false)}
                      >
                        {t('dataCenter.executeFieldCompletion')}
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {tab === 'recent_runs' && (
          <div className="data-center-field-completion-modal-body">
            {runsLoading && <p>{t('dataCenter.loading')}</p>}
            {runsApiUnavailable && (
              <p className="data-center-field-completion-warning">{t('dataCenter.fieldCompletionRunsUnavailable')}</p>
            )}
            {!runsLoading && !runsApiUnavailable && recentRuns.length === 0 && (
              <p>{t('dataCenter.noCompletionRuns')}</p>
            )}
            <ul className="data-center-field-completion-runs-list">
              {recentRuns.map(run => (
                <li key={run.id}>
                  <button type="button" className="btn btn-sm" onClick={() => void loadRunDetail(run.id)}>
                    <code>{shortId(run.id)}</code>
                    {' '}
                    <StatusBadge status={run.status} />
                    {' '}
                    {run.created_at?.slice(0, 19)}
                  </button>
                </li>
              ))}
            </ul>
            {selectedRunId && selectedRunItems.length > 0 && (
              <FieldCompletionItemsTable items={selectedRunItems} t={t} />
            )}
          </div>
        )}

        {tab === 'current' && !unsupported && !showConfirm && (
          <>
            {/* Loading progress bar */}
            {loading && (
              <div style={{ padding: '14px 18px', borderTop: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
                  <span>⏳ 正在调用 LLM 处理 {selectedIds.length} 个对象…</span>
                  <span style={{ color: '#888' }}>{(elapsedMs / 1000).toFixed(1)}s</span>
                </div>
                <div style={{ height: 8, background: '#e8e8e8', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{
                    height: '100%', width: '100%', borderRadius: 4,
                    background: 'linear-gradient(90deg, var(--primary) 0%, #69b1ff 50%, var(--primary) 100%)',
                    backgroundSize: '200% 100%',
                    animation: 'modal-progress-pulse 1.5s infinite',
                  }} />
                </div>
                <div style={{ fontSize: 11, color: '#888', marginTop: 4 }}>
                  {elapsedMs < 3000 ? '正在发送请求…' : elapsedMs < 10000 ? 'LLM 处理中，请耐心等待…' : '仍在处理中，复杂请求可能需要更长时间…'}
                </div>
              </div>
            )}
            <div className="data-center-field-completion-footer">
              <button type="button" className="btn" onClick={onClose} disabled={loading}>
                {t('llm.workflow.closeCandidateDetail')}
              </button>
              {(mode === 'execution_result') && onCompleted && (
                <button type="button" className="btn" onClick={() => onCompleted()}>
                  {t('dataCenter.refreshAfterCompletion')}
                </button>
              )}
              <button
                type="button"
                className="btn"
                disabled={loading || !canSubmit || selectedIds.length === 0}
                onClick={() => void runCompletion(true)}
              >
                {loading ? '…' : t('dataCenter.generateDryRunPreview')}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={loading || !canSubmit || selectedIds.length === 0 || (!dryRunDone && mode !== 'execution_result')}
                title={!dryRunDone ? t('dataCenter.dryRunFirstHint') : undefined}
                onClick={() => setShowConfirm(true)}
              >
                {t('dataCenter.executeFieldCompletion')}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function FieldCompletionResultView({
  response,
  items,
  t,
}: {
  response: UniversalFieldCompletionResponse
  items: FieldCompletionItem[]
  t: (key: string, params?: Record<string, string | number>) => string
}) {
  const overlayCount = response.applied_overlay_count
    ?? response.summary_json?.applied_overlay_count
    ?? response.field_updates?.filter(
      u => u.update_status === 'applied_overlay' || u.update_status === 'applied',
    ).length
    ?? 0
  const directCount = response.applied_direct_count
    ?? response.summary_json?.applied_direct_count
    ?? response.field_updates?.filter(u => u.update_status === 'applied_direct').length
    ?? 0

  const displayItems = items.length > 0 ? items : null

  return (
    <div className="data-center-field-completion-result">
      <div className="data-center-field-completion-summary">
        <span><strong>run_id:</strong> <code>{shortId(response.run_id)}</code></span>
        <span><StatusBadge status={response.status} /></span>
        <span>{t('dataCenter.updatedCount')}: {response.updated_count ?? 0}</span>
        <span>{t('dataCenter.appliedOverlayCount')}: {overlayCount}</span>
        <span>{t('dataCenter.appliedDirectCount')}: {directCount}</span>
        <span>{t('dataCenter.suggestedCount')}: {response.suggested_count ?? 0}</span>
        <span>{t('dataCenter.skippedCount')}: {response.skipped_count ?? 0}</span>
        <span>{t('dataCenter.failedCount')}: {response.failed_count ?? 0}</span>
      </div>
      {(response.warnings?.length ?? 0) > 0 && (
        <div className="data-center-field-completion-warning">
          {response.warnings!.map((w, i) => <p key={i}>{w}</p>)}
        </div>
      )}
      {(response.errors?.length ?? 0) > 0 && (
        <details className="data-center-field-completion-error">
          <summary>{t('dataCenter.fieldCompletionErrorDetails')}</summary>
          {response.errors!.map((e, i) => <p key={i}>{e}</p>)}
        </details>
      )}
      {displayItems && displayItems.length > 0 ? (
        <FieldCompletionItemsTable items={displayItems} t={t} />
      ) : response.field_updates && response.field_updates.length > 0 ? (
        <FieldCompletionUpdatesTable updates={response.field_updates} t={t} />
      ) : null}
    </div>
  )
}

function FieldCompletionStatusBadge({
  status,
  t,
}: {
  status: string
  t: (key: string) => string
}) {
  if (status === 'applied_overlay' || status === 'applied') {
    return <span className="data-center-overlay-badge">{t('dataCenter.appliedOverlay')}</span>
  }
  if (status === 'applied_direct') {
    return <span className="data-center-direct-badge">{t('dataCenter.appliedDirect')}</span>
  }
  if (status === 'suggested') {
    return <span className="data-center-suggest-badge">{t('dataCenter.suggestOnlyBadge')}</span>
  }
  if (status.startsWith('skipped')) {
    return <span className="data-center-skipped-badge">{t('dataCenter.skippedBadge')}</span>
  }
  if (status === 'failed') {
    return <span className="data-center-failed-badge">{t('dataCenter.failedBadge')}</span>
  }
  return <StatusBadge status={status} />
}

function FieldCompletionUpdatesTable({
  updates,
  t,
}: {
  updates: UniversalFieldCompletionResponse['field_updates']
  t: (key: string) => string
}) {
  return (
    <div className="data-center-field-completion-items">
      <h4>{t('dataCenter.completionItems')}</h4>
      <div className="data-center-table-scroll">
        <table>
          <thead>
            <tr>
              <th>target_id</th>
              <th>field_name</th>
              <th>old</th>
              <th>suggested</th>
              <th>applied</th>
              <th>status</th>
            </tr>
          </thead>
          <tbody>
            {updates.map((u, i) => (
              <tr key={`${u.target_id}-${u.field_name}-${i}`}>
                <td><code>{shortId(u.target_id)}</code></td>
                <td>{u.field_name}</td>
                <td>—</td>
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

function FieldCompletionItemsTable({
  items,
  t,
}: {
  items: FieldCompletionItem[]
  t: (key: string) => string
}) {
  return (
    <div className="data-center-field-completion-items">
      <h4>{t('dataCenter.completionItems')}</h4>
      <div className="data-center-table-scroll">
        <table>
          <thead>
            <tr>
              <th>target_id</th>
              <th>field_name</th>
              <th>old</th>
              <th>suggested</th>
              <th>applied</th>
              <th>conf</th>
              <th>status</th>
              <th>evidence</th>
              <th>error</th>
            </tr>
          </thead>
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
                <td>{item.evidence_text ? formatCellValue(item.evidence_text) : '—'}</td>
                <td>{item.error_message ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
