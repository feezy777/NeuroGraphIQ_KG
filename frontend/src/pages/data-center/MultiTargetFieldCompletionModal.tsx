import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n-context'
import { StatusBadge } from '../../components/StatusBadge'
import { ModelBadge } from '../../components/ModelBadge'
import {
  getFieldCompletionRun,
  runUniversalFieldCompletion,
  type FieldCompletionItem,
  type FieldCompletionRun,
  type FieldCompletionRunDetail,
  type FieldCompletionScope,
  type FieldCompletionTargetType,
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

// ── Types ───────────────────────────────────────────────────────────────────

type Step = 0 | 1 | 2 | 3 // overview, configure, dry_run, execute

const STEP_LABELS = ['概览', '配置参数', 'Dry Run 预览', '执行补全'] as const

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

// ── Helpers ─────────────────────────────────────────────────────────────────

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

function elapsedStr(sec: number): string {
  if (sec < 60) return `${Math.round(sec)}s`
  return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`
}

function formatValue(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'string') return v.length > 60 ? v.slice(0, 60) + '…' : v
  return JSON.stringify(v).slice(0, 60)
}

// ── Model presets ───────────────────────────────────────────────────────────

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

// ── Component ───────────────────────────────────────────────────────────────

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

  // ── Wizard state ──────────────────────────────────────────────────────────
  const [step, setStep] = useState<Step>(0)
  const [selProvider, setSelProvider] = useState('deepseek')
  const [selModel, setSelModel] = useState('deepseek-chat')
  const [customModel, setCustomModel] = useState('')
  const [options, setOptions] = useState<FieldCompletionFormOptions>(DEFAULT_FIELD_COMPLETION_OPTIONS)
  const effectiveModel = customModel || selModel

  const modelOptions = selProvider === 'kimi' ? KIMI_MODELS : DS_MODELS

  const handleProviderChange = (p: string) => {
    setSelProvider(p)
    setSelModel(p === 'kimi' ? 'moonshot-v1-auto' : 'deepseek-chat')
  }

  // ── Bundle state ──────────────────────────────────────────────────────────
  const [groupStates, setGroupStates] = useState<GroupRunState[]>([])
  const [bundleWarnings, setBundleWarnings] = useState<string[]>([])
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())

  // ── Loading states ────────────────────────────────────────────────────────
  const [dryRunLoading, setDryRunLoading] = useState(false)
  const [dryRunElapsed, setDryRunElapsed] = useState(0)
  const [dryRunError, setDryRunError] = useState<string | null>(null)

  // ── Recent runs drawer ────────────────────────────────────────────────────
  const [drawerRun, setDrawerRun] = useState<FieldCompletionRunDetail | null>(null)
  const [drawerLoading, setDrawerLoading] = useState(false)
  const [recentRuns, setRecentRuns] = useState<FieldCompletionRun[]>([])
  const [runsFetched, setRunsFetched] = useState(false)

  // ── Async execution state ─────────────────────────────────────────────────
  const [running, setRunning] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [execDone, setExecDone] = useState(false)
  const [execOverlayPatch, setExecOverlayPatch] = useState<OverlayPatch>({})
  const [execElapsed, setExecElapsed] = useState(0)
  const [execDetail, setExecDetail] = useState<FieldCompletionRunDetail | null>(null)
  const [execStatus, setExecStatus] = useState('')

  const execRef = useRef<{
    dryRun: boolean
    groupIndex: number
    runId: string | null
    groups: GroupRunState[]
    warnings: string[]
    accumulatedPatch: OverlayPatch
    pollTimer: ReturnType<typeof setInterval> | null
    execStart: number
    cancelled: boolean
  } | null>(null)
  const [execTick, setExecTick] = useState(0)

  const mountedRef = useRef(true)
  const notifiedRef = useRef(false)
  const onCompletedRef = useRef(onCompleted)
  onCompletedRef.current = onCompleted

  // ── Cleanup ───────────────────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      mountedRef.current = false
      if (execRef.current?.pollTimer) clearInterval(execRef.current.pollTimer)
    }
  }, [])

  // ── Reset on open ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!open || !bundle) return
    setStep(0)
    setSelProvider('deepseek')
    setSelModel('deepseek-chat')
    setCustomModel('')
    setOptions(DEFAULT_FIELD_COMPLETION_OPTIONS)
    setBundleWarnings([])
    setDryRunError(null)
    setDryRunLoading(false)
    setDryRunElapsed(0)
    setRunning(false)
    setCancelling(false)
    setExecDone(false)
    setExecOverlayPatch({})
    setExecElapsed(0)
    setExecDetail(null)
    setExecStatus('')
    setDrawerRun(null)
    setRecentRuns([])
    setRunsFetched(false)
    notifiedRef.current = false
    setGroupStates(
      bundle.groups.map(g => {
        const mapping = getFormalFieldMapping(g.targetType)
        return {
          ...g,
          status: g.status ?? (g.targetIds.length === 0 ? 'skipped' : 'pending'),
          allowedFields: mapping ? [] : [],
        }
      }),
    )
  }, [open, bundle])

  // ── Derived ───────────────────────────────────────────────────────────────
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

  const isMigrationMissing = useMemo(
    () => groupStates.find(g => g.targetType === 'circuit_function')?.status === 'unavailable',
    [groupStates],
  )

  // ── Aggregate dry run stats ───────────────────────────────────────────────
  const dryRunAggStats = useMemo(() => {
    const done = groupStates.filter(g => g.status === 'dry_run_done' && g.response)
    if (done.length === 0) return null
    let totalLlmFields = 0
    let totalDetFields = 0
    let totalEstCalls = 0
    let totalEstInput = 0
    let totalEstOutput = 0
    let totalPackCount = 0
    let totalTargets = 0
    let totalUpdated = 0
    let totalSuggested = 0
    let totalSkipped = 0
    let totalFailed = 0
    for (const g of done) {
      const s = (g.response!.summary_json ?? {}) as Record<string, number>
      totalLlmFields += s.llm_fields_count ?? 0
      totalDetFields += s.deterministic_fields_count ?? 0
      totalEstCalls += s.estimated_model_calls ?? 0
      totalEstInput += s.estimated_input_tokens ?? 0
      totalEstOutput += s.estimated_output_tokens ?? 0
      totalPackCount += s.pack_count ?? 0
      totalTargets += g.response!.target_count
      totalUpdated += g.response!.updated_count
      totalSuggested += g.response!.suggested_count
      totalSkipped += g.response!.skipped_count
      totalFailed += g.response!.failed_count
    }
    const cost = (totalEstInput / 1_000_000) * 1.0 + (totalEstOutput / 1_000_000) * 2.0
    return {
      totalLlmFields, totalDetFields, totalEstCalls, totalEstInput, totalEstOutput,
      totalPackCount, totalTargets, totalUpdated, totalSuggested, totalSkipped, totalFailed,
      cost,
    }
  }, [groupStates])

  // ── Aggregate execution stats ─────────────────────────────────────────────
  const execAggStats = useMemo(() => {
    const done = groupStates.filter(g => g.status === 'executed' && g.response)
    if (done.length === 0) return null
    let totalUpdated = 0; let totalSuggested = 0; let totalSkipped = 0; let totalFailed = 0
    let totalOverlay = 0; let totalDirect = 0; let totalModelCalls = 0
    let totalStepItems = 0; let totalCircuitItems = 0
    let totalMemberships = 0; let totalRegions = 0
    for (const g of done) {
      totalUpdated += g.response!.updated_count
      totalSuggested += g.response!.suggested_count
      totalSkipped += g.response!.skipped_count
      totalFailed += g.response!.failed_count
      totalOverlay += g.response!.applied_overlay_count ?? (g.response!.summary_json as any)?.applied_overlay_count ?? 0
      totalDirect += g.response!.applied_direct_count ?? (g.response!.summary_json as any)?.applied_direct_count ?? 0
      totalModelCalls += (g.response!.summary_json as any)?.model_call_count ?? 0
      totalMemberships += (g.response!.summary_json as any)?.memberships_count ?? 0
      totalRegions += (g.response!.summary_json as any)?.regions_count ?? 0
      if (g.executionItems) {
        for (const item of g.executionItems) {
          if (item.target_type === 'circuit_step') totalStepItems++
          else if (item.target_type === 'circuit') totalCircuitItems++
        }
      }
    }
    return { totalUpdated, totalSuggested, totalSkipped, totalFailed, totalOverlay, totalDirect, totalModelCalls, totalStepItems, totalCircuitItems, totalMemberships, totalRegions }
  }, [groupStates])

  // ── Poller for async execution ────────────────────────────────────────────
  useEffect(() => {
    if (execTick === 0) return
    const exec = execRef.current
    if (!exec || exec.dryRun) return

    if (exec.pollTimer) clearInterval(exec.pollTimer)

    exec.pollTimer = setInterval(async () => {
      const e = execRef.current
      if (!e) return
      if (e.cancelled) {
        if (e.pollTimer) { clearInterval(e.pollTimer); e.pollTimer = null }
        setRunning(false); setExecDone(true)
        execRef.current = null
        return
      }
      const elapsed = Math.round((Date.now() - e.execStart) / 1000)
      setExecElapsed(elapsed)
      if (!e.runId) {
        if (elapsed > 60) {
          setRunning(false); setExecDone(true)
          if (e.pollTimer) { clearInterval(e.pollTimer); e.pollTimer = null }
          execRef.current = null
        }
        return
      }

      try {
        const detail = await getFieldCompletionRun(e.runId)
        if (!detail || !['succeeded', 'partially_succeeded', 'failed', 'cancelled'].includes(detail.status)) {
          // Still running — update elapsed time
          setExecDetail(detail)
          return
        }
        setExecDetail(detail)

        if (e.pollTimer) { clearInterval(e.pollTimer); e.pollTimer = null }

        const group = e.groups[e.groupIndex]
        const items = detail.items ?? []
        const finalRes: UniversalFieldCompletionResponse = {
          run_id: detail.id,
          status: detail.status as any,
          provider: detail.provider,
          model_name: detail.model_name,
          target_type: detail.target_type as any,
          target_count: detail.target_count,
          updated_count: (detail.summary_json as any)?.updated_count ?? 0,
          suggested_count: (detail.summary_json as any)?.suggested_count ?? 0,
          skipped_count: (detail.summary_json as any)?.skipped_count ?? 0,
          failed_count: (detail.summary_json as any)?.failed_count ?? 0,
          applied_direct_count: (detail.summary_json as any)?.applied_direct_count ?? 0,
          applied_overlay_count: (detail.summary_json as any)?.applied_overlay_count ?? 0,
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
        if (finalRes.warnings?.length) e.warnings.push(...finalRes.warnings)

        e.groups[e.groupIndex] = {
          ...group,
          status: 'executed',
          response: finalRes,
          executionItems: items,
          errorMessage: finalRes.errors?.length ? finalRes.errors.join('; ') : undefined,
        }
        setGroupStates([...e.groups])

        // Push to recent runs
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

        e.groupIndex++
        if (e.groupIndex >= e.groups.length) {
          setBundleWarnings(e.warnings)
          setRunning(false)
          setCancelling(false)
          setExecDone(true)
          setExecStatus(detail.status)
          if (!notifiedRef.current) {
            notifiedRef.current = true
            onCompletedRef.current?.(e.accumulatedPatch)
          }
          execRef.current = null
          return
        }

        await executeNextGroup(e)
      } catch {
        // polling error — continue
      }
    }, 2000)
  }, [execTick])

  async function executeNextGroup(exec: NonNullable<typeof execRef.current>) {
    while (exec.groupIndex < exec.groups.length) {
      if (exec.cancelled) break
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
        provider: selProvider,
        modelName: effectiveModel,
        dryRun: false,
        promptOverrides: {},
      })
      try {
        const res = await runUniversalFieldCompletion(req)
        if ('run_id' in res && !('field_updates' in res)) {
          exec.runId = res.run_id
          return
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

    if (exec.pollTimer) { clearInterval(exec.pollTimer); exec.pollTimer = null }
    setBundleWarnings(exec.warnings)
    setRunning(false)
    setCancelling(false)
    setExecDone(true)
    setExecStatus('succeeded')
    if (!notifiedRef.current) {
      notifiedRef.current = true
      onCompletedRef.current?.(exec.accumulatedPatch)
    }
    execRef.current = null
  }

  // ── Cancel ────────────────────────────────────────────────────────────────
  const handleCancel = useCallback(async () => {
    const exec = execRef.current
    if (!exec || cancelling) return
    if (exec.runId) {
      setCancelling(true)
      try {
        const { cancelFieldCompletionRun } = await import('../../api/endpoints')
        await cancelFieldCompletionRun(exec.runId)
      } catch {
        setCancelling(false)
      }
    } else {
      // No runId yet (initial API call in flight) — mark cancelled, poller will clean up
      exec.cancelled = true
      setRunning(false)
      setExecDone(true)
    }
  }, [cancelling])

  // ── Dry run ───────────────────────────────────────────────────────────────
  const runDryRun = useCallback(async () => {
    setDryRunLoading(true)
    setDryRunError(null)
    setDryRunElapsed(0)
    const t0 = Date.now()
    const timer = setInterval(() => setDryRunElapsed((Date.now() - t0) / 1000), 200)
    const warnings: string[] = []
    const groups = groupStates.map(g => ({ ...g }))

    for (let i = 0; i < groups.length; i++) {
      const group = groups[i]
      if (group.targetIds.length === 0 || group.status === 'unavailable' || group.status === 'no_data') continue
      const mapping = getFormalFieldMapping(group.targetType)
      if (!mapping?.implemented) continue
      groups[i] = { ...group, status: 'running', errorMessage: undefined }
      setGroupStates([...groups])
      const req = buildFieldCompletionRequest(mapping, group.targetIds, {
        ...options,
        provider: selProvider,
        modelName: effectiveModel,
        dryRun: true,
        promptOverrides: {},
      })
      try {
        const res = await runUniversalFieldCompletion(req)
        groups[i] = {
          ...groups[i],
          status: 'dry_run_done',
          response: res as any,
          allowedFields: mapping.enrichableFields ?? [],
        }
        if ((res as any).warnings?.length) warnings.push(...(res as any).warnings)
      } catch (err) {
        groups[i] = { ...groups[i], status: 'failed', errorMessage: formatFieldCompletionErrorMessage(err, t) }
      }
      setGroupStates([...groups])
    }
    clearInterval(timer)
    setBundleWarnings(warnings)
    setGroupStates(groups)
    setDryRunLoading(false)
    setStep(2)
  }, [groupStates, options, selProvider, effectiveModel, t])

  // ── Execute ───────────────────────────────────────────────────────────────
  const runBundle = useCallback(async () => {
    if (!bundle) return
    setRunning(true)
    setCancelling(false)
    setExecDone(false)
    setExecOverlayPatch({})
    setExecElapsed(0)
    setExecDetail(null)
    setExecStatus('running')
    notifiedRef.current = false
    const groups: GroupRunState[] = groupStates.map(g => ({ ...g }))
    setGroupStates(groups)

    const exec = {
      dryRun: false,
      groupIndex: 0,
      runId: null as string | null,
      groups,
      warnings: [] as string[],
      accumulatedPatch: {} as OverlayPatch,
      pollTimer: null as ReturnType<typeof setInterval> | null,
      execStart: Date.now(),
      cancelled: false,
    }
    execRef.current = exec
    setExecTick(t => t + 1)
    void executeNextGroup(exec)
  }, [bundle, groupStates, options, selProvider, effectiveModel, t])

  // ── Recent runs ───────────────────────────────────────────────────────────
  const loadRecentRuns = useCallback(async () => {
    setRunsFetched(true)
    try {
      const { listFieldCompletionRuns } = await import('../../api/endpoints')
      const res = await listFieldCompletionRuns({ target_type: 'circuit' as FieldCompletionTargetType, limit: 20 })
      setRecentRuns(res.items)
    } catch { /* ignore */ }
  }, [])

  const handleClose = () => {
    if (execDone && Object.keys(execOverlayPatch).length > 0 && !notifiedRef.current) {
      notifiedRef.current = true
      onCompletedRef.current?.(execOverlayPatch)
    }
    onClose()
  }

  // ── Enrichable fields for selected_fields scope (must be before early return) ─
  const allEnrichableFields = useMemo(() => {
    const seen = new Map<string, string>()
    for (const g of groupStates) {
      const m = getFormalFieldMapping(g.targetType)
      if (m?.enrichableFields) {
        for (const f of m.enrichableFields) {
          if (!seen.has(f.key)) seen.set(f.key, f.label)
        }
      }
    }
    return [...seen.entries()].map(([key, label]) => ({ key, label }))
  }, [groupStates])

  if (!open || !bundle) return null

  const allWarnings = [...resolveWarnings, ...bundleWarnings]
  const isExecuting = step === 3 && running && !execDone
  const isExecDone = step === 3 && execDone

  return (
    <div className="data-center-field-completion-modal data-center-bundle-completion">
      <div className="data-center-field-completion-backdrop" onClick={handleClose} />
      <div className="data-center-field-completion-panel data-center-field-completion-modal-panel">
        {/* ── Header ──────────────────────────────────────────────────────── */}
        <div className="data-center-field-completion-modal-header">
          <h3>{t('dataCenter.circuitBundleCompletion')}</h3>
          <button type="button" className="btn" onClick={handleClose}>×</button>
        </div>

        {/* ── Step indicator ──────────────────────────────────────────────── */}
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

        {/* ── Warning banner ──────────────────────────────────────────────── */}
        {allWarnings.length > 0 && !isExecuting && !isExecDone && (
          <details className="data-center-bundle-warning" open={resolveWarnings.length > 0}>
            <summary>{t('dataCenter.bundleWarnings')}</summary>
            <ul>
              {allWarnings.map((w, i) => (
                <li key={i}>{translateBundleWarning(w, t)}</li>
              ))}
            </ul>
          </details>
        )}

        {!isExecuting && !isExecDone && isMigrationMissing && (
          <p className="data-center-bundle-warning">{t('dataCenter.mirrorCircuitFunctionsNotInitialized')}</p>
        )}

        {externalLoading && !isExecuting && !isExecDone && (
          <p className="data-center-bundle-warning">{t('dataCenter.bundleResolvingTargets')}</p>
        )}

        <div className="data-center-field-completion-modal-body">

          {/* ════════════════════════════════════════════════════════════════
              STEP 0: Overview
              ════════════════════════════════════════════════════════════════ */}
          {step === 0 && (
            <>
              <div className="data-center-field-completion-section">
                <h4>{t('dataCenter.bundleCompletionGroups')}</h4>
                <span className="data-center-field-completion-meta">
                  {t('dataCenter.bundleGroupCount', { groups: groupStates.length, ids: totalTargetIds })}
                </span>
              </div>

              <div className="data-center-bundle-groups">
                {groupStates.map(group => {
                  const mapping = getFormalFieldMapping(group.targetType)
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
                      {group.unavailableReason && (
                        <p className="data-center-bundle-warning">
                          {group.unavailableReason.startsWith('dataCenter.') ? t(group.unavailableReason) : group.unavailableReason}
                        </p>
                      )}
                      {group.warnings?.map(w => (
                        <p key={w} className="data-center-bundle-warning data-center-bundle-warning-muted">
                          {translateBundleWarning(w, t)}
                        </p>
                      ))}
                    </div>
                  )
                })}
              </div>

              <div className="data-center-field-completion-boundary">
                <p>{t('dataCenter.circuitBundleCompletionDesc')}</p>
                <p>{t('dataCenter.mirrorOnlyBoundary')}</p>
                <p>{t('dataCenter.noFinalNoKg')}</p>
                <p>{t('dataCenter.noAutoApprovePromotion')}</p>
              </div>
            </>
          )}

          {/* ════════════════════════════════════════════════════════════════
              STEP 1: Configure
              ════════════════════════════════════════════════════════════════ */}
          {step === 1 && (
            <>
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
                    {allEnrichableFields.map(col => (
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
              {dryRunError && <div className="data-center-field-completion-error"><p>{dryRunError}</p></div>}
            </>
          )}

          {/* ════════════════════════════════════════════════════════════════
              STEP 2: Dry Run Result
              ════════════════════════════════════════════════════════════════ */}
          {step === 2 && (
            <>
              {dryRunLoading ? (
                <div style={{ textAlign: 'center', padding: 40 }}>
                  <div className="dc-wizard-loading" />
                  <p style={{ marginTop: 16, color: '#888' }}>正在分析… {elapsedStr(dryRunElapsed)}</p>
                </div>
              ) : dryRunAggStats ? (
                <>
                  <div className="dc-fc-stats-banner success" style={{ marginBottom: 12 }}>
                    <div className="dc-fc-stats-banner-title">Dry Run 预览完成</div>
                  </div>

                  {/* Per-group cards */}
                  <div className="dc-fc-stats-grid">
                    <div className="dc-fc-stats-col">
                      <div className="dc-fc-stats-col-title">预估概览</div>
                      <div className="dc-fc-stats-cards">
                        <MiniCard label="LLM 字段" value={dryRunAggStats.totalLlmFields} color="#1e40af" />
                        <MiniCard label="确定性字段" value={dryRunAggStats.totalDetFields} color="#7c3aed" />
                        <MiniCard label="LLM 调用" value={dryRunAggStats.totalEstCalls} color="#0891b2" />
                        <MiniCard label="包数" value={dryRunAggStats.totalPackCount} color="#0d9488" />
                      </div>
                    </div>
                    <div className="dc-fc-stats-col">
                      <div className="dc-fc-stats-col-title">Token / 费用估算</div>
                      <div className="dc-fc-stats-cards">
                        <MiniCard label="输入" value={`~${dryRunAggStats.totalEstInput.toLocaleString()}`} color="#2563eb" />
                        <MiniCard label="输出" value={`~${dryRunAggStats.totalEstOutput.toLocaleString()}`} color="#16a34a" />
                        <MiniCard label="费用" value={dryRunAggStats.cost < 0.01 ? '<¥0.01' : `¥${dryRunAggStats.cost.toFixed(2)}`} color="#dc2626" />
                        <MiniCard label="对象数" value={dryRunAggStats.totalTargets} color="#d97706" />
                      </div>
                    </div>
                  </div>

                  {/* Per-group dry run results */}
                  {groupStates.filter(g => g.response?.prompt_preview).map(group => (
                    <details key={group.targetType} className="data-center-bundle-result" style={{ marginTop: 12 }}
                      open={expandedGroups.has(group.targetType)}
                      onToggle={e => {
                        const next = new Set(expandedGroups)
                        if ((e.target as HTMLDetailsElement).open) next.add(group.targetType)
                        else next.delete(group.targetType)
                        setExpandedGroups(next)
                      }}>
                      <summary>
                        {group.targetType === 'circuit' ? t('dataCenter.bundleGroupCircuit')
                          : group.targetType === 'circuit_step' ? t('dataCenter.bundleGroupCircuitStep')
                            : t('dataCenter.bundleGroupCircuitFunction')} — {group.targetIds.length} 对象
                      </summary>
                      <pre>{JSON.stringify(group.response!.prompt_preview, null, 2).slice(0, 2000)}</pre>
                    </details>
                  ))}

                  {dryRunError && <div className="data-center-field-completion-error"><p>{dryRunError}</p></div>}
                </>
              ) : dryRunError ? (
                <div className="data-center-field-completion-error"><p>{dryRunError}</p></div>
              ) : (
                <p style={{ color: '#888', textAlign: 'center', padding: 40 }}>Dry run 结果将在这里展示</p>
              )}
            </>
          )}

          {/* ════════════════════════════════════════════════════════════════
              STEP 3: Execute
              ════════════════════════════════════════════════════════════════ */}
          {step === 3 && (isExecuting || isExecDone ? (
            <>
              <FieldCompletionStatsCards
                detail={execDetail}
                status={execDone ? (execDetail?.status ?? execStatus) : execStatus || 'running'}
                targetCount={totalTargetIds}
                elapsedSec={execElapsed}
                onCancel={!isExecDone && !cancelling ? handleCancel : undefined}
                cancelling={cancelling}
                onClose={handleClose}
              />

              {/* Group status list */}
              <div className="data-center-bundle-groups" style={{ marginTop: 12 }}>
                {groupStates.map(group => (
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
                      {group.response && (
                        <span className="data-center-field-completion-meta">
                          updated {group.response.updated_count} · skipped {group.response.skipped_count}
                          · overlay {group.response.applied_overlay_count ?? (group.response.summary_json as any)?.applied_overlay_count ?? 0}
                          · direct {group.response.applied_direct_count ?? (group.response.summary_json as any)?.applied_direct_count ?? 0}
                        </span>
                      )}
                    </div>
                    {group.errorMessage && (
                      <details className="data-center-bundle-result">
                        <summary>{t('dataCenter.fieldCompletionErrorDetails')}</summary>
                        <p>{group.errorMessage}</p>
                      </details>
                    )}
                    {group.executionItems && group.executionItems.length > 0 && (
                      <details className="data-center-bundle-result">
                        <summary>{t('dataCenter.completionItems')} ({group.executionItems.length})</summary>
                        <table className="data-center-field-completion-items">
                          <thead>
                            <tr><th>{t('dataCenter.formalFieldsSection')}</th><th>status</th><th>applied</th></tr>
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
                ))}
              </div>

              {/* Aggregate summary */}
              {execAggStats && (
                <div className="data-center-bundle-summary">
                  <h4>{t('dataCenter.bundleCompletionSummary')}</h4>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px', fontSize: 13 }}>
                    <div><strong>LLM 调用</strong>: {execAggStats.totalModelCalls} 次 (回路 {Math.ceil(execAggStats.totalModelCalls/2)} + 步骤 {Math.floor(execAggStats.totalModelCalls/2)})</div>
                    <div><strong>回路字段</strong>: {execAggStats.totalCircuitItems} 项</div>
                    <div><strong>步骤字段</strong>: {execAggStats.totalStepItems} 项</div>
                    <div><strong>更新/建议/跳过/失败</strong>: {execAggStats.totalUpdated}/{execAggStats.totalSuggested}/{execAggStats.totalSkipped}/{execAggStats.totalFailed}</div>
                    <div><strong>Overlay</strong>: {execAggStats.totalOverlay} · <strong>Direct</strong>: {execAggStats.totalDirect}</div>
                    <div><strong>Connection映射</strong>: {execAggStats.totalMemberships} · <strong>Region关联</strong>: {execAggStats.totalRegions}</div>
                    <div style={{ gridColumn: '1 / -1', fontSize: 11, color: '#888', marginTop: 4 }}>
                      ⚡ V2 Bundle: 回路字段 + 步骤字段 + 脑区匹配 + step→connection映射（自动）
                    </div>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: 40 }}>
              <p style={{ fontSize: 16, color: '#1a1a2e', marginBottom: 8 }}>确认执行回路 Bundle 补全</p>
              <p style={{ color: '#888', marginBottom: 8 }}>
                将对 {runnableGroups.length} 个分组（共 {totalTargetIds} 个对象）执行 LLM 字段补全。
              </p>
              <div className="data-center-field-completion-boundary" style={{ textAlign: 'left' }}>
                <p>{t('dataCenter.mirrorOnlyBoundary')}</p>
                <p>{t('dataCenter.noFinalNoKg')}</p>
                <p>{t('dataCenter.noAutoApprovePromotion')}</p>
              </div>
              <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={() => void runBundle()} disabled={running}>
                {running ? '启动中…' : '✨ 开始执行'}
              </button>
            </div>
          ))}

        </div>

        {/* ── Footer navigation ────────────────────────────────────────────── */}
        {!(isExecuting || isExecDone) && (
          <div className="data-center-field-completion-footer">
            <button type="button" className="btn" onClick={handleClose} disabled={dryRunLoading || running}>取消</button>
            <div style={{ display: 'flex', gap: 8 }}>
              {step > 0 && (
                <button type="button" className="btn" onClick={() => setStep(s => (s - 1) as Step)}
                  disabled={dryRunLoading || running}>
                  上一步
                </button>
              )}
              {step === 0 && (
                <button type="button" className="btn btn-primary"
                  onClick={() => setStep(1)}
                  disabled={runnableGroups.length === 0 || externalLoading}>
                  下一步 →
                </button>
              )}
              {step === 1 && (
                <button type="button" className="btn btn-primary"
                  onClick={() => { setStep(2); void runDryRun() }}
                  disabled={runnableGroups.length === 0}>
                  Dry Run 预览 →
                </button>
              )}
              {step === 2 && (
                <button type="button" className="btn btn-primary"
                  onClick={() => setStep(3)}
                  disabled={!dryRunAggStats || dryRunLoading}>
                  执行补全 →
                </button>
              )}
            </div>
          </div>
        )}

        {/* ── Execute footer: Open Data Center button ──────────────────────── */}
        {isExecDone && (
          <div className="data-center-field-completion-footer">
            <button type="button" className="btn" onClick={handleClose}>关闭</button>
            {onOpenDataCenter && (
              <button type="button" className="btn btn-primary" onClick={onOpenDataCenter}>
                {t('dataCenter.openDataCenterView')}
              </button>
            )}
          </div>
        )}

        {/* ── Recent runs ──────────────────────────────────────────────────── */}
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

        {/* ── Side drawer ──────────────────────────────────────────────────── */}
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
                      <FieldCompletionItemsTable items={drawerRun.items} />
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

// ── Items table for drawer ──────────────────────────────────────────────────

function FieldCompletionItemsTable({ items }: { items: FieldCompletionItem[] }) {
  return (
    <div className="data-center-field-completion-items">
      <h4>补全明细</h4>
      <div className="data-center-table-scroll">
        <table>
          <thead>
            <tr><th>target_id</th><th>field_name</th><th>old</th><th>suggested</th><th>applied</th><th>conf</th><th>status</th></tr>
          </thead>
          <tbody>
            {items.map(item => (
              <tr key={item.id}>
                <td><code>{shortId(item.target_id)}</code></td>
                <td>{item.field_name}</td>
                <td>{String(item.old_value_json ?? '—').slice(0, 40)}</td>
                <td>{String(item.suggested_value_json ?? '—').slice(0, 40)}</td>
                <td>{String(item.applied_value_json ?? '—').slice(0, 40)}</td>
                <td>{item.confidence ?? '—'}</td>
                <td>{item.update_status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
