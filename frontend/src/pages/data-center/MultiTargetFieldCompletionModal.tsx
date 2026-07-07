import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n-context'
import {
  getFieldCompletionRelatedTargets,
  getFieldCompletionRun,
  runUniversalFieldCompletion,
  type FieldCompletionItem,
  type FieldCompletionRunDetail,
  type UniversalFieldCompletionResponse,
} from '../../api/endpoints'
import {
  DEFAULT_FIELD_COMPLETION_OPTIONS,
  type FieldCompletionFormOptions,
  type OverlayPatch,
  buildFieldCompletionRequest,
  extractOverlayPatchFromFieldUpdates,
  extractOverlayPatchFromItems,
  formatFieldCompletionErrorMessage,
  getEnrichableFormalFields,
  mergeOverlayPatches,
  shortId,
} from './fieldCompletionUtils'
import { getFormalFieldMapping } from './formalFieldMappings'
import type {
  BundleGroupStatus,
  CircuitBundleFieldCompletionGroup,
  CircuitBundleTargetGroup,
} from './circuitBundleTypes'
import { FieldCompletionStatsCards } from './FieldCompletionStatsCards'
import { translateBundleWarning } from './circuitBundleUtils'

type ModalMode = 'preview' | 'dry_run_result' | 'execution_result'

interface GroupRunState extends CircuitBundleTargetGroup {
  status: BundleGroupStatus
  response?: UniversalFieldCompletionResponse
  executionItems?: FieldCompletionItem[]
  errorMessage?: string
  allowedFields?: string[]
}

interface Props {
  open: boolean
  bundle: CircuitBundleFieldCompletionGroup | null
  resolveWarnings?: string[]
  loading?: boolean
  onClose: () => void
  onCompleted?: (overlayPatch?: OverlayPatch) => void
  onOpenDataCenter?: () => void
}

function statusLabel(status: BundleGroupStatus, t: (key: string) => string): string {
  switch (status) {
    case 'pending': return t('dataCenter.bundleStatusPending')
    case 'running': return t('dataCenter.bundleStatusRunning')
    case 'dry_run_done': return t('dataCenter.bundleStatusDryRunDone')
    case 'executed': return t('dataCenter.bundleStatusExecuted')
    case 'skipped': return t('dataCenter.bundleStatusSkipped')
    case 'no_data': return t('dataCenter.bundleStatusNoData')
    case 'failed': return t('dataCenter.bundleStatusFailed')
    case 'unavailable': return t('dataCenter.bundleStatusUnavailable')
    default: return status
  }
}

