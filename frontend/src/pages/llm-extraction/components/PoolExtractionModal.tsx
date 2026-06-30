import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { ModelSelector } from './ModelSelector'
import {
  getCompositeWorkflowRun,
  startCompositeWorkflow,
  runSameGranularityFunctionExtraction,
  cancelCompositeWorkflow,
  pauseCompositeWorkflow,
  resumeCompositeWorkflow,
  removePoolMembers,
  getCandidatePool,
  createCandidatePool,
  fetchCandidates,
  getExtractionPromptTemplates,
  type CandidatePool,
  type CandidatePoolMember,
  type CompositeWorkflowRunRead,
  type CompositeWorkflowStartResponse,
  type ExtractionPromptTemplate,
} from '../../../api/endpoints'
import { getJson } from '../../../api/client'

// ── Types ───────────────────────────────────────────────────────────────────

type ModalState = 'prepare' | 'progress' | 'result'

interface ProgressData {
  workflowRunId: string
  workflowStatus: string
  progressPercent: number
  processedPacks: number
  totalPacks: number
  successPacks: number          // succeeded_pack_count — packs that finished without error
  failedPacks: number            // failed_pack_count — transport/parse/exception failures
  noConnectionPacks: number      // no_connection_pack_count — succeeded but zero connections found
  connectionsFound: number       // parsed_projection_count
  parsedNoConnCount: number      // parsed_no_connection_count
  createdCount: number            // created_projection_count — new Mirror connections written
  updatedCount: number            // updated_projection_count — merged into existing
  mergedCount: number             // merged_projection_count — dedup-merged into existing
  skippedDupCount: number         // skipped_duplicate_count — exact duplicates skipped
  noConnectionCount: number       // no_connection_count — all no_connection entries
  providerCallCount: number
  modelCalls: number              // model_call_count — packs built, waiting for provider
  promptSent: number              // prompt_sent_count — provider request in flight
  inFlightPacks: number           // in_flight_pack_count — backend reports current in-flight packs
  concurrency: number
  averagePackSec: number | null   // null = not available yet
  estimatedRemainingSec: number | null
  zeroDiags: string[]
  errors: string[]
  elapsedSec: number
  startedAt: string | null
  lastPauseResponse: string
  lastPauseError: string
  lastCancelResponse: string
  lastCancelError: string
}

interface Props {
  open: boolean
  pool: CandidatePool | null
  pooledCandidateIds: Set<string>
  provider: string
  modelName: string
  providers: Array<{ name: string; configured: boolean; default_model: string }>
  onProviderChange: (p: string) => void
  onModelChange: (m: string) => void
  onPoolRefresh: () => void
  onSetPoolCandidates?: (candidateIds: string[]) => Promise<unknown>
  selectedCandidateIds: string[]
  candidateLabels?: Record<string, string>
  skipInitialPoolSync?: boolean
  onClose: () => void
  workflowType?: string
}

interface DisplayMember {
  candidate_id: string
  label: string
  added_at: string
}

// ── Helpers ─────────────────────────────────────────────────────────────────

const TYPE_LABELS: Record<string, string> = {
  connection_with_function: '连接 + 功能提取',
  circuit_with_function_steps: '回路 + 步骤 + 功能提取',
  same_granularity_function_completion: '脑区功能提取',
}

const COMPOSITE_WORKFLOW_TYPES = new Set([
  'connection_with_function',
  'circuit_with_function_steps',
  'triple_generation',
])

function resolveCompositeWorkflowType(workflowType: string): string | null {
  if (COMPOSITE_WORKFLOW_TYPES.has(workflowType)) return workflowType
  if (workflowType === 'same_granularity_connection_completion') return 'connection_with_function'
  if (workflowType === 'composite_circuit_with_function_and_steps') return 'circuit_with_function_steps'
  return null
}

function isFunctionPoolWorkflow(workflowType: string): boolean {
  return workflowType === 'same_granularity_function_completion'
}

const TERMINAL_STATUSES = new Set([
  'succeeded',
  'partially_succeeded',
  'failed',
  'cancelled',
  'cleanup_done',
  'cleanup_failed',
  'no_edges',
  'succeeded_no_edges',
  'dry_run',
  'failed_provider_not_called',
  'failed_provider_empty_response',
  'failed_parse_error',
  'failed_no_output',
  'paused',
])

function resolvePolledWorkflowStatus(
  previous: string,
  fromServer: string,
): string {
  if (fromServer !== 'running' && fromServer !== 'pending') return fromServer
  if (previous === 'cancelling' || previous === 'pause_requested') return previous
  return fromServer
}

function isTerminalWorkflowStatus(status: string): boolean {
  return TERMINAL_STATUSES.has(status)
}

function shortId(id: string): string {
  return id.length > 10 ? `${id.slice(0, 10)}…` : id
}

