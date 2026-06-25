import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n-context'
import {
  getFieldCompletionRelatedTargets,
  getFieldCompletionRun,
  runUniversalFieldCompletion,
  type FieldCompletionItem,
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
import { translateBundleWarning } from './circuitBundleUtils'
import { PromptWorkbenchSection } from './PromptWorkbenchSection'

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
  const [promptOverrides, setPromptOverrides] = useState<Record<string, string>>({})
  const [groupStates, setGroupStates] = useState<GroupRunState[]>([])
  const [running, setRunning] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [bundleWarnings, setBundleWarnings] = useState<string[]>([])
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())
  const [refreshingTargets, setRefreshingTargets] = useState(false)

  useEffect(() => {
    if (!open || !bundle) return
    setMode('preview')
    setRunning(false)
    setShowConfirm(false)
    setBundleWarnings([])
    setPromptOverrides({})
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
    const warnings: string[] = []
    let accumulatedPatch: OverlayPatch = {}

    for (const group of groupStates) {
      if (group.targetIds.length === 0 || group.status === 'unavailable' || group.status === 'no_data') {
        if (group.status !== 'unavailable' && group.status !== 'no_data') {
          updateGroup(group.targetType, { status: 'skipped' })
        }
        continue
      }

      const mapping = getFormalFieldMapping(group.targetType)
      if (!mapping?.implemented) {
        updateGroup(group.targetType, {
          status: 'unavailable',
          errorMessage: t('dataCenter.unsupportedTarget'),
        })
        continue
      }

      updateGroup(group.targetType, {
        status: 'running',
        errorMessage: undefined,
        executionItems: undefined,
      })
      const req = buildFieldCompletionRequest(mapping, group.targetIds, {
        ...options,
        dryRun,
        promptOverrides,
      })
      try {
        const res = await runUniversalFieldCompletion(req)
        let executionItems: FieldCompletionItem[] | undefined
        if (!dryRun && res.run_id) {
          try {
            const detail = await getFieldCompletionRun(res.run_id)
            executionItems = detail.items ?? []
            accumulatedPatch = mergeOverlayPatches(
              accumulatedPatch,
              extractOverlayPatchFromItems(executionItems),
            )
          } catch {
            accumulatedPatch = mergeOverlayPatches(
              accumulatedPatch,
              extractOverlayPatchFromFieldUpdates(res.field_updates),
            )
          }
        }
        updateGroup(group.targetType, {
          status: dryRun ? 'dry_run_done' : 'executed',
          response: res,
          executionItems,
          allowedFields: getEnrichableFormalFields(mapping),
          errorMessage: res.errors?.length ? res.errors.join('; ') : undefined,
        })
        if (res.warnings?.length) warnings.push(...res.warnings)
      } catch (err) {
        updateGroup(group.targetType, {
          status: 'failed',
          errorMessage: formatFieldCompletionErrorMessage(err, t),
        })
        warnings.push(`${group.targetType}: ${formatFieldCompletionErrorMessage(err, t)}`)
      }
    }

    setBundleWarnings(warnings)
    setMode(dryRun ? 'dry_run_result' : 'execution_result')
    setRunning(false)
    if (!dryRun) {
      onCompleted?.(accumulatedPatch)
    }
  }, [bundle, groupStates, options, promptOverrides, t, updateGroup, onCompleted])

  const dryRunPreview = useMemo(() => {
    const withPreview = groupStates.find(g => g.response?.prompt_preview)
    return (withPreview?.response?.prompt_preview as Record<string, unknown> | undefined) ?? null
  }, [groupStates])

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

        <PromptWorkbenchSection
          modeLabel={t('dataCenter.circuitBundleCompletion')}
          dryRunPreview={dryRunPreview}
          promptOverrides={promptOverrides}
          onPromptOverridesChange={setPromptOverrides}
        />

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