export function MultiTargetFieldCompletionModal({
  open,
  bundle,
  resolveWarnings = [],
  loading: externalLoading = false,
  onClose,
  onCompleted,
  onOpenDataCenter,
}: Props) {
  const { t } = useI18n()
  const [mode, setMode] = useState<ModalMode>('preview')
  const [options, setOptions] = useState<FieldCompletionFormOptions>(DEFAULT_FIELD_COMPLETION_OPTIONS)
  const [groupStates, setGroupStates] = useState<GroupRunState[]>([])
  const [running, setRunning] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [bundleWarnings, setBundleWarnings] = useState<string[]>([])
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())
  const [refreshingTargets, setRefreshingTargets] = useState(false)
  // Async non-blocking execution state machine
  const execRef = useRef<{
    dryRun: boolean
    groupIndex: number
    runId: string | null
    groups: GroupRunState[]
    warnings: string[]
    accumulatedPatch: OverlayPatch
    pollTimer: ReturnType<typeof setInterval> | null
  } | null>(null)
  const [execTick, setExecTick] = useState(0) // triggers re-renders

  // Cleanup poller on unmount
  const mountedRef = useRef(true)
  const notifiedRef = useRef(false)       // H4: prevent double onCompleted
  const onCompletedRef = useRef(onCompleted)  // H4: stabilize poller deps
  onCompletedRef.current = onCompleted
  useEffect(() => {
    return () => {
      mountedRef.current = false
      if (execRef.current?.pollTimer) clearInterval(execRef.current.pollTimer)
    }
  }, [])

  // Non-blocking async poller: polls current group's run, advances to next group on completion
  useEffect(() => {
    if (execTick === 0) return
    const exec = execRef.current
    if (!exec || exec.dryRun) return

    if (exec.pollTimer) clearInterval(exec.pollTimer)

    exec.pollTimer = setInterval(async () => {
      const e = execRef.current
      if (!e || !e.runId) return

      try {
        const detail = await getFieldCompletionRun(e.runId)
        if (!detail || !['succeeded', 'partially_succeeded', 'failed', 'cancelled'].includes(detail.status)) return

        // Group completed — update state
        if (e.pollTimer) { clearInterval(e.pollTimer); e.pollTimer = null }

        const group = e.groups[e.groupIndex]
        const items = detail.items ?? []
        const finalRes = {
          run_id: detail.id,
          status: detail.status,
          provider: detail.provider,
          model_name: detail.model_name,
          target_type: detail.target_type as any,
          target_count: detail.target_count,
          updated_count: (detail.summary_json as any)?.updated_count ?? 0,
          suggested_count: (detail.summary_json as any)?.suggested_count ?? 0,
          skipped_count: (detail.summary_json as any)?.skipped_count ?? 0,
          failed_count: (detail.summary_json as any)?.failed_count ?? 0,
          field_updates: items.map((item: any) => ({
            target_id: item.target_id,
            field_name: item.field_name,
            update_status: item.update_status as any,
            suggested_value: item.suggested_value_json,
            applied_value: item.applied_value_json,
          })),
          prompt_preview: null,
          warnings: (detail.warnings_json ?? []) as string[],
          errors: (detail.errors_json ?? []) as string[],
          dry_run: false,
          summary_json: detail.summary_json as Record<string, number>,
        }

        e.accumulatedPatch = mergeOverlayPatches(
          e.accumulatedPatch,
          extractOverlayPatchFromItems(items),
        )
        if ((finalRes as any).warnings?.length) e.warnings.push(...(finalRes as any).warnings)

        e.groups[e.groupIndex] = {
          ...group,
          status: 'executed',
          response: finalRes as any,
          executionItems: items,
          errorMessage: (finalRes as any).errors?.length ? (finalRes as any).errors.join('; ') : undefined,
        }
        setGroupStates([...e.groups])

        // Advance to next group
        e.groupIndex++
        if (e.groupIndex >= e.groups.length) {
          // All done
          setBundleWarnings(e.warnings)
          setMode('execution_result')
          setRunning(false)
          // H4: guard against double notification (executeNextGroup may also fire)
          if (!notifiedRef.current) {
            notifiedRef.current = true
            onCompletedRef.current?.(e.accumulatedPatch)
          }
          execRef.current = null
          return
        }

        // Start next group
        await executeNextGroup(e)
      } catch {
        // polling error — continue
      }
    }, 2000)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [execTick])  // H4: removed onCompleted from deps; uses stable ref

  async function executeNextGroup(exec: NonNullable<typeof execRef.current>) {
    while (exec.groupIndex < exec.groups.length) {
      const group = exec.groups[exec.groupIndex]
      if (group.targetIds.length === 0 || group.status === 'unavailable' || group.status === 'no_data') {
        exec.groups[exec.groupIndex] = { ...group, status: group.status === 'pending' ? 'skipped' : group.status }
        setGroupStates([...exec.groups])
        exec.groupIndex++
        continue
      }

      const mapping = getFormalFieldMapping(group.targetType)
      if (!mapping?.implemented) {
        exec.groups[exec.groupIndex] = { ...group, status: 'unavailable', errorMessage: t('dataCenter.unsupportedTarget') }
        setGroupStates([...exec.groups])
        exec.groupIndex++
        continue
      }

      exec.groups[exec.groupIndex] = { ...group, status: 'running', errorMessage: undefined, executionItems: undefined }
      setGroupStates([...exec.groups])

      const req = buildFieldCompletionRequest(mapping, group.targetIds, {
        ...options,
        dryRun: false,
        promptOverrides: {},
      })
      try {
        const res = await runUniversalFieldCompletion(req)
        if ('run_id' in res && !('field_updates' in res)) {
          exec.runId = res.run_id
          return // poller will pick up from here
        }
        // Sync response fallback
        const items = (res as any).items ?? (res as any).field_updates ?? []
        exec.accumulatedPatch = mergeOverlayPatches(exec.accumulatedPatch, extractOverlayPatchFromFieldUpdates(items))
        exec.groups[exec.groupIndex] = {
          ...group,
          status: 'executed',
          response: res as any,
          executionItems: items,
        }
        setGroupStates([...exec.groups])
        exec.groupIndex++
      } catch (err) {
        exec.groups[exec.groupIndex] = {
          ...group,
          status: 'failed',
          errorMessage: formatFieldCompletionErrorMessage(err, t),
        }
        setGroupStates([...exec.groups])
        exec.warnings.push(`${group.targetType}: ${formatFieldCompletionErrorMessage(err, t)}`)
        exec.groupIndex++
      }
    }

    // All groups done
    setBundleWarnings(exec.warnings)
    setMode('execution_result')
    setRunning(false)
    // H4: guard against double notification (poller may also fire)
    if (!notifiedRef.current) {
      notifiedRef.current = true
      onCompletedRef.current?.(exec.accumulatedPatch)
    }
    execRef.current = null
  }

  useEffect(() => {
    if (!open || !bundle) return
    setMode('preview')
    setRunning(false)
    setShowConfirm(false)
    setBundleWarnings([])
    setOptions(DEFAULT_FIELD_COMPLETION_OPTIONS)
    setGroupStates(
      bundle.groups.map(g => {
        const mapping = getFormalFieldMapping(g.targetType)
        return {
          ...g,
          status: g.status ?? (g.targetIds.length === 0 ? 'skipped' : 'pending'),
          allowedFields: mapping ? getEnrichableFormalFields(mapping) : [],
        }
      }),
    )
  }, [open, bundle, resolveWarnings.join('|')])

  const totalTargetIds = useMemo(
    () => groupStates.reduce((sum, g) => sum + g.targetIds.length, 0),
    [groupStates],
  )

  const runnableGroups = useMemo(
    () => groupStates.filter(
      g => g.targetIds.length > 0 && g.status !== 'unavailable',
    ),
    [groupStates],
  )

  const updateGroup = useCallback((targetType: string, patch: Partial<GroupRunState>) => {
    setGroupStates(prev =>
      prev.map(g => (g.targetType === targetType ? { ...g, ...patch } : g)),
    )
  }, [])

  const circuitIds = useMemo(
    () => groupStates.find(g => g.targetType === 'circuit')?.targetIds ?? [],
    [groupStates],
  )

  const cfGroup = useMemo(
    () => groupStates.find(g => g.targetType === 'circuit_function'),
    [groupStates],
  )

  const isCfNoData = cfGroup?.status === 'no_data'
  const isMigrationMissing = cfGroup?.status === 'unavailable'

  const goToLlmExtractionCenter = useCallback(() => {
    if (circuitIds.length > 0) {
      sessionStorage.setItem(
        'pendingCircuitFunctionExtractionCircuitIds',
        JSON.stringify(circuitIds),
      )
      sessionStorage.setItem(
        'pendingCircuitFunctionExtractionSource',
        'data_center_bundle',
      )
    }
    window.location.hash = '/llm-extraction'
  }, [circuitIds])

  const refreshRelatedTargets = useCallback(async () => {
    if (!circuitIds.length) return
    setRefreshingTargets(true)
    try {
      const related = await getFieldCompletionRelatedTargets({
        target_type: 'circuit',
        target_ids: circuitIds,
        include: ['circuit_function'],
      })
      const cfEntry = related.groups.find(g => g.target_type === 'circuit_function')
      const newIds = cfEntry?.target_ids ?? []
      updateGroup('circuit_function', {
        targetIds: newIds,
        status: newIds.length > 0 ? 'pending' : 'no_data',
      })
    } catch {
      // keep current state on error
    } finally {
      setRefreshingTargets(false)
    }
  }, [circuitIds, updateGroup])

  const runBundle = useCallback(async (dryRun: boolean) => {
    if (!bundle) return
    setRunning(true)
    const groups: GroupRunState[] = groupStates.map(g => ({ ...g }))
    setGroupStates(groups)

    if (dryRun) {
      // Dry run: execute all groups synchronously (dry runs are fast)
      const warnings: string[] = []
      for (let i = 0; i < groups.length; i++) {
        const group = groups[i]
        if (group.targetIds.length === 0 || group.status === 'unavailable' || group.status === 'no_data') continue
        const mapping = getFormalFieldMapping(group.targetType)
        if (!mapping?.implemented) continue
        groups[i] = { ...group, status: 'running', errorMessage: undefined }
        setGroupStates([...groups])
        const req = buildFieldCompletionRequest(mapping, group.targetIds, { ...options, dryRun: true, promptOverrides: {} })
        try {
          const res = await runUniversalFieldCompletion(req)
          groups[i] = {
            ...groups[i],
            status: 'dry_run_done',
            response: res as any,
            allowedFields: getEnrichableFormalFields(mapping),
          }
          if ((res as any).warnings?.length) warnings.push(...(res as any).warnings)
        } catch (err) {
          groups[i] = { ...groups[i], status: 'failed', errorMessage: formatFieldCompletionErrorMessage(err, t) }
        }
        setGroupStates([...groups])
      }
      setBundleWarnings(warnings)
      setMode('dry_run_result')
      setRunning(false)
      return
    }

    // Non-dry-run: non-blocking state machine
    const exec = {
      dryRun: false,
      groupIndex: 0,
      runId: null as string | null,
      groups,
      warnings: [] as string[],
      accumulatedPatch: {} as OverlayPatch,
      pollTimer: null as ReturnType<typeof setInterval> | null,
    }
    execRef.current = exec
    setExecTick(t => t + 1)
    void executeNextGroup(exec)
  }, [bundle, groupStates, options, t])

  const summary = useMemo(() => {
    const byType = (type: string) => groupStates.find(g => g.targetType === type)
    const countFor = (type: string) => {
      const g = byType(type)
      if (!g) return { updated: 0, skipped: 0, failed: 0 }
      if (g.status === 'failed') return { updated: 0, skipped: 0, failed: g.targetIds.length }
      if (g.status === 'skipped' || g.status === 'unavailable' || g.status === 'no_data') {
        return { updated: 0, skipped: g.targetIds.length, failed: 0 }
      }
      return {
        updated: g.response?.updated_count ?? 0,
        skipped: g.response?.skipped_count ?? 0,
        failed: g.response?.failed_count ?? 0,
      }
    }
    return {
      circuit: countFor('circuit'),
      circuit_step: countFor('circuit_step'),
      circuit_function: countFor('circuit_function'),
      hasPartialFailure: groupStates.some(g => g.status === 'failed'),
    }
  }, [groupStates])

  if (!open || !bundle) return null

  const allWarnings = [...resolveWarnings, ...bundleWarnings]

  return (
    <div className="data-center-field-completion-modal data-center-bundle-completion">
      <div className="data-center-field-completion-backdrop" onClick={onClose} />
      <div className="data-center-field-completion-panel data-center-field-completion-modal-panel">
        <div className="data-center-field-completion-modal-header">
          <h3>{t('dataCenter.circuitBundleCompletion')}</h3>
          <button type="button" className="btn" onClick={onClose}>×</button>
        </div>

        <div className="data-center-field-completion-boundary">
          <p>{t('dataCenter.circuitBundleCompletionDesc')}</p>
          <p>{t('dataCenter.mirrorOnlyBoundary')}</p>
          <p>{t('dataCenter.noFinalNoKg')}</p>
          <p>{t('dataCenter.noAutoApprovePromotion')}</p>
        </div>

        {externalLoading && (
          <p className="data-center-bundle-warning">{t('dataCenter.bundleResolvingTargets')}</p>
        )}

        {allWarnings.length > 0 && (
          <details className="data-center-bundle-warning" open={resolveWarnings.length > 0}>
            <summary>{t('dataCenter.bundleWarnings')}</summary>
            <ul>
              {allWarnings.map((w, i) => (
                <li key={i}>{translateBundleWarning(w, t)}</li>
              ))}
            </ul>
          </details>
        )}

        {/* no_data: redirect to LLM Extraction Center */}
        {isCfNoData && !isMigrationMissing && (
          <div className="data-center-bundle-no-data-notice">
            <strong>{t('dataCenter.bundleCfNoDataTitle')}</strong>
            <p>{t('dataCenter.bundleCfNoDataDesc')}</p>
            <div className="data-center-bundle-extraction-actions">
              <button
                type="button"
                className="btn btn-primary"
                onClick={goToLlmExtractionCenter}
              >
                {t('dataCenter.bundleGoToLlmCenter')}
              </button>
              <button
                type="button"
                className="btn"
                disabled={refreshingTargets || circuitIds.length === 0}
                onClick={() => void refreshRelatedTargets()}
              >
                {refreshingTargets ? t('dataCenter.bundleRefreshing') : t('dataCenter.bundleRefreshRelatedTargets')}
              </button>
            </div>
          </div>
        )}

        {isMigrationMissing && (
          <p className="data-center-bundle-warning">{t('dataCenter.mirrorCircuitFunctionsNotInitialized')}</p>
        )}

        <div className="data-center-field-completion-modal-body">
          <div className="data-center-field-completion-section">
            <h4>{t('dataCenter.bundleCompletionGroups')}</h4>
            <span className="data-center-field-completion-meta">
              {t('dataCenter.bundleGroupCount', { groups: groupStates.length, ids: totalTargetIds })}
            </span>
          </div>

          <div className="data-center-bundle-groups">
            {groupStates.map(group => {
              const mapping = getFormalFieldMapping(group.targetType)
              const expanded = expandedGroups.has(group.targetType)
              return (
                <div key={group.targetType} className="data-center-bundle-group">
                  <div className="data-center-bundle-group-header">
                    <strong>
                      {group.targetType === 'circuit' && t('dataCenter.bundleGroupCircuit')}
                      {group.targetType === 'circuit_step' && t('dataCenter.bundleGroupCircuitStep')}
                      {group.targetType === 'circuit_function' && t('dataCenter.bundleGroupCircuitFunction')}
                    </strong>
                    <span className={`data-center-bundle-group-status data-center-bundle-group-status-${group.status}`}>
                      {statusLabel(group.status, t)}
                    </span>
                    <span className="data-center-field-completion-meta">
                      {group.targetIds.length} · {mapping?.formalQualifiedName ?? group.targetType}
                    </span>
                  </div>
                  <div className="data-center-field-completion-meta">
                    {t('dataCenter.allowedFields')}: {(group.allowedFields ?? []).join(', ') || '—'}
                  </div>
                  {group.unavailableReason && (
                    <p className="data-center-bundle-warning">
                      {group.unavailableReason.startsWith('dataCenter.')
                        ? t(group.unavailableReason)
                        : group.unavailableReason}
                    </p>
                  )}
                  {group.warnings?.map(w => (
                    <p key={w} className="data-center-bundle-warning data-center-bundle-warning-muted">
                      {translateBundleWarning(w, t)}
                    </p>
                  ))}
                  {group.errorMessage && (
                    <details className="data-center-bundle-result">
                      <summary>{t('dataCenter.fieldCompletionErrorDetails')}</summary>
                      <p>{group.errorMessage}</p>
                    </details>
                  )}
                  {group.response?.prompt_preview && (
                    <details
                      className="data-center-bundle-result"
                      open={expanded}
                      onToggle={e => {
                        const next = new Set(expandedGroups)
                        if ((e.target as HTMLDetailsElement).open) next.add(group.targetType)
                        else next.delete(group.targetType)
                        setExpandedGroups(next)
                      }}
                    >
                      <summary>{t('dataCenter.promptPreview')} ({group.targetType})</summary>
                      <pre>{JSON.stringify(group.response.prompt_preview, null, 2)}</pre>
                    </details>
                  )}
                  {group.response && mode === 'execution_result' && (
                    <div className="data-center-field-completion-summary">
                      updated {group.response.updated_count} · skipped {group.response.skipped_count} · failed {group.response.failed_count}
                      · overlay {group.response.applied_overlay_count ?? group.response.summary_json?.applied_overlay_count ?? 0}
                      · direct {group.response.applied_direct_count ?? group.response.summary_json?.applied_direct_count ?? 0}
                    </div>
                  )}
                  {group.executionItems && group.executionItems.length > 0 && mode === 'execution_result' && (
                    <details className="data-center-bundle-result">
                      <summary>{t('dataCenter.completionItems')} ({group.executionItems.length})</summary>
                      <table className="data-center-field-completion-items">
                        <thead>
                          <tr>
                            <th>{t('dataCenter.formalFieldsSection')}</th>
                            <th>status</th>
                            <th>applied</th>
                          </tr>
                        </thead>
                        <tbody>
                          {group.executionItems.slice(0, 20).map(item => (
                            <tr key={item.id}>
                              <td><code>{shortId(String(item.target_id))}</code> · {item.field_name}</td>
                              <td>{item.update_status}</td>
                              <td>{String(item.applied_value_json ?? item.suggested_value_json ?? '—')}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </details>
                  )}
                </div>
              )
            })}
          </div>

          {(mode === 'dry_run_result' || mode === 'execution_result') && (
            <div className="data-center-bundle-summary">
              <h4>{t('dataCenter.bundleCompletionSummary')}</h4>
              {summary.hasPartialFailure && (
                <p className="data-center-bundle-warning">{t('dataCenter.bundleCompletionPartialFailure')}</p>
              )}
              <ul>
                <li>Circuit — updated {summary.circuit.updated}, skipped {summary.circuit.skipped}, failed {summary.circuit.failed}</li>
                <li>Circuit Step — updated {summary.circuit_step.updated}, skipped {summary.circuit_step.skipped}, failed {summary.circuit_step.failed}</li>
                <li>Circuit Function — updated {summary.circuit_function.updated}, skipped {summary.circuit_function.skipped}, failed {summary.circuit_function.failed}</li>
              </ul>
            </div>
          )}

          {showConfirm && (
            <div className="data-center-field-completion-confirm">
              <h4>{t('dataCenter.bundleCompletionConfirm')}</h4>
              <ul>
                <li>{t('dataCenter.bundleCompletionConfirmCircuit')}</li>
                <li>{t('dataCenter.confirmFieldCompletionDeepSeek')}</li>
                <li>{t('dataCenter.confirmFieldCompletionMirrorOnly')}</li>
                <li>{t('dataCenter.confirmFieldCompletionNoFinalKg')}</li>
                <li>{t('dataCenter.confirmFieldCompletionFillMissing')}</li>
              </ul>
              <div className="data-center-field-completion-actions">
                <button type="button" className="btn" onClick={() => setShowConfirm(false)}>
                  {t('common.cancel')}
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={running}
                  onClick={() => {
                    setShowConfirm(false)
                    void runBundle(false)
                  }}
                >
                  {t('dataCenter.executeBundleCompletion')}
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="data-center-field-completion-footer">
          {mode === 'preview' && (
            <>
              <button
                type="button"
                className="btn"
                disabled={running || externalLoading || runnableGroups.length === 0}
                onClick={() => void runBundle(true)}
              >
                {t('dataCenter.generateBundleDryRun')}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={running || externalLoading || runnableGroups.length === 0}
                onClick={() => setShowConfirm(true)}
              >
                {t('dataCenter.executeBundleCompletion')}
              </button>
            </>
          )}
          {mode === 'dry_run_result' && (
            <button
              type="button"
              className="btn btn-primary"
              disabled={running}
              onClick={() => setShowConfirm(true)}
            >
              {t('dataCenter.executeBundleCompletion')}
            </button>
          )}
          {(mode === 'dry_run_result' || mode === 'execution_result') && onOpenDataCenter && (
            <button type="button" className="btn" onClick={onOpenDataCenter}>
              {t('dataCenter.openDataCenterView')}
            </button>
          )}
          <button type="button" className="btn" onClick={onClose}>
            {t('dataCenter.close')}
          </button>
        </div>
      </div>
    </div>
  )
}