function elapsedStr(sec: number): string {
  if (sec < 60) return `${Math.round(sec)}s`
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}m ${s}s`
}

function computePairCount(n: number): number {
  if (n < 2) return 0
  return (n * (n - 1)) / 2
}

function estimatePackCount(pairCount: number): number {
  if (pairCount <= 0) return 0
  return Math.ceil(pairCount / 40)
}

function sortedIdsKey(ids: string[]): string {
  return ids.slice().sort().join('\0')
}

function countFinishedPacks(summaries: unknown): number {
  if (!Array.isArray(summaries)) return 0
  return summaries.filter(p => {
    if (!p || typeof p !== 'object') return false
    const t = p as Record<string, unknown>
    return t.provider_call_finished === true
      || t.status === 'succeeded'
      || t.status === 'no_connection'
  }).length
}

function readProgressMetric(
  sources: Array<Record<string, unknown>>,
  key: string,
  fallbackKey?: string,
): number | null {
  for (const src of sources) {
    if (!src) continue
    let v = src[key]
    if ((v === undefined || v === null) && fallbackKey) v = src[fallbackKey]
    if (v !== undefined && v !== null) {
      const n = Number(v)
      if (Number.isFinite(n)) return n
    }
  }
  return null
}

// ── Component ──────────────────────────────────────────────────────────────

export function PoolExtractionModal({
  open,
  pool,
  pooledCandidateIds,
  provider,
  modelName,
  providers,
  onProviderChange,
  onModelChange,
  onPoolRefresh,
  onSetPoolCandidates,
  selectedCandidateIds,
  candidateLabels = {},
  skipInitialPoolSync = false,
  onClose,
  workflowType = 'connection_with_function',
}: Props) {
  // ── Modal state ───────────────────────────────────────────────────────────
  const [modalState, setModalState] = useState<ModalState>('prepare')
  const [wizardStep, setWizardStep] = useState<1 | 2>(1)
  const [internalLabels, setInternalLabels] = useState<Record<string, string>>({})
  const [dryRun, setDryRun] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [addingMembers, setAddingMembers] = useState(false)
  const [showErrors, setShowErrors] = useState(false)
  const [localPoolId, setLocalPoolId] = useState<string | null>(null)

  // ── Prompt engineering ──────────────────────────────────────────────────────
  const [temperature, setTemperature] = useState(0.7)
  const [maxTokens, setMaxTokens] = useState(4096)
  const [showPromptPreview, setShowPromptPreview] = useState(false)
  const [editingPrompt, setEditingPrompt] = useState(false)
  const [customSystemPrompt, setCustomSystemPrompt] = useState('')
  const [customUserPrompt, setCustomUserPrompt] = useState('')
  const [promptTemplates, setPromptTemplates] = useState<ExtractionPromptTemplate[]>([])

  // ── Pool member selection ─────────────────────────────────────────────────
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedMemberCandidateIds, setSelectedMemberCandidateIds] = useState<Set<string>>(new Set())
  const [localMembers, setLocalMembers] = useState<CandidatePoolMember[]>([])
  const [pendingMembers, setPendingMembers] = useState<Array<{ candidate_id: string; added_at: string }>>([])

  // ── Progress state (keep with other useState — hooks order) ───────────────
  const [progress, setProgress] = useState<ProgressData>({
    workflowRunId: '',
    workflowStatus: 'pending',
    progressPercent: 0,
    processedPacks: 0,
    totalPacks: 0,
    successPacks: 0,
    failedPacks: 0,
    noConnectionPacks: 0,
    connectionsFound: 0,
    parsedNoConnCount: 0,
    createdCount: 0,
    updatedCount: 0,
    mergedCount: 0,
    skippedDupCount: 0,
    noConnectionCount: 0,
    providerCallCount: 0,
    modelCalls: 0,
    promptSent: 0,
    inFlightPacks: 0,
    concurrency: 1,
    averagePackSec: null,
    estimatedRemainingSec: null,
    zeroDiags: [],
    errors: [],
    elapsedSec: 0,
    startedAt: null,
    lastPauseResponse: '',
    lastPauseError: '',
    lastCancelResponse: '',
    lastCancelError: '',
  })

  // ── Runtime debug refs (must be before any early return) ──────────────────
  const lastPollRef = useRef('')
  const dataSourceRef = useRef('init')
  const startTimeRef = useRef(Date.now())
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const cancelledRef = useRef(false)
  const pauseInFlightRef = useRef(false)
  const cancelInFlightRef = useRef(false)
  const openSyncDoneRef = useRef(false)
  const [pausing, setPausing] = useState(false)
  const [resuming, setResuming] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const [lockedPanelHeight, setLockedPanelHeight] = useState<number>(520)

  // Lock panel height from step 1 so step 2 uses the same size
  useEffect(() => {
    if (modalState === 'prepare' && wizardStep === 1 && panelRef.current) {
      const raf = requestAnimationFrame(() => {
        if (panelRef.current) {
          setLockedPanelHeight(panelRef.current.offsetHeight)
        }
      })
      return () => cancelAnimationFrame(raf)
    }
  }, [modalState, wizardStep, open])

  // ── Prompt template key mapping ─────────────────────────────────────────────
  const WORKFLOW_PRIMARY_TEMPLATE: Record<string, string> = {
    connection_with_function: 'same_granularity_connection_completion_v1',
    circuit_with_function_steps: 'same_granularity_circuit_completion_v1',
    same_granularity_function_completion: 'same_granularity_function_completion_v1',
  }

  const primaryTemplateKey = WORKFLOW_PRIMARY_TEMPLATE[workflowType] ?? ''

  // Load prompt templates on open
  useEffect(() => {
    if (!open || promptTemplates.length > 0) return
    getExtractionPromptTemplates('extraction')
      .then(res => setPromptTemplates(res.items ?? []))
      .catch(err => console.error('[PoolExtractionModal] Failed to load templates:', err))
  }, [open, promptTemplates.length])

  // Primary template from fetched templates
  const primaryTemplate = useMemo(
    () => promptTemplates.find(t => t.key === primaryTemplateKey),
    [promptTemplates, primaryTemplateKey],
  )

  // Populate custom prompts when template loads
  useEffect(() => {
    if (primaryTemplate) {
      setCustomSystemPrompt(primaryTemplate.system_prompt)
      setCustomUserPrompt(primaryTemplate.template)
    }
  }, [primaryTemplate?.key])

  // Keep localMembers in sync with pool.memberships
  useEffect(() => {
    if (pool?.memberships && pool.memberships.length > 0) {
      setLocalMembers(pool.memberships)
      setPendingMembers([])
    } else if (!pool?.memberships?.length) {
      setLocalMembers([])
      setPendingMembers([])
    }
  }, [pool?.id, pool?.memberships])

  // Fetch candidate labels when pool changes
  useEffect(() => {
    if (!pool?.resource_id) { setInternalLabels({}); return }
    let cancelled = false
    fetchCandidates({ resource_id: pool.resource_id, limit: 500 })
      .then(res => {
        if (cancelled) return
        const labels: Record<string, string> = {}
        for (const c of res.items) {
          labels[c.id] = c.cn_name ?? c.en_name ?? c.raw_name ?? c.id
        }
        setInternalLabels(labels)
      })
      .catch(err => console.error('[PoolExtractionModal] Failed to fetch candidates:', err))
    return () => { cancelled = true }
  }, [pool?.resource_id])

  // Replace pool with external table selection (no accumulation)
  const handleReplaceWithSelected = useCallback(async () => {
    if (selectedCandidateIds.length < 2) return
    setAddingMembers(true)
    try {
      if (onSetPoolCandidates) {
        await onSetPoolCandidates(selectedCandidateIds)
      } else {
        const scope = {
          candidate_ids: selectedCandidateIds,
          source_atlas: pool?.source_atlas ?? 'AAL3',
          granularity_level: pool?.granularity_level ?? 'macro',
          granularity_family: pool?.granularity_family ?? 'macro_clinical',
        }
        const newPool = await createCandidatePool(scope)
        setLocalPoolId(newPool.id)
        const updated = await getCandidatePool(newPool.id)
        setLocalMembers(updated.memberships ?? [])
        setPendingMembers([])
      }
      setSelectedMemberCandidateIds(new Set(selectedCandidateIds))
      onPoolRefresh()
    } catch (err) {
      console.error('[PoolExtractionModal] Replace pool failed:', err)
    } finally {
      setAddingMembers(false)
    }
  }, [selectedCandidateIds, onSetPoolCandidates, pool?.source_atlas, pool?.granularity_level, pool?.granularity_family, onPoolRefresh])

  // On open: auto-replace pool with external table selection when they differ
  useEffect(() => {
    if (!open) {
      openSyncDoneRef.current = false
      return
    }
    if (skipInitialPoolSync) {
      openSyncDoneRef.current = true
      return
    }
    if (modalState !== 'prepare' || openSyncDoneRef.current) return
    if (selectedCandidateIds.length < 2 || !onSetPoolCandidates) return

    const externalKey = sortedIdsKey(selectedCandidateIds)
    const poolKey = sortedIdsKey((pool?.memberships ?? []).map(m => m.candidate_id))
    openSyncDoneRef.current = true
    if (externalKey === poolKey) return

    let cancelled = false
    setAddingMembers(true)
    onSetPoolCandidates(selectedCandidateIds)
      .then(() => { if (!cancelled) onPoolRefresh() })
      .catch(err => console.error('[PoolExtractionModal] Auto-sync pool failed:', err))
      .finally(() => { if (!cancelled) setAddingMembers(false) })
    return () => { cancelled = true }
  }, [
    open,
    modalState,
    selectedCandidateIds,
    pool?.id,
    pool?.memberships,
    onSetPoolCandidates,
    onPoolRefresh,
    skipInitialPoolSync,
  ])

  const displayMembers: DisplayMember[] = useMemo(() => {
    const fromPool = localMembers.map(m => ({
      candidate_id: m.candidate_id,
      label: internalLabels[m.candidate_id] ?? m.candidate_id,
      added_at: m.added_at ?? '',
    }))
    const fromPending = pendingMembers.filter(p => !localMembers.some(m => m.candidate_id === p.candidate_id))
      .map(p => ({
        candidate_id: p.candidate_id,
        label: internalLabels[p.candidate_id] ?? p.candidate_id,
        added_at: p.added_at,
      }))
    return [...fromPool, ...fromPending]
  }, [localMembers, pendingMembers, internalLabels])

  const allMemberIds = new Set(displayMembers.map(m => m.candidate_id))
  const totalPooledCount = allMemberIds.size

  const filteredMembers = useMemo(() => {
    if (!searchTerm.trim()) return displayMembers
    const term = searchTerm.toLowerCase()
    return displayMembers.filter(m => m.label.toLowerCase().includes(term) || m.candidate_id.toLowerCase().includes(term))
  }, [displayMembers, searchTerm])

  const selectedExtractionIds = useMemo(
    () => Array.from(selectedMemberCandidateIds),
    [selectedMemberCandidateIds],
  )
  const selectedPairCount = computePairCount(selectedExtractionIds.length)
  const selectedPackEstimate = estimatePackCount(selectedPairCount)

  const selectedCount = selectedCandidateIds.length
  const externalPackEstimate = estimatePackCount(computePairCount(selectedCount))
  const poolMatchesExternal = totalPooledCount === selectedCount
    && selectedCount > 0
    && selectedCandidateIds.every(id => allMemberIds.has(id))

  // ── Select all / none ─────────────────────────────────────────────────────
  const handleSelectAll = useCallback(() => {
    const ids = filteredMembers.map(m => m.candidate_id)
    setSelectedMemberCandidateIds(new Set(ids))
  }, [filteredMembers])

  const handleSelectNone = useCallback(() => {
    setSelectedMemberCandidateIds(new Set())
  }, [])

  const handleToggleMember = useCallback((candidateId: string) => {
    setSelectedMemberCandidateIds(prev => {
      const next = new Set(prev)
      if (next.has(candidateId)) {
        next.delete(candidateId)
      } else {
        next.add(candidateId)
      }
      return next
    })
  }, [])

  // ── Remove members ───────────────────────────────────────────────────────
  const handleRemoveSelected = useCallback(async () => {
    if (!pool || selectedMemberCandidateIds.size === 0) return
    try {
      await removePoolMembers(pool.id, { candidate_ids: Array.from(selectedMemberCandidateIds) })
      setSelectedMemberCandidateIds(new Set())
      try {
        const updatedPool = await getCandidatePool(pool.id)
        setLocalMembers(updatedPool.memberships ?? [])
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        if (msg.includes('Pool not found') || msg.includes('404')) {
          setLocalMembers([])
        }
      }
      onPoolRefresh()
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      if (msg.includes('Pool not found') || msg.includes('404')) {
        setLocalMembers([])
        setSelectedMemberCandidateIds(new Set())
        onPoolRefresh()
        return
      }
      console.error('[PoolExtractionModal] Failed to remove members:', err)
    }
  }, [pool, selectedMemberCandidateIds, onPoolRefresh])

  // Default: select all pool members when pool opens or is replaced
  const memberIdsKey = useMemo(() => {
    const ids = [
      ...localMembers.map(m => m.candidate_id),
      ...pendingMembers
        .filter(p => !localMembers.some(m => m.candidate_id === p.candidate_id))
        .map(p => p.candidate_id),
    ]
    return ids.slice().sort().join('\0')
  }, [localMembers, pendingMembers])

  useEffect(() => {
    if (!open || modalState !== 'prepare') return
    if (!memberIdsKey) {
      setSelectedMemberCandidateIds(new Set())
      return
    }
    setSelectedMemberCandidateIds(new Set(memberIdsKey.split('\0')))
  }, [open, modalState, pool?.id, memberIdsKey])

  // ── Start extraction ─────────────────────────────────────────────────────
  const handleStartExtraction = useCallback(async () => {
    const candidateIds = selectedExtractionIds
    if (candidateIds.length < 2) {
      setProgress(prev => ({
        ...prev,
        workflowStatus: 'failed',
        errors: ['请至少勾选 2 个脑区后再开始提取'],
      }))
      setModalState('result')
      return
    }

    startTimeRef.current = Date.now()
    cancelledRef.current = false

    console.info('[PoolExtractionModal] Starting extraction:', {
      workflowType,
      provider,
      modelName,
      candidateCount: candidateIds.length,
      poolMemberCount: displayMembers.length,
      hasResourceId: !!pool?.resource_id,
      hasBatchId: !!pool?.batch_id,
      dryRun,
    })

    const scope = {
      resource_id: pool?.resource_id ?? undefined,
      batch_id: pool?.batch_id ?? undefined,
      source_atlas: pool?.source_atlas ?? 'AAL3',
      granularity_level: pool?.granularity_level ?? 'macro',
      granularity_family: pool?.granularity_family ?? undefined,
    }

    try {
      if (isFunctionPoolWorkflow(workflowType)) {
        setModalState('progress')
        setProgress(prev => ({
          ...prev,
          workflowRunId: '',
          workflowStatus: 'running',
          progressPercent: 0,
          processedPacks: 0,
          totalPacks: candidateIds.length,
          successPacks: 0,
          failedPacks: 0,
          connectionsFound: 0,
          parsedNoConnCount: 0,
          createdCount: 0,
          updatedCount: 0,
          noConnectionCount: 0,
          providerCallCount: 0,
          modelCalls: 0,
          promptSent: 0,
          concurrency: 1,
          averagePackSec: null,
          estimatedRemainingSec: null,
          zeroDiags: [],
          errors: [],
          elapsedSec: 0,
          startedAt: new Date().toISOString(),
          lastPauseResponse: '',
          lastPauseError: '',
          lastCancelResponse: '',
          lastCancelError: '',
        }))

        const fnResponse = await runSameGranularityFunctionExtraction({
          provider,
          model_name: modelName || undefined,
          candidate_ids: candidateIds,
          scope,
          dry_run: dryRun,
          create_mirror_records: !dryRun,
          create_triples: !dryRun,
          create_evidence: !dryRun,
        })

        const fnStatus = fnResponse.status ?? (dryRun ? 'dry_run' : 'succeeded')
        setProgress(prev => ({
          ...prev,
          workflowRunId: fnResponse.run_id ?? '',
          workflowStatus: fnStatus,
          progressPercent: 100,
          processedPacks: fnResponse.candidate_count ?? candidateIds.length,
          totalPacks: fnResponse.candidate_count ?? candidateIds.length,
          successPacks: fnResponse.function_count ?? 0,
          createdCount: fnResponse.mirror_function_created_count ?? 0,
          errors: fnResponse.warnings ?? [],
          elapsedSec: Math.round((Date.now() - startTimeRef.current) / 1000),
        }))
        setModalState('result')
        return
      }

      const compositeWorkflowType = resolveCompositeWorkflowType(workflowType)
      if (!compositeWorkflowType) {
        throw new Error(`不支持的提取类型: ${workflowType}`)
      }

      const payload = {
        workflow_type: compositeWorkflowType as 'connection_with_function' | 'circuit_with_function_steps' | 'triple_generation',
        provider,
        model_name: modelName || undefined,
        dry_run: dryRun,
        candidate_ids: candidateIds,
        resource_id: scope.resource_id,
        batch_id: scope.batch_id,
        source_atlas: scope.source_atlas,
        granularity_level: scope.granularity_level,
        granularity_family: scope.granularity_family,
        create_mirror_records: !dryRun,
        create_evidence: !dryRun,
      }

      const response: CompositeWorkflowStartResponse = await startCompositeWorkflow(payload)

      const packCountFromResponse = ((response as any).pack_count as number | undefined)
        ?? (response.pair_count ? Math.ceil(response.pair_count / 40) : 0)
      const totalPacks = packCountFromResponse || selectedPackEstimate || estimatePackCount(computePairCount(candidateIds.length))

      const startedAt = new Date().toISOString()
      setProgress({
        workflowRunId: response.workflow_run_id,
        workflowStatus: response.status,
        progressPercent: response.progress_percent ?? 0,
        processedPacks: 0,
        totalPacks,
        successPacks: 0,
        failedPacks: 0,
        noConnectionPacks: 0,
        connectionsFound: 0,
        parsedNoConnCount: 0,
        createdCount: 0,
        updatedCount: 0,
        mergedCount: 0,
        skippedDupCount: 0,
        noConnectionCount: 0,
        providerCallCount: 0,
        modelCalls: 0,
        promptSent: 0,
        inFlightPacks: 0,
        concurrency: 1,
        averagePackSec: null,
        estimatedRemainingSec: null,
        zeroDiags: [],
        errors: [],
        elapsedSec: 0,
        startedAt,
        lastPauseResponse: '',
        lastPauseError: '',
        lastCancelResponse: '',
        lastCancelError: '',
      })
      setModalState('progress')
    } catch (err) {
      console.error('[PoolExtractionModal] Failed to start workflow:', err instanceof Error ? err.message : String(err))
      setProgress(prev => ({
        ...prev,
        workflowStatus: 'failed',
        errors: [err instanceof Error ? err.message : String(err)],
      }))
      setModalState('result')
    }
  }, [selectedExtractionIds, selectedPackEstimate, displayMembers.length, pool, provider, modelName, dryRun, workflowType])

  // ── Cancel extraction ─────────────────────────────────────────────────────
  // ── Pause / Resume ──────────────────────────────────────────────────────
  const handlePause = useCallback(async () => {
    console.log('[PoolExtractionModal] pause clicked', {
      workflowRunId: progress.workflowRunId,
      status: progress.workflowStatus,
    })
    const wfId = progress.workflowRunId
    if (!wfId) {
      setProgress(prev => ({ ...prev, errors: [...prev.errors, '缺少 workflow_run_id，无法暂停'] }))
      return
    }
    if (pauseInFlightRef.current) return
    pauseInFlightRef.current = true
    setPausing(true)
    setProgress(prev => ({ ...prev, workflowStatus: 'pause_requested' }))
    try {
      const resp = await pauseCompositeWorkflow(wfId)
      setProgress(prev => ({
        ...prev,
        workflowStatus: resolvePolledWorkflowStatus(prev.workflowStatus, resp.status as string),
      }))
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setProgress(prev => ({
        ...prev,
        workflowStatus: 'running',
        errors: [...prev.errors, `暂停失败: ${msg}`],
        lastPauseError: msg,
      }))
    } finally {
      pauseInFlightRef.current = false
      setPausing(false)
    }
  }, [progress.workflowRunId, progress.workflowStatus])

  const handleResume = useCallback(async () => {
    const wfId = progress.workflowRunId
    if (!wfId) {
      setProgress(prev => ({ ...prev, errors: [...prev.errors, '缺少 workflow_run_id，无法继续'] }))
      return
    }
    setResuming(true)
    try {
      const resp = await resumeCompositeWorkflow(wfId)
      setProgress(prev => ({
        ...prev,
        workflowStatus: (resp.status as string) === 'running' ? 'running' : prev.workflowStatus,
        errors: resp.warnings?.length ? [...prev.errors, ...resp.warnings] : prev.errors,
      }))
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setProgress(prev => ({ ...prev, errors: [...prev.errors, `继续失败: ${msg}`] }))
    } finally {
      setResuming(false)
    }
  }, [progress.workflowRunId])

  const handleCancel = useCallback(async () => {
    console.log('[PoolExtractionModal] cancel clicked', {
      workflowRunId: progress.workflowRunId,
      status: progress.workflowStatus,
    })
    const wfId = progress.workflowRunId
    if (!wfId) {
      setProgress(prev => ({ ...prev, errors: [...prev.errors, '缺少 workflow_run_id，无法取消'] }))
      return
    }
    if (cancelInFlightRef.current) return
    cancelInFlightRef.current = true
    setCancelling(true)
    setProgress(prev => ({ ...prev, workflowStatus: 'cancelling' }))
    try {
      const resp = await cancelCompositeWorkflow(wfId, {
        cleanup: true,
        reason: 'user_cancelled_from_pool_extraction_modal',
      })
      cancelledRef.current = true
      if (pollingRef.current) clearInterval(pollingRef.current)
      const nextStatus = resp.status as string
      const cancelErrors = (resp.errors ?? []).filter((e): e is string => Boolean(e))
      setProgress(prev => ({
        ...prev,
        workflowStatus: nextStatus,
        lastCancelResponse: JSON.stringify(resp),
        lastCancelError: cancelErrors[0] ?? '',
        errors: cancelErrors.length ? [...prev.errors, ...cancelErrors] : prev.errors,
      }))
      if (isTerminalWorkflowStatus(nextStatus) || nextStatus === 'cancelled' || nextStatus === 'cancelling') {
        setModalState('result')
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setProgress(prev => ({
        ...prev,
        workflowStatus: 'running',
        errors: [...prev.errors, `取消失败: ${msg}`],
        lastCancelError: msg,
      }))
    } finally {
      cancelInFlightRef.current = false
      setCancelling(false)
    }
  }, [progress.workflowRunId, progress.workflowStatus])

  // ── Local elapsed timer (runs every 1s independently of API polling) ──────
  useEffect(() => {
    if (modalState !== 'progress') return
    const timer = setInterval(() => {
      setProgress(prev => ({ ...prev, elapsedSec: (Date.now() - startTimeRef.current) / 1000 }))
    }, 1000)
    return () => clearInterval(timer)
  }, [modalState])

  // ── Polling effect (1s interval) ──────────────────────────────────────────
  useEffect(() => {
    if (modalState !== 'progress' || !progress.workflowRunId) return

    pollingRef.current = setInterval(async () => {
      if (cancelledRef.current) {
        if (pollingRef.current) clearInterval(pollingRef.current)
        return
      }

      try {
        const detail: CompositeWorkflowRunRead = await getCompositeWorkflowRun(
          progress.workflowRunId,
        )

        // ── Resolve the best progress source ──────────────────────────────
        // Priority: step.execution_summary (live) > detail.provider_audit (merged) >
        //            result_summary (aggregate) > result_summary.provider_audit (nested)
        const connStep = (detail.steps ?? []).find(s => s.step_key === 'extract_connections')
        const stepExec = (connStep?.execution_summary ?? {}) as Record<string, unknown>
        const stepPa = (stepExec.provider_audit ?? {}) as Record<string, unknown>
        const topPa = (detail.provider_audit ?? {}) as Record<string, unknown>
        const rs = (detail.result_summary ?? {}) as Record<string, unknown>
        const rsPa = (rs.provider_audit ?? {}) as Record<string, unknown>
        const terminal = isTerminalWorkflowStatus(detail.status)
        const liveSources = [rs, stepExec, stepPa, topPa, rsPa]
        const finalSources = [rs, rsPa, stepExec, stepPa, topPa]

        // All counters — prefer result_summary after workflow finishes
        let processedPacks = readProgressMetric(
          terminal ? finalSources : liveSources,
          'processed_pack_count',
          'executed_pack_count',
        )
        const plannedPacks = readProgressMetric(
          terminal ? finalSources : liveSources,
          'pack_count',
          'planned_pack_count',
        )
        const totalPacks = plannedPacks ?? progress.totalPacks
        const successPacks = readProgressMetric(
          terminal ? finalSources : liveSources,
          'succeeded_pack_count',
          'provider_success_count',
        )
        const failedPacks = readProgressMetric(
          terminal ? finalSources : liveSources,
          'failed_pack_count',
        ) ?? 0
        const parsedProj = readProgressMetric(
          terminal ? finalSources : liveSources,
          'parsed_projection_count',
        )
        const parsedNoConn = readProgressMetric(
          terminal ? finalSources : liveSources,
          'parsed_no_connection_count',
        )
        const createdProj = readProgressMetric(
          terminal ? finalSources : liveSources,
          'created_projection_count',
        )
        const updatedProj = readProgressMetric(
          terminal ? finalSources : liveSources,
          'updated_projection_count',
        )
        const mergedProj = readProgressMetric(
          terminal ? finalSources : liveSources,
          'merged_projection_count',
        )
        const skippedDup = readProgressMetric(
          terminal ? finalSources : liveSources,
          'skipped_duplicate_count',
        )
        const noConn = readProgressMetric(
          terminal ? finalSources : liveSources,
          'no_connection_count',
        )
        const noConnectionPacks = readProgressMetric(
          terminal ? finalSources : liveSources,
          'no_connection_pack_count',
        ) ?? 0
        const providerCalls = readProgressMetric(
          terminal ? finalSources : liveSources,
          'provider_call_count',
        )
        const promptSent = readProgressMetric(
          terminal ? finalSources : liveSources,
          'prompt_sent_count',
        )
        const modelCalls = readProgressMetric(
          terminal ? finalSources : liveSources,
          'model_call_count',
          'planned_model_call_count',
        )

        if (processedPacks === null || (terminal && processedPacks === 0)) {
          const summaryPacks = countFinishedPacks(rs.pack_summaries ?? stepExec.pack_summaries)
          if (summaryPacks > 0) processedPacks = summaryPacks
        }
        processedPacks = processedPacks ?? 0

        const backendAvgSec = readProgressMetric(
          terminal ? finalSources : liveSources,
          'average_pack_sec',
        )
        const backendEstRem = readProgressMetric(
          terminal ? finalSources : liveSources,
          'estimated_remaining_sec',
        )
        const backendConcurrency = readProgressMetric(
          terminal ? finalSources : liveSources,
          'concurrency',
        )
        const inFlightCount = readProgressMetric(
          terminal ? finalSources : liveSources,
          'in_flight_pack_count',
        )
        const packProgressPct = readProgressMetric(
          terminal ? finalSources : liveSources,
          'pack_progress_percent',
        )

        const localAvgSec: number | null = processedPacks > 0
          ? ((Date.now() - startTimeRef.current) / 1000) / processedPacks
          : null
        const remainingPacks = Math.max(0, totalPacks - processedPacks - (inFlightCount ?? 0))
        const avgSec: number | null = backendAvgSec ?? localAvgSec
        const estRemaining: number | null = backendEstRem ?? (avgSec !== null ? avgSec * remainingPacks : null)

        // zero diagnostics — try multiple sources
        const zeroDiags =
          (stepExec.connection_zero_diagnostics as string[] | undefined)
          ?? (rs.connection_zero_diagnostics as string[] | undefined)
          ?? (rsPa.connection_zero_diagnostics as string[] | undefined)
          ?? []

        // Collect errors from pack_summaries across all sources
        const allPackSummaries = [
          stepPa.pack_summaries,
          stepExec.pack_summaries,
          topPa.pack_summaries,
          rsPa.pack_summaries,
          rs.pack_summaries,
        ]
        const packErrors: string[] = []
        for (const ps of allPackSummaries) {
          if (!Array.isArray(ps)) continue
          for (const pack of ps) {
            if (!pack || typeof pack !== 'object') continue
            const pe = (pack as Record<string, unknown>)
            const err = (pe.error ?? pe.error_message ?? pe.parse_error) as string | undefined
            if (err && !packErrors.includes(err)) packErrors.push(err)
          }
        }

        // Track last poll time and data source for debug display
        lastPollRef.current = new Date().toISOString().slice(11, 19)
        if (Object.keys(stepExec).length > 3) {
          dataSourceRef.current = 'step.execution_summary'
        } else if (Object.keys(topPa).length > 3) {
          dataSourceRef.current = 'provider_audit'
        } else {
          dataSourceRef.current = 'result_summary (no live data)'
        }

        // Debug: log first poll and every 15th poll so we can see raw data
        const pollCount = (Date.now() - startTimeRef.current) / 1000
        const shouldLog = pollCount < 3 || Math.round(pollCount) % 15 === 0
        if (shouldLog) {
          console.info('[PoolExtractionModal] Poll snapshot', {
            status: detail.status,
          processedPacks,
          totalPacks,
          successPacks,
          failedPacks,
          parsedProj,
          createdProj,
          providerCalls,
            stepKeys: Object.keys(stepExec).slice(0, 12),
            topPaKeys: Object.keys(topPa).slice(0, 12),
          })
        }

        setProgress(prev => ({
          workflowRunId: detail.id,
          workflowStatus: resolvePolledWorkflowStatus(prev.workflowStatus, detail.status),
          progressPercent: packProgressPct ?? detail.progress_percent ?? (
            totalPacks > 0
              ? ((processedPacks + (inFlightCount ?? 0)) / totalPacks) * 100
              : 0
          ),
          processedPacks,
          totalPacks: totalPacks || prev.totalPacks,
          successPacks: successPacks ?? 0,
          failedPacks,
          noConnectionPacks: noConnectionPacks ?? 0,
          connectionsFound: parsedProj ?? 0,
          parsedNoConnCount: parsedNoConn ?? 0,
          createdCount: createdProj ?? 0,
          updatedCount: updatedProj ?? 0,
          mergedCount: mergedProj ?? 0,
          skippedDupCount: skippedDup ?? 0,
          noConnectionCount: noConn ?? 0,
          providerCallCount: providerCalls ?? 0,
          modelCalls: modelCalls ?? 0,
          promptSent: promptSent ?? 0,
          inFlightPacks: inFlightCount ?? 0,
          concurrency: backendConcurrency ?? 1,
          averagePackSec: avgSec,
          estimatedRemainingSec: estRemaining,
          zeroDiags,
          errors: packErrors.slice(0, 10),
          elapsedSec: prev.elapsedSec,
          startedAt: prev.startedAt,
          lastPauseResponse: prev.lastPauseResponse,
          lastPauseError: prev.lastPauseError,
          lastCancelResponse: prev.lastCancelResponse,
          lastCancelError: prev.lastCancelError,
        }))

        if (isTerminalWorkflowStatus(detail.status) || cancelledRef.current) {
          if (pollingRef.current) clearInterval(pollingRef.current)
          console.info('[PoolExtractionModal] Extraction finished:', {
            status: detail.status,
            workflowRunId: detail.id,
            parsedProjections: parsedProj,
            createdProjections: createdProj,
            updatedProjections: updatedProj,
            processedPacks,
            totalPacks,
            zeroDiags,
            packErrors: packErrors.slice(0, 3),
            stepExecKeys: Object.keys(stepExec).slice(0, 10),
            topPaKeys: Object.keys(topPa).slice(0, 10),
          })
          // Surface backend errors for failed/cancelled workflows
          if (detail.status === 'failed' || detail.status === 'failed_provider_not_called' ||
              detail.status === 'failed_provider_empty_response' || detail.status === 'failed_parse_error' ||
              detail.status === 'failed_no_output' || detail.status === 'cleanup_failed') {
            const backendErrors = detail.errors ?? []
            if (backendErrors.length > 0) {
              packErrors.push(...backendErrors)
            }
            // Also pull cleanup_errors and cleanup_warnings from result_summary
            const rs2 = (detail.result_summary ?? {}) as Record<string, unknown>
            const cleanupErrors = rs2.cleanup_errors as string[] | undefined
            const cleanupWarnings = rs2.cleanup_warnings as string[] | undefined
            if (cleanupErrors?.length) {
              for (const ce of cleanupErrors) {
                if (!packErrors.includes(ce)) packErrors.push(ce)
              }
            }
            if (cleanupWarnings?.length) {
              for (const cw of cleanupWarnings) {
                if (!packErrors.includes(cw)) packErrors.push(cw)
              }
            }
          }
          setModalState('result')
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        // Skip logging 404s (workflow run cleaned up) as errors — they're expected during cancel cleanup
        if (err && typeof err === 'object' && 'status' in err && (err as any).status !== 404) {
          console.error('[PoolExtractionModal] Poll error:', msg)
        }
        setProgress(prev => ({
          ...prev,
          errors: [...prev.errors, msg].slice(0, 5),
        }))
      }
    }, 1000)

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [modalState, progress.workflowRunId, progress.totalPacks])

  // ── Reset on close ───────────────────────────────────────────────────────
  const handleClose = useCallback(async () => {
    if (pollingRef.current) clearInterval(pollingRef.current)
    cancelledRef.current = true
    // If extraction is in progress, attempt to cancel the backend workflow
    const wfId = progress.workflowRunId
    if (wfId && modalState === 'progress') {
      try {
        await fetch(`/api/llm-extraction/composite-workflows/${wfId}/cancel`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cleanup: true, reason: 'user_closed_modal' }),
        })
      } catch { /* fire-and-forget */ }
    }
    setModalState('prepare')
    setWizardStep(1)
    setLockedPanelHeight(520)
    setSearchTerm('')
    setSelectedMemberCandidateIds(new Set())
    setDryRun(false)
    setCancelling(false)
    setShowErrors(false)
    setLocalPoolId(null)
    setPendingMembers([])
    onClose()
  }, [onClose, progress.workflowRunId, modalState])

  if (!open) return null

  // ── Render: step 1 (pool selection) ──────────────────────────────────────
  const renderStep1 = () => (
    <>
      {/* Header */}
      <div className="modal-header">
        <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: '#1a1a2e' }}>
          ⚡ {TYPE_LABELS[workflowType] || workflowType || '全量提取'}
        </h3>
        <button className="btn-close" onClick={handleClose}>x</button>
      </div>

      <div style={{ padding: '0 20px', flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Scope info */}
        <div className="modal-section">
          <p className="modal-section-title">提取范围</p>
          {pool ? (
            <>
              <div className="modal-section-row">
                <span className="label">Atlas</span>
                <span className="value">{pool.source_atlas}</span>
              </div>
              <div className="modal-section-row">
                <span className="label">Granularity</span>
                <span className="value">
                  {pool.granularity_level}
                  {pool.granularity_family ? ` / ${pool.granularity_family}` : ''}
                </span>
              </div>
              <div className="modal-section-row">
                <span className="label">外部已选</span>
                <span className="value">
                  {selectedCount} 个 · 约 {externalPackEstimate} 包
                </span>
              </div>
              <div className="modal-section-row">
                <span className="label">池中脑区</span>
                <span className="value">{totalPooledCount} 个（与外部选中同步）</span>
              </div>
              {!poolMatchesExternal && selectedCount >= 2 && (
                <div style={{ marginTop: 8, padding: '8px 12px', background: '#fffbe6', borderRadius: 6, fontSize: 12, color: '#8c6d00' }}>
                  {addingMembers
                    ? '正在用外部选中的脑区更新提取池…'
                    : `提取池 (${totalPooledCount}) 与外部选中 (${selectedCount}) 不一致，请点击「用外部选中替换」或关闭后重新打开`}
                </div>
              )}
              <div className="modal-section-row">
                <span className="label">本次已选</span>
                <span className="value">{selectedExtractionIds.length} 个</span>
              </div>
              <div className="modal-section-row">
                <span className="label">本次配对</span>
                <span className="value">{selectedPairCount.toLocaleString()} 对 · 约 {selectedPackEstimate} 包</span>
              </div>
            </>
          ) : (
            <p style={{ color: '#888', fontStyle: 'italic', fontSize: 13 }}>
              未设置提取池 — 请在外部勾选脑区后点击「设为提取池」，或在此用表格选中替换
            </p>
          )}
        </div>

        {/* Member table */}
        <div className="modal-section" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <p className="modal-section-title">本次提取范围（在池中勾选）</p>

          {/* Search + actions bar */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              className="form-input"
              placeholder="搜索 ID 或名称..."
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              style={{ flex: 1, minWidth: 160, padding: '6px 10px', fontSize: 13, border: '1px solid #d0d7e2', borderRadius: 6 }}
            />
            <button className="llm-btn" onClick={handleSelectAll} disabled={filteredMembers.length === 0}>
              全选
            </button>
            <button className="llm-btn" onClick={handleSelectNone} disabled={selectedMemberCandidateIds.size === 0}>
              取消选择
            </button>
            <button
              className="llm-btn"
              onClick={handleReplaceWithSelected}
              disabled={selectedCount < 2 || addingMembers}
            >
              {addingMembers ? '更新中...' : `用外部选中替换 (${selectedCount})`}
            </button>
            <button
              className="llm-btn llm-btn-danger"
              onClick={handleRemoveSelected}
              disabled={selectedMemberCandidateIds.size === 0}
            >
              移除选中 ({selectedMemberCandidateIds.size})
            </button>
          </div>

          {/* Member list */}
          <div style={{ flex: 1, overflow: 'auto', border: '1px solid #e0e7f0', borderRadius: 6 }}>
            {addingMembers && displayMembers.length === 0 ? (
              <div style={{ padding: 24, textAlign: 'center', color: '#999', fontSize: 13 }}>正在加载池成员...</div>
            ) : filteredMembers.length === 0 ? (
              <div style={{ padding: 24, textAlign: 'center', color: '#999', fontSize: 13 }}>
                {searchTerm ? '没有匹配的成员' : '池中没有成员 — 请在外部勾选脑区并设为提取池'}
              </div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ background: '#f8faff', borderBottom: '1px solid #e0e7f0' }}>
                    <th style={{ width: 40, padding: '8px 6px', textAlign: 'center' }}>
                      <input
                        type="checkbox"
                        checked={filteredMembers.length > 0 && filteredMembers.every(m => selectedMemberCandidateIds.has(m.candidate_id))}
                        onChange={() => {
                          const allSelected = filteredMembers.every(m => selectedMemberCandidateIds.has(m.candidate_id))
                          if (allSelected) { handleSelectNone() } else { handleSelectAll() }
                        }}
                      />
                    </th>
                    <th style={{ width: 40, padding: '8px 6px', textAlign: 'left', color: '#555', fontWeight: 500 }}>#</th>
                    <th style={{ padding: '8px 6px', textAlign: 'left', color: '#555', fontWeight: 500 }}>脑区名称</th>
                    <th style={{ padding: '8px 6px', textAlign: 'left', color: '#555', fontWeight: 500 }}>ID</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredMembers.map((m, idx) => (
                    <tr
                      key={m.candidate_id}
                      style={{
                        borderBottom: '1px solid #f0f2f5',
                        background: selectedMemberCandidateIds.has(m.candidate_id) ? '#f0f7ff' : undefined,
                        cursor: 'pointer',
                      }}
                      onClick={() => handleToggleMember(m.candidate_id)}
                    >
                      <td style={{ padding: '6px', textAlign: 'center' }}>
                        <input
                          type="checkbox"
                          checked={selectedMemberCandidateIds.has(m.candidate_id)}
                          onChange={(e) => { e.stopPropagation(); handleToggleMember(m.candidate_id) }}
                        />
                      </td>
                      <td style={{ padding: '6px', color: '#888' }}>{idx + 1}</td>
                      <td style={{ padding: '6px', fontWeight: 500 }}>{m.label}</td>
                      <td style={{ padding: '6px', fontFamily: 'monospace', fontSize: 11, color: '#888' }}>{shortId(m.candidate_id)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="modal-footer">
        <button className="llm-btn" onClick={handleClose}>取消</button>
        <button
          className="llm-btn llm-btn-primary"
          onClick={() => setWizardStep(2)}
          disabled={!pool || selectedExtractionIds.length < 2 || addingMembers || !poolMatchesExternal}
        >
          下一步
        </button>
      </div>
    </>
  )

  // ── Render: step 2 (model config) ────────────────────────────────────────
  const renderStep2 = () => (
    <>
      <div className="modal-header">
        <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: '#1a1a2e' }}>
          ⚡ {TYPE_LABELS[workflowType] || workflowType || '全量提取'}
        </h3>
        <button className="btn-close" onClick={handleClose}>x</button>
      </div>

      <div style={{ padding: '0 20px', flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Scope summary */}
        <div className="modal-section">
          <p className="modal-section-title">提取配置</p>
          <div className="modal-section-row">
            <span className="label">已选 {selectedExtractionIds.length} 个脑区 · {selectedPairCount.toLocaleString()} 对 · 约 {selectedPackEstimate} 包</span>
          </div>
        </div>

        {/* Model config */}
        <div className="modal-section">
          <p className="modal-section-title">模型配置</p>
          <ModelSelector
            provider={provider}
            modelName={modelName}
            onProviderChange={onProviderChange}
            onModelChange={onModelChange}
            providers={providers}
          />
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, fontSize: 13, color: '#888', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={dryRun}
              onChange={e => setDryRun(e.target.checked)}
            />
            Dry run（仅预览，不实际调用 LLM）
          </label>
        </div>
      </div>

      {/* Footer */}
      <div className="modal-footer">
        <button className="llm-btn" onClick={() => setWizardStep(1)}>上一步</button>
        <button className="llm-btn" onClick={handleClose}>取消</button>
        <button
          className="llm-btn llm-btn-primary"
          onClick={handleStartExtraction}
          disabled={!pool || selectedExtractionIds.length < 2}
        >
          开始提取 ({selectedExtractionIds.length} 区)
        </button>
      </div>
    </>
  )

  // ── Render: progress ──────────────────────────────────────────────────────
  const avgSec = progress.averagePackSec ?? (progress.processedPacks > 0 ? progress.elapsedSec / progress.processedPacks : null)
  const remSec = progress.estimatedRemainingSec ?? (avgSec !== null ? avgSec * Math.max(0, progress.totalPacks - progress.processedPacks) : null)

  const renderProgress = () => {
    const processed = progress.processedPacks
    const total = Math.max(progress.totalPacks, 1)
    const running = !isTerminalWorkflowStatus(progress.workflowStatus)
      && progress.workflowStatus !== 'paused'
      && progress.workflowStatus !== 'pause_requested'
    const effectiveProcessed = processed + (progress.inFlightPacks || 0)
    const currentPack = effectiveProcessed > processed ? effectiveProcessed : (processed > 0 ? processed : 0)
    const progressPct = Math.min(
      progress.progressPercent,
      (effectiveProcessed / total) * 100,
      100,
    )
    return (
    <>
      <div className="modal-header">
        <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: '#1a1a2e' }}>
          {progress.workflowStatus === 'pause_requested'
            ? '⏸ 正在暂停...'
            : progress.workflowStatus === 'paused'
              ? '⏸ 已暂停'
              : '提取中...'}
        </h3>
        <button className="btn-close" onClick={handleClose}>x</button>
      </div>

      <div style={{ padding: '0 20px', display: 'flex', flexDirection: 'column', gap: 16, flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {/* Progress bar */}
        <div className="modal-section">
          <p className="modal-section-title">进度</p>
          <div className="pool-bar-progress-track" style={{ height: 10, borderRadius: 5, marginBottom: 8 }}>
            <div
              className="pool-bar-progress-fill"
              style={{
                width: `${progressPct}%`,
                height: '100%',
                borderRadius: 5,
                transition: 'width 0.5s ease',
              }}
            />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: '#555' }}>
            <span>
              {effectiveProcessed > processed
                ? `正在处理第 ${currentPack}/${total} 包`
                : processed > 0
                  ? `已完成 ${processed}/${total} 包`
                  : progress.modelCalls > 0
                    ? `已构建 ${progress.modelCalls} 包，准备调用…`
                    : '准备中…'}
            </span>
            <span>{Math.round(progressPct)}%</span>
          </div>
        </div>

        {/* Pack stats */}
        <div className="modal-section">
          <p className="modal-section-title">包统计</p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
            <div style={{ background: '#f8faff', borderRadius: 6, padding: '10px 12px', textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#2563eb' }}>
                {effectiveProcessed}/{total}
              </div>
              <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>包进度</div>
            </div>
            <div style={{ background: '#f6ffed', borderRadius: 6, padding: '10px 12px', textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#389e0d' }}>
                {progress.successPacks > 0 ? progress.successPacks : 0}
              </div>
              <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>成功包</div>
            </div>
            <div style={{ background: '#fff2f0', borderRadius: 6, padding: '10px 12px', textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: progress.failedPacks > 0 ? '#cf1322' : '#bbb' }}>
                {progress.failedPacks}
              </div>
              <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>失败包</div>
            </div>
            <div className="modal-metric-card" style={{ background: progress.noConnectionPacks > 0 ? '#fff7e6' : '#fafafa' }}>
              <div className="metric-label" style={{ color: '#d48806' }}>无连接包</div>
              <div className="metric-value" style={{ color: '#d48806' }}>
                {progress.noConnectionPacks > 0 ? progress.noConnectionPacks : '—'}
              </div>
            </div>
          </div>
        </div>

        {/* Timing */}
        <div className="modal-section">
          <p className="modal-section-title">时序</p>
          <div className="modal-section-row">
            <span className="label">已用时间</span>
            <span className="value">{elapsedStr(progress.elapsedSec)}</span>
          </div>
          {avgSec !== null && (
            <div className="modal-section-row">
              <span className="label">平均每包</span>
              <span className="value">{elapsedStr(avgSec)}</span>
            </div>
          )}
          {remSec !== null && remSec > 0 && (
            <div className="modal-section-row">
              <span className="label">预估剩余</span>
              <span className="value">{elapsedStr(remSec)}</span>
            </div>
          )}
          <div className="modal-section-row">
            <span className="label">处理模式</span>
            <span className="value">逐包串行</span>
          </div>
        </div>

        {/* Connections found */}
        <div className="modal-section">
          <p className="modal-section-title">提取统计</p>
          <div className="modal-section-row">
            <span className="label">已解析投射</span>
            <span className="value" style={{ fontSize: 16, fontWeight: 600, color: progress.connectionsFound > 0 ? '#2563eb' : '#888' }}>
              {progress.connectionsFound > 0 ? progress.connectionsFound : '—'}
            </span>
          </div>
          <div className="modal-section-row">
            <span className="label">判定无连接</span>
            <span className="value" style={{ fontSize: 13, color: '#d48806' }}>
              {progress.parsedNoConnCount > 0 ? progress.parsedNoConnCount : '—'}
            </span>
          </div>
          <div className="modal-section-row">
            <span className="label">已写入 Mirror (新增)</span>
            <span className="value" style={{ fontSize: 13, color: progress.createdCount > 0 ? '#389e0d' : '#888' }}>
              {progress.createdCount > 0 ? progress.createdCount : '—'}
            </span>
          </div>
          <div className="modal-section-row">
            <span className="label">已合并 Mirror (更新)</span>
            <span className="value" style={{ fontSize: 13, color: progress.mergedCount > 0 ? '#2563eb' : '#888' }}>
              {progress.mergedCount > 0 ? progress.mergedCount : '—'}
            </span>
          </div>
          <div className="modal-section-row">
            <span className="label">重复跳过</span>
            <span className="value" style={{ fontSize: 13, color: progress.skippedDupCount > 0 ? '#888' : '#888' }}>
              {progress.skippedDupCount > 0 ? progress.skippedDupCount : '—'}
            </span>
          </div>
          <div className="modal-section-row">
            <span className="label">No Connection</span>
            <span className="value" style={{ fontSize: 13, color: '#888' }}>
              {progress.noConnectionCount > 0 ? progress.noConnectionCount : '—'}
            </span>
          </div>
          {progress.totalPacks > 0 && progress.processedPacks > 0 && progress.successPacks === 0 && progress.failedPacks === 0 && (
            <div style={{ marginTop: 8, padding: '8px 12px', background: '#fff7e6', borderRadius: 6, fontSize: 12, color: '#d48806' }}>
              ⚠ 包已处理 ({progress.processedPacks}/{progress.totalPacks})，但结果统计缺失（成功包=0 且 失败包=0），请检查 execution_summary 写入。
            </div>
          )}
          {progress.totalPacks > 0 && (
            <div style={{ marginTop: 8, padding: '8px 12px', background: '#fffbe6', borderRadius: 6, fontSize: 12, color: '#8c6d00' }}>
              {progress.processedPacks === 0 && progress.providerCallCount === 0
                ? (progress.modelCalls > 0
                  ? <div>⏳ 已构建 {progress.modelCalls} 个 prompt 包，即将逐包调用 LLM…</div>
                  : (progress.workflowStatus === 'running' || progress.workflowStatus === 'pending'
                    ? <div>⏳ 后台任务启动中…已用时 {Math.round(progress.elapsedSec)} 秒</div>
                    : <div>⚠ 后台任务可能未启动，请查看后端日志</div>
                  )
                )
                : effectiveProcessed > processed
                  ? <div>⏳ 正在处理第 {currentPack}/{progress.totalPacks} 包…</div>
                : progress.processedPacks > 0 && progress.connectionsFound === 0 && progress.parsedNoConnCount === 0
                  ? (progress.zeroDiags.length > 0
                    ? progress.zeroDiags.map((d: string, i: number) => <div key={i}>⚠ {d}</div>)
                    : (progress.parsedNoConnCount > 0
                      ? <div>⚠ 模型已处理全部 pack，但所有 pair 均被判定为无连接</div>
                      : <div>⚠ 已处理 {progress.processedPacks}/{progress.totalPacks} 包，暂未解析到连接</div>
                    )
                  )
                  : progress.connectionsFound > 0
                    ? <div style={{ color: '#389e0d' }}>已提取 {progress.connectionsFound} 条连接</div>
                    : null
              }
            </div>
          )}
        </div>

        {/* Recent errors — collapsible */}
        {progress.errors.length > 0 && (
          <div className="modal-section">
            <p
              className="modal-section-title"
              style={{ color: '#cf1322', cursor: 'pointer', userSelect: 'none' }}
              onClick={() => setShowErrors(!showErrors)}
            >
              {showErrors ? '▾' : '▸'} 近期异常 ({progress.errors.length})
            </p>
            {showErrors && (
              <div style={{ maxHeight: 100, overflow: 'auto', background: '#fff2f0', borderRadius: 6, padding: '8px 12px' }}>
                {progress.errors.map((err, i) => (
                  <div key={i} style={{ fontSize: 12, color: '#cf1322', marginBottom: 4, fontFamily: 'monospace' }}>
                    {err.length > 120 ? `${err.slice(0, 120)}…` : err}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer — sticky, always clickable */}
      <div
        className="modal-footer"
        style={{
          flexShrink: 0,
          position: 'sticky',
          bottom: 0,
          zIndex: 20,
          pointerEvents: 'auto',
          background: '#fafafa',
          borderTop: '1px solid var(--border)',
        }}
      >
        {/* Pause / Resume */}
        {progress.workflowStatus === 'pause_requested' || progress.workflowStatus === 'paused' ? (
          <button
            className="llm-btn llm-btn-primary"
            type="button"
            disabled={resuming}
            onClick={handleResume}
          >
            {resuming ? '恢复中...' : progress.workflowStatus === 'paused' ? '已暂停' : '继续提取'}
          </button>
        ) : (progress.workflowStatus === 'running' || progress.workflowStatus === 'pending') && progress.workflowRunId ? (
          <button
            className="llm-btn"
            type="button"
            disabled={pausing}
            onClick={handlePause}
          >
            {pausing ? '暂停中...' : '暂停'}
          </button>
        ) : null}
        <button
          className="llm-btn llm-btn-danger"
          type="button"
          disabled={cancelling || progress.workflowStatus === 'cleanup_done'}
          onClick={handleCancel}
        >
          {cancelling ? '取消中...' : '取消任务'}
        </button>
        <button className="llm-btn" onClick={handleClose} type="button">后台运行</button>
      </div>
    </>
    )
  }

  // ── Render: result ────────────────────────────────────────────────────────
  const isSuccess = progress.workflowStatus === 'succeeded' || progress.workflowStatus === 'cleanup_done'
  const isPartial = progress.workflowStatus === 'partially_succeeded'
  const isFailed = progress.workflowStatus === 'failed' || progress.failedPacks > 0
  const isCancelled = progress.workflowStatus === 'cancelled'
  const isCleanupFailed = progress.workflowStatus === 'cleanup_failed'
  const hasCleanupError = isCleanupFailed && progress.errors.length > 0

  const renderResult = () => (
    <>
      <div className="modal-header">
        <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: '#1a1a2e' }}>
          提取结果
        </h3>
        <button className="btn-close" onClick={handleClose}>x</button>
      </div>

      <div style={{ padding: '0 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* Status banner */}
        <div
          style={{
            padding: '12px 16px',
            borderRadius: 8,
            background: isCleanupFailed
              ? '#fff2f0'
              : isCancelled
                ? '#fffbe6'
                : isFailed
                  ? '#fff2f0'
                  : '#f6ffed',
            border: `1px solid ${
              isCleanupFailed ? '#ffa39e' : isCancelled ? '#ffe58f' : isFailed ? '#ffccc7' : '#b7eb8f'
            }`,
            textAlign: 'center',
          }}
        >
          <div style={{ fontSize: 16, fontWeight: 600, color: isCleanupFailed ? '#cf1322' : isCancelled ? '#d48806' : isFailed ? '#cf1322' : '#389e0d' }}>
            {isCleanupFailed
              ? '⚠ 取消失败（数据已清理）'
              : isCancelled
                ? '已取消'
                : isFailed
                  ? '部分失败'
                  : isPartial
                    ? '部分成功'
                    : '提取完成'}
          </div>
          <div style={{ fontSize: 13, color: '#666', marginTop: 4 }}>
            {isCleanupFailed
              ? '已停止提取但清理资源时出错'
              : isCancelled
                ? '用户取消了本次提取'
                : `${progress.processedPacks}/${progress.totalPacks} 包完成`}
          </div>
          {/* Show cleanup errors directly in banner */}
          {hasCleanupError && (
            <div style={{ marginTop: 8, padding: '6px 10px', background: '#fff1f0', borderRadius: 4, fontSize: 11, fontFamily: 'monospace', textAlign: 'left', maxHeight: 80, overflow: 'auto' }}>
              {progress.errors.slice(0, 3).map((e, i) => (
                <div key={i} style={{ color: '#cf1322' }}>{e.length > 150 ? e.slice(0, 150) + '…' : e}</div>
              ))}
            </div>
          )}
        </div>

        {/* Summary stats */}
        <div className="modal-section">
          <p className="modal-section-title">汇总</p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div style={{ background: '#f8faff', borderRadius: 6, padding: '10px 12px', textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#2563eb' }}>{progress.totalPacks}</div>
              <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>总包数</div>
            </div>
            <div style={{ background: '#f8faff', borderRadius: 6, padding: '10px 12px', textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#2563eb' }}>{progress.connectionsFound}</div>
              <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>连接数</div>
            </div>
            <div style={{ background: '#f6ffed', borderRadius: 6, padding: '10px 12px', textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#389e0d' }}>{progress.successPacks}</div>
              <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>成功包</div>
            </div>
            <div style={{ background: progress.failedPacks > 0 ? '#fff2f0' : '#f8faff', borderRadius: 6, padding: '10px 12px', textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: progress.failedPacks > 0 ? '#cf1322' : '#bbb' }}>
                {progress.failedPacks}
              </div>
              <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>失败包</div>
            </div>
          </div>
        </div>

        {/* Time */}
        <div className="modal-section">
          <div className="modal-section-row">
            <span className="label">总耗时</span>
            <span className="value">{elapsedStr(progress.elapsedSec)}</span>
          </div>
          {progress.processedPacks > 0 && (
            <div className="modal-section-row">
              <span className="label">平均每包</span>
              <span className="value">{elapsedStr(progress.elapsedSec / progress.processedPacks)}</span>
            </div>
          )}
        </div>

        {/* Error details — collapsible */}
        {progress.errors.length > 0 && (
          <div className="modal-section">
            <p
              className="modal-section-title"
              style={{ color: '#cf1322', cursor: 'pointer', userSelect: 'none', marginBottom: showErrors ? 12 : 0 }}
              onClick={() => setShowErrors(!showErrors)}
            >
              {showErrors ? '▾' : '▸'} 异常详情 ({progress.errors.length})
            </p>
            {showErrors && (
              <div style={{ maxHeight: 160, overflow: 'auto', background: '#fff2f0', borderRadius: 6, padding: '8px 12px' }}>
                {progress.errors.map((err, i) => (
                  <div key={i} style={{ fontSize: 12, color: '#cf1322', marginBottom: 6, fontFamily: 'monospace', lineHeight: 1.4 }}>
                    {err}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="modal-footer">
        <button className="llm-btn llm-btn-primary" onClick={handleClose}>
          关闭
        </button>
      </div>
    </>
  )

  // ── Render dispatcher ─────────────────────────────────────────────────────
  return (
    <div className="modal-overlay pool-extraction-modal" style={{ zIndex: 10000 }} onClick={() => {}}>
      <div
        ref={panelRef}
        className="modal-panel wide"
        onClick={e => e.stopPropagation()}
        style={{
          minHeight: wizardStep === 2 ? lockedPanelHeight : 520,
          maxHeight: '85vh',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {modalState === 'prepare' && wizardStep === 1 && renderStep1()}
        {modalState === 'prepare' && wizardStep === 2 && renderStep2()}
        {modalState === 'progress' && renderProgress()}
        {modalState === 'result' && renderResult()}
      </div>
    </div>
  )
}
