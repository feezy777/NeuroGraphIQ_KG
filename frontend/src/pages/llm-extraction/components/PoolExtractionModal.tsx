import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { ModelSelector } from './ModelSelector'
import {
  getCompositeWorkflowRun,
  startCompositeWorkflow,
  runSameGranularityFunctionExtraction,
  runCircuitExtraction,
  getCircuitExtractionRun,
  cancelCircuitExtractionRun,
  cancelCompositeWorkflow,
  pauseCompositeWorkflow,
  resumeCompositeWorkflow,
  retryFailedCompositeWorkflow,
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
import {
  getRegionPoolMemberIds,
  buildPackPlanPreview,
  buildPackConfigPayload,
  logPackPlanNext,
  type PackConfigPayload,
} from '../packPlanUtils'
import type { TaskPreset } from '../taskPresets'

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
  noFindingsPacks: number         // no_findings_pack_count — packs with no findings at all
  screenedLikelyCount: number     // screened_likely_connection_count — filtered likely connections
  connectionsFound: number       // parsed_projection_count
  parsedNoConnCount: number      // parsed_no_connection_count
  createdCount: number            // created_projection_count — new Mirror connections written
  updatedCount: number            // updated_projection_count — merged into existing
  mergedCount: number             // merged_projection_count — dedup-merged into existing
  skippedDupCount: number         // skipped_duplicate_count — exact duplicates skipped
  noConnectionCount: number       // no_connection_count — all no_connection entries
  functionCount: number           // parsed_function_count — for circuit/function extraction
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
  estimatedInputTokens: number
  estimatedOutputTokens: number
  actualPromptTokens: number
  actualCompletionTokens: number
  dryRunSamplePack: boolean
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
  preset?: import('../taskPresets').TaskPreset | null
  activeTab?: string
  connPool?: any
  connPooledIds?: Set<string>
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
  return null
}

function isCircuitPackWorkflow(workflowType: string, preset?: import('../taskPresets').TaskPreset | null): boolean {
  if (preset?.endpoint_type === 'circuit_extraction') return true
  return workflowType === 'circuit_with_function_steps' || workflowType === 'composite_circuit_with_function_and_steps'
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

function estimateCost(inputTokens: number, outputTokens: number): string {
  const inputPrice = 1.0   // ¥1 per 1M input tokens (DeepSeek CN)
  const outputPrice = 2.0  // ¥2 per 1M output tokens (DeepSeek CN)
  const cost = (inputTokens / 1_000_000) * inputPrice + (outputTokens / 1_000_000) * outputPrice
  if (cost < 0.01) return '< ¥0.01'
  return `¥${cost.toFixed(2)}`
}

function computePairCount(n: number): number {
  if (n < 2) return 0
  return (n * (n - 1)) / 2
}

/** Matches backend DEFAULT_PAIRS_PER_PACK_OVERRIDE (30). */
function estimatePackCount(pairCount: number): number {
  if (pairCount <= 0) return 0
  return Math.ceil(pairCount / 30)
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
  preset = null,
  activeTab = 'region',
  connPool = null,
  connPooledIds = new Set(),
}: Props) {
  // ── Modal state ───────────────────────────────────────────────────────────
  const [modalState, setModalState] = useState<ModalState>('prepare')
  const [wizardStep, setWizardStep] = useState<1 | 2 | 3 | 4>(1)
  const [internalLabels, setInternalLabels] = useState<Record<string, string>>({})
  const [dryRun, setDryRun] = useState(false)
  const [dryRunSamplePack, setDryRunSamplePack] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [addingMembers, setAddingMembers] = useState(false)
  const [showErrors, setShowErrors] = useState(false)
  const [localPoolId, setLocalPoolId] = useState<string | null>(null)

  // ── Prompt engineering ──────────────────────────────────────────────────────
  const [temperature, setTemperature] = useState(0.7)
  const [maxTokens, setMaxTokens] = useState(16384)
  const [candidatesPerPack, setCandidatesPerPack] = useState(25)
  const [shuffleRounds, setShuffleRounds] = useState(3)
  const [packConfig, setPackConfig] = useState<PackConfigPayload | null>(null)
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
    noFindingsPacks: 0,
    screenedLikelyCount: 0,
    connectionsFound: 0,
    parsedNoConnCount: 0,
    createdCount: 0,
    updatedCount: 0,
    mergedCount: 0,
    skippedDupCount: 0,
    noConnectionCount: 0,
    functionCount: 0,
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
    estimatedInputTokens: 0,
    estimatedOutputTokens: 0,
    actualPromptTokens: 0,
    actualCompletionTokens: 0,
    dryRunSamplePack: false,
  })

  // ── Runtime debug refs (must be before any early return) ──────────────────
  const lastPollRef = useRef('')
  const dataSourceRef = useRef('init')
  const startTimeRef = useRef(Date.now())
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const cancelledRef = useRef(false)
  const pollInFlightRef = useRef(false)
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
    if (skipInitialPoolSync || preset?.input_pool_type === 'connection_pool') {
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
          estimatedInputTokens: 0,
          estimatedOutputTokens: 0,
          actualPromptTokens: 0,
          actualCompletionTokens: 0,
        }))

        const fnResponse = await runSameGranularityFunctionExtraction({
          provider,
          model_name: modelName || undefined,
          candidate_ids: candidateIds,
          scope,
          dry_run: dryRun,
          dry_run_sample_pack: dryRun && dryRunSamplePack,
          create_mirror_records: !dryRun,
          create_triples: !dryRun,
          create_evidence: !dryRun,
          temperature: temperature !== 0.7 ? temperature : undefined,
          max_tokens: maxTokens !== 16384 ? maxTokens : undefined,
          prompt_template_key: primaryTemplateKey || undefined,
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

      if (isCircuitPackWorkflow(workflowType, preset)) {
        setModalState('progress')
        // Use ALL pool members for circuit extraction (not just selected subset)
        const allPoolIds = localMembers.map(m => m.candidate_id)
        const packSize = Math.min(allPoolIds.length, allPoolIds.length <= 30 ? allPoolIds.length : 25)
        const circuitResponse = await runCircuitExtraction({
          provider,
          model_name: modelName || undefined,
          candidate_ids: allPoolIds,
          pool_id: pool?.id ?? undefined,
          candidates_per_pack: packSize,
          shuffle_rounds: 3,
          pack_concurrency: 1,
          temperature: temperature !== 0.7 ? temperature : undefined,
          max_tokens: maxTokens !== 16384 ? maxTokens : undefined,
          dry_run: dryRun,
        })
        if (dryRun) { setModalState('result'); return }
        setProgress(prev => ({
          ...prev,
          workflowRunId: circuitResponse.run_id,
          workflowStatus: circuitResponse.status,
          progressPercent: 0,
          totalPacks: circuitResponse.estimated_packs,
        }))
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
        dry_run_sample_pack: dryRun && dryRunSamplePack,
        pack_concurrency: packConcurrency !== 1 ? packConcurrency : undefined,
        candidate_ids: candidateIds,
        resource_id: scope.resource_id,
        batch_id: scope.batch_id,
        source_atlas: scope.source_atlas,
        granularity_level: scope.granularity_level,
        granularity_family: scope.granularity_family,
        create_mirror_records: !dryRun,
        create_evidence: !dryRun,
        temperature: temperature !== 0.7 ? temperature : undefined,
        max_tokens: maxTokens !== 16384 ? maxTokens : undefined,
        prompt_template_key: primaryTemplateKey || undefined,
        prompt_overrides: editingPrompt && primaryTemplateKey
          ? { [primaryTemplateKey]: customUserPrompt }
          : undefined,
      }

      const response: CompositeWorkflowStartResponse = await startCompositeWorkflow(payload)

      const packCountFromResponse = ((response as any).pack_count as number | undefined)
        ?? (response.pair_count ? Math.ceil(response.pair_count / 30) : 0)
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
        noFindingsPacks: 0,
        screenedLikelyCount: 0,
        connectionsFound: 0,
        parsedNoConnCount: 0,
        createdCount: 0,
        updatedCount: 0,
        mergedCount: 0,
        skippedDupCount: 0,
        noConnectionCount: 0,
        functionCount: 0,
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
        estimatedInputTokens: 0,
        estimatedOutputTokens: 0,
        actualPromptTokens: 0,
        actualCompletionTokens: 0,
        dryRunSamplePack: dryRun && dryRunSamplePack,
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
  }, [selectedExtractionIds, selectedPackEstimate, displayMembers.length, pool, provider, modelName, dryRun, workflowType, temperature, maxTokens, primaryTemplateKey, editingPrompt, customUserPrompt, dryRunSamplePack, preset, localMembers, candidatesPerPack, shuffleRounds])

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
      if (isCircuitPackWorkflow(workflowType, preset)) {
        const resp = await cancelCircuitExtractionRun(wfId)
        cancelledRef.current = true
        if (pollingRef.current) clearInterval(pollingRef.current)
        setProgress(prev => ({
          ...prev,
          workflowStatus: resp.status,
          lastCancelResponse: JSON.stringify(resp),
        }))
        setCancelling(false)
        cancelInFlightRef.current = false
        setModalState('result')
        return
      }

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
      // Prevent overlapping poll requests from regressing counters
      if (pollInFlightRef.current) return
      pollInFlightRef.current = true

      try {
        if (isCircuitPackWorkflow(workflowType, preset)) {
          const cr = await getCircuitExtractionRun(progress.workflowRunId)
          const s = (cr.result_summary_json || {}) as Record<string, number>
          const u = (cr.usage_summary_json || {}) as Record<string, number>
          const processed = s.processed_packs ?? 0
          const total = s.total_packs ?? cr.pack_count ?? 1
          setProgress(prev => ({
            ...prev,
            workflowStatus: cr.status,
            progressPercent: total > 0 ? Math.round((processed / total) * 100) : 0,
            processedPacks: processed,
            totalPacks: total,
            successPacks: cr.succeeded_packs ?? 0,
            noConnectionPacks: cr.no_findings_packs ?? 0,
            failedPacks: cr.failed_packs ?? 0,
            modelCalls: processed,
            connectionsFound: cr.circuit_count ?? 0,
            functionCount: cr.step_count ?? 0,
            createdCount: cr.function_count ?? 0,
            actualPromptTokens: u.prompt_tokens ?? 0,
            actualCompletionTokens: u.completion_tokens ?? 0,
            estimatedRemainingSec: null,
            averagePackSec: null,
          }))
          if (['succeeded', 'partially_succeeded', 'failed', 'cancelled'].includes(cr.status)) {
            if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null }
            setModalState('result')
          }
          return
        }

        const detail: CompositeWorkflowRunRead = await getCompositeWorkflowRun(
          progress.workflowRunId,
        )

        // ── Resolve the best progress source ──────────────────────────────
        // result_summary (rs) first — committed flat dict from callback writes.
        // step.execution_summary LAST — NOT committed during execution (step_commit=False).
        const connStep = (detail.steps ?? []).find(s => s.step_key === 'extract_connections')
        const stepExec = (connStep?.execution_summary ?? {}) as Record<string, unknown>
        const stepPa = (stepExec.provider_audit ?? {}) as Record<string, unknown>
        const topPa = (detail.provider_audit ?? {}) as Record<string, unknown>
        const rs = (detail.result_summary ?? {}) as Record<string, unknown>
        const rsPa = (rs.provider_audit ?? {}) as Record<string, unknown>
        const terminal = isTerminalWorkflowStatus(detail.status)
        const sources = [rs, rsPa, topPa, stepExec, stepPa]

        // All counters — prefer result_summary; stepExec only as last resort
        let processedPacks = readProgressMetric(
          sources,
          'processed_pack_count',
        )
        const plannedPacks = readProgressMetric(
          sources,
          'pack_count',
          'planned_pack_count',
        )
        const totalPacks = plannedPacks ?? progress.totalPacks
        const successPacks = readProgressMetric(
          sources,
          'succeeded_pack_count',
        )
        const failedPacks = readProgressMetric(
          sources,
          'failed_pack_count',
        ) ?? 0
        const parsedProj = readProgressMetric(
          sources,
          'parsed_projection_count',
        )
        const parsedNoConn = readProgressMetric(
          sources,
          'parsed_no_connection_count',
        )
        const createdProj = readProgressMetric(
          sources,
          'created_projection_count',
        )
        const updatedProj = readProgressMetric(
          sources,
          'updated_projection_count',
        )
        const mergedProj = readProgressMetric(
          sources,
          'merged_projection_count',
        )
        const skippedDup = readProgressMetric(
          sources,
          'skipped_duplicate_count',
        )
        const noConn = readProgressMetric(
          sources,
          'no_connection_count',
        )
        const noConnectionPacks = readProgressMetric(
          sources,
          'no_connection_pack_count',
        ) ?? 0
        const noFindingsPacks = readProgressMetric(
          sources,
          'no_findings_pack_count',
        ) ?? 0
        const screenedLikely = readProgressMetric(
          sources,
          'screened_likely_connection_count',
        ) ?? 0
        const parsedFunc = readProgressMetric(
          sources,
          'parsed_function_count',
        ) ?? 0
        const providerCalls = readProgressMetric(
          sources,
          'provider_call_count',
        )
        const promptSent = readProgressMetric(
          sources,
          'prompt_sent_count',
        )
        const modelCalls = readProgressMetric(
          sources,
          'model_call_count',
          'planned_model_call_count',
        )

        if (processedPacks === null || (terminal && processedPacks === 0)) {
          const summaryPacks = countFinishedPacks(rs.pack_summaries ?? stepExec.pack_summaries)
          if (summaryPacks > 0) processedPacks = summaryPacks
        }
        processedPacks = processedPacks ?? 0

        const backendAvgSec = readProgressMetric(
          sources,
          'average_pack_sec',
        )
        const backendEstRem = readProgressMetric(
          sources,
          'estimated_remaining_sec',
        )
        const backendConcurrency = readProgressMetric(
          sources,
          'concurrency',
        )
        const estInput = readProgressMetric(sources, 'estimated_input_tokens') ?? 0
        const estOutput = readProgressMetric(sources, 'estimated_output_tokens') ?? 0
        // Read actual token usage from result_summary (available after completion)
        const actualPrompt = terminal ? (readProgressMetric(sources, 'prompt_tokens') ?? 0) : 0
        const actualCompletion = terminal ? (readProgressMetric(sources, 'completion_tokens') ?? 0) : 0

        const inFlightCount = readProgressMetric(
          sources,
          'in_flight_pack_count',
        )
        const packProgressPct = readProgressMetric(
          sources,
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
          ...prev,
          workflowRunId: detail.id,
          workflowStatus: resolvePolledWorkflowStatus(prev.workflowStatus, detail.status),
          estimatedInputTokens: estInput,
          estimatedOutputTokens: estOutput,
          actualPromptTokens: actualPrompt,
          actualCompletionTokens: actualCompletion,
          dryRunSamplePack: prev.dryRunSamplePack,
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
          noFindingsPacks: noFindingsPacks ?? 0,
          screenedLikelyCount: screenedLikely ?? 0,
          connectionsFound: parsedProj ?? 0,
          parsedNoConnCount: parsedNoConn ?? 0,
          createdCount: createdProj ?? 0,
          updatedCount: updatedProj ?? 0,
          mergedCount: mergedProj ?? 0,
          skippedDupCount: skippedDup ?? 0,
          noConnectionCount: noConn ?? 0,
          functionCount: parsedFunc,
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
      } finally {
        pollInFlightRef.current = false
      }
    }, 1000)

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [modalState, progress.workflowRunId])

  // ── Reset state helper (shared by close / background close) ──────────────
  const resetModalState = useCallback(() => {
    setModalState('prepare')
    setWizardStep(1)
    setLockedPanelHeight(520)
    setSearchTerm('')
    setSelectedMemberCandidateIds(new Set())
    setDryRun(false)
    setDryRunSamplePack(false)
    setTemperature(0.7)
    setMaxTokens(16384)
    setShowPromptPreview(false)
    setEditingPrompt(false)
    setCustomSystemPrompt('')
    setCustomUserPrompt('')
    setPromptTemplates([])
    setCancelling(false)
    setShowErrors(false)
    setLocalPoolId(null)
    setPendingMembers([])
    setPackConfig(null)
  }, [])

  // Close UI without canceling — for X button, "后台运行", wizard cancel/close, result close
  const handleClose = useCallback(() => {
    if (pollingRef.current) clearInterval(pollingRef.current)
    resetModalState()
    onClose()
  }, [onClose, resetModalState])

  // Close UI AND cancel the workflow — for "取消任务" button during progress
  const handleCancelAndClose = useCallback(async () => {
    // First cancel the backend workflow via proper API client
    const wfId = progress.workflowRunId
    if (wfId && modalState === 'progress') {
      cancelledRef.current = true
      if (pollingRef.current) clearInterval(pollingRef.current)
      try {
        if (isCircuitPackWorkflow(workflowType, preset)) {
          await cancelCircuitExtractionRun(wfId)
        } else {
          await cancelCompositeWorkflow(wfId, {
            cleanup: true,
            reason: 'user_closed_modal',
          })
        }
      } catch (err) { console.error('[PoolExtractionModal] Cancel API call failed:', err) }
    }
    resetModalState()
    onClose()
  }, [onClose, resetModalState, progress.workflowRunId, modalState, workflowType, preset])

  // ── LLM config state (Step 2) — MUST be before early return ─────────────
  const [llmProvider, setLlmProvider] = useState('deepseek')
  const [llmModel, setLlmModel] = useState('deepseek-chat')
  const [packConcurrency, setPackConcurrency] = useState(1)
  const [skipExisting, setSkipExisting] = useState(false)
  const [budgetCny, setBudgetCny] = useState('')
  const [runInstructionOverlay, setRunInstructionOverlay] = useState('')

  // ── Dry run state ─────────────────────────────────────────────────────────
  const [dryRunResult, setDryRunResult] = useState<any>(null)
  const [dryRunLoading, setDryRunLoading] = useState(false)
  const [dryRunError, setDryRunError] = useState<string | null>(null)

  const LLM_MODELS: Record<string, Array<{ value: string; label: string }>> = {
    deepseek: [
      { value: 'deepseek-chat', label: 'deepseek-chat (V3)' },
      { value: 'deepseek-v4-pro', label: 'deepseek-v4-pro (V4 Pro)' },
      { value: 'deepseek-reasoner', label: 'deepseek-reasoner (R1)' },
    ],
    kimi: [
      { value: 'moonshot-v1-auto', label: 'moonshot-v1-auto' },
      { value: 'moonshot-v1-8k', label: 'moonshot-v1-8k' },
      { value: 'moonshot-v1-32k', label: 'moonshot-v1-32k' },
    ],
  }

  const handleProviderChange = (p: string) => {
    setLlmProvider(p)
    setLlmModel(p === 'kimi' ? 'moonshot-v1-auto' : 'deepseek-chat')
  }

  useEffect(() => {
    if (wizardStep === 2 && packConfig) {
      console.log('[llm-config][enter]', {
        preset_id: packConfig.preset_id,
        candidate_count: packConfig.candidate_ids.length,
        estimated_pack_count: packConfig.estimated_pack_count,
        candidates_per_pack: packConfig.candidates_per_pack,
        shuffle_rounds: packConfig.shuffle_rounds,
      })
    }
  }, [wizardStep, packConfig])

  if (!open) return null

  // ── Render: step 1 (pool selection) ──────────────────────────────────────
  const renderStep1 = () => (
    <>
      {/* Header */}
      <div className="modal-header">
        <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: '#1a1a2e' }}>
          ⚡ {preset ? preset.label : (TYPE_LABELS[workflowType] || workflowType || '全量提取')}
        </h3>
        <button className="btn-close" onClick={handleClose}>x</button>
      </div>

      <div style={{ padding: '0 20px', flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Preset summary */}
        {preset && (
          <div className="modal-section" style={{
            background: 'linear-gradient(135deg, #eef2ff, #f5f3ff)',
            border: '1px solid #c7d2fe', borderRadius: 8, padding: '12px 14px', marginBottom: 12,
          }}>
            <p className="modal-section-title" style={{ marginTop: 0 }}>本次提取模式</p>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 16px', fontSize: 12 }}>
              <span style={{ color: '#888' }}>提取模式</span><span style={{ fontWeight: 600 }}>{preset.label}</span>
              <span style={{ color: '#888' }}>输入类型</span><span>{preset.input_pool_type === 'region_pool' ? '脑区池' : '连接池'}</span>
              <span style={{ color: '#888' }}>提取目标</span><code style={{ fontSize: 11 }}>{preset.target}</code>
              <span style={{ color: '#888' }}>内置提示词</span><code style={{ fontSize: 11 }}>{preset.prompt_template_key}</code>
              <span style={{ color: '#888' }}>输出表</span><span style={{ fontSize: 11 }}>{preset.output_tables.join(', ')}</span>
              <span style={{ color: '#888' }}>分包策略</span><span style={{ fontSize: 11 }}>{preset.pack_strategy || '—'}</span>
              <span style={{ color: '#888' }}>后端接口</span><code style={{ fontSize: 11 }}>{preset.endpoint_type}</code>
            </div>
          </div>
        )}

        {/* Scope info */}
        <div className="modal-section">
          <p className="modal-section-title">提取范围</p>
          {preset?.input_pool_type === 'connection_pool' ? (
            <>
              <div className="modal-section-row">
                <span className="label">Atlas</span>
                <span className="value">{connPool?.scope_atlas || '—'}</span>
              </div>
              <div className="modal-section-row">
                <span className="label">Granularity</span>
                <span className="value">{connPool?.scope_granularity || '—'}</span>
              </div>
              <div className="modal-section-row">
                <span className="label">连接池</span>
                <span className="value" style={{ fontWeight: 600, color: '#059669' }}>
                  {connPooledIds?.size ?? 0} 条连接
                </span>
              </div>
              <div className="modal-section-row">
                <span className="label">本次已选</span>
                <span className="value">{selectedExtractionIds.length} 条</span>
              </div>
            </>
          ) : pool ? (
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

        {/* Pack plan section */}
        {(() => {
          const poolCandidateIds = getRegionPoolMemberIds({
            localMembers: pool ? localMembers : undefined,
            pool,
            candidateIds: selectedCandidateIds,
          })
          const plan = buildPackPlanPreview({
            preset: preset as TaskPreset | null,
            candidateCount: preset?.input_pool_type === 'connection_pool' ? (connPooledIds as Set<string>)?.size ?? 0 : poolCandidateIds.length,
            candidatesPerPack,
            shuffleRounds,
          })
          const showShuffleRounds = preset?.pack_strategy === 'multi_round_region_shuffle_for_circuit'
          const showPackPlan = pool && preset && preset.input_pool_type === 'region_pool'

          return showPackPlan ? (
            <div className="modal-section" style={{
              background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 12,
            }}>
              <p className="modal-section-title" style={{ marginTop: 0 }}>分包计划</p>
              <div className="modal-section-row">
                <span className="label">脑区数</span>
                <span className="value"><strong>{poolCandidateIds.length}</strong></span>
              </div>
              <div className="modal-section-row" style={{ alignItems: 'center' }}>
                <span className="label">每包脑区数</span>
                <input type="number" className="llm-input" style={{ width: 80, textAlign: 'center' }}
                  min={5} max={50} value={candidatesPerPack}
                  onChange={e => setCandidatesPerPack(Math.max(5, Math.min(50, Number(e.target.value) || 5)))}
                />
                <span style={{ fontSize: 11, color: '#888', marginLeft: 8 }}>建议 20–30</span>
              </div>
              {showShuffleRounds && (
                <div className="modal-section-row" style={{ alignItems: 'center' }}>
                  <span className="label">Shuffle 轮数</span>
                  <input type="number" className="llm-input" style={{ width: 80, textAlign: 'center' }}
                    min={1} max={10} value={shuffleRounds}
                    onChange={e => setShuffleRounds(Math.max(1, Math.min(10, Number(e.target.value) || 1)))}
                  />
                  <span style={{ fontSize: 11, color: '#888', marginLeft: 8 }}>范围 1–10</span>
                </div>
              )}
              {showShuffleRounds && (
                <div className="modal-section-row">
                  <span className="label">每轮包数</span>
                  <span className="value">{Math.ceil(poolCandidateIds.length / candidatesPerPack)}</span>
                </div>
              )}
              <div className="modal-section-row">
                <span className="label">总包数</span>
                <span className="value" style={{ fontWeight: 700, color: '#2563eb', fontSize: 16 }}>{plan.pack_count}</span>
              </div>
              <div className="modal-section-row">
                <span className="label">包大小</span>
                <span className="value" style={{ fontSize: 11 }}>
                  {plan.pack_sizes.slice(0, 8).join(' + ')}{plan.pack_sizes.length > 8 ? ' …' : ''}
                  {showShuffleRounds ? ` × ${shuffleRounds} 轮` : ''}
                </span>
              </div>
              {plan.warnings.map((w, i) => (
                <div key={i} style={{ marginTop: 6, padding: '4px 8px', background: '#fffbe6', borderRadius: 4, fontSize: 11, color: '#8c6d00' }}>⚠️ {w}</div>
              ))}
            </div>
          ) : preset?.input_pool_type === 'connection_pool' && (
            <div className="modal-section" style={{
              background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 12,
            }}>
              <p className="modal-section-title" style={{ marginTop: 0 }}>分包计划</p>
              <div className="modal-section-row">
                <span className="label">连接数</span>
                <span className="value"><strong>{(connPooledIds as Set<string>)?.size ?? 0}</strong></span>
              </div>
              <div className="modal-section-row" style={{ alignItems: 'center' }}>
                <span className="label">每包连接数</span>
                <input type="number" className="llm-input" style={{ width: 80, textAlign: 'center' }}
                  min={5} max={50} value={candidatesPerPack}
                  onChange={e => setCandidatesPerPack(Math.max(5, Math.min(50, Number(e.target.value) || 5)))}
                />
                <span style={{ fontSize: 11, color: '#888', marginLeft: 8 }}>建议 20–30</span>
              </div>
              <div className="modal-section-row">
                <span className="label">预估包数</span>
                <span className="value" style={{ fontWeight: 700, color: '#2563eb', fontSize: 16 }}>{plan.pack_count}</span>
              </div>
              <div className="modal-section-row">
                <span className="label">分包策略</span>
                <span className="value" style={{ fontSize: 12 }}>按连接图连通性分组 (graph-aware)</span>
              </div>
              {plan.warnings.map((w, i) => (
                <div key={i} style={{ marginTop: 6, padding: '4px 8px', background: '#fffbe6', borderRadius: 4, fontSize: 11, color: '#8c6d00' }}>⚠️ {w}</div>
              ))}
            </div>
          )
        })()}

        {/* Connection pool mode: simplified info */}
        {preset?.input_pool_type === 'connection_pool' && (
          <div className="modal-section" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, justifyContent: 'center', alignItems: 'center' }}>
            <p style={{ color: '#888', fontSize: 13, textAlign: 'center' }}>
              🔗 连接池模式：连接在上方外部表格中管理<br/>
              <span style={{ fontSize: 11 }}>勾选的 {connPooledIds?.size ?? 0} 条连接将用于回路提取</span>
            </p>
          </div>
        )}

        {/* Region pool mode: member table */}
        {preset?.input_pool_type !== 'connection_pool' && (
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
      )}

      </div>

      {/* Footer */}
      <div className="modal-footer">
        <button className="llm-btn" onClick={handleClose}>取消</button>
        <button
          className="llm-btn llm-btn-primary"
          onClick={() => {
            const isConnPool = preset?.input_pool_type === 'connection_pool'
            const poolIds = isConnPool
              ? Array.from(connPooledIds ?? new Set())
              : getRegionPoolMemberIds({ localMembers, pool, candidateIds: selectedCandidateIds })
            if (poolIds.length < 2) return
            const plan = buildPackPlanPreview({
              preset: preset as TaskPreset | null,
              candidateCount: poolIds.length,
              candidatesPerPack,
              shuffleRounds,
            })
            const cfg = buildPackConfigPayload({
              preset: preset as TaskPreset | null,
              poolId: pool?.id ?? connPool?.id,
              candidateIds: poolIds,
              candidatesPerPack,
              shuffleRounds,
              packPlan: plan,
            })
            setPackConfig(cfg)
            logPackPlanNext(cfg)
            setWizardStep(2)
          }}
          disabled={(() => {
            const isConnPool = preset?.input_pool_type === 'connection_pool'
            const poolIds = isConnPool
              ? Array.from(connPooledIds ?? new Set())
              : getRegionPoolMemberIds({ localMembers, pool, candidateIds: selectedCandidateIds })
            return isConnPool
              ? poolIds.length < 2 || addingMembers
              : !pool || poolIds.length < 2 || addingMembers || !poolMatchesExternal
          })()}
        >
          下一步
        </button>
      </div>
    </>
  )

  // ── Render: step 2 (LLM config) ────────────────────────────────────────────
  const renderStep2 = () => {
    const modelOptions = LLM_MODELS[llmProvider] || LLM_MODELS.deepseek
    const cfg = packConfig
    return (
    <>
      <div className="modal-header">
        <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: '#1a1a2e' }}>
          ⚡ LLM 基础配置
        </h3>
        <button className="btn-close" onClick={handleClose}>x</button>
      </div>

      <div style={{ padding: '0 20px', flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Model config */}
        <div className="modal-section">
          <p className="modal-section-title">模型配置</p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px 16px' }}>
            <label style={{ fontSize: 13 }}>
              <span className="label" style={{ display: 'block', marginBottom: 4 }}>Provider</span>
              <select className="llm-select" value={llmProvider}
                onChange={e => handleProviderChange(e.target.value)} style={{ width: '100%' }}>
                <option value="deepseek">deepseek</option>
                <option value="kimi">kimi</option>
              </select>
            </label>
            <label style={{ fontSize: 13 }}>
              <span className="label" style={{ display: 'block', marginBottom: 4 }}>Model</span>
              <select className="llm-select" value={llmModel}
                onChange={e => setLlmModel(e.target.value)} style={{ width: '100%' }}>
                {modelOptions.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </label>
          </div>
        </div>

        {/* Advanced params */}
        <div className="modal-section">
          <p className="modal-section-title">高级参数</p>

          <div style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
              <span className="label">Temperature</span>
              <span style={{ color: '#2563eb', fontWeight: 600 }}>{temperature.toFixed(1)}</span>
            </div>
            <input type="range" min={0} max={2} step={0.1} value={temperature}
              onChange={e => setTemperature(parseFloat(e.target.value))} style={{ width: '100%' }} />
          </div>

          <div style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
              <span className="label">Max Tokens</span>
              <span style={{ color: '#2563eb', fontWeight: 600 }}>{maxTokens.toLocaleString()}</span>
            </div>
            <input type="range" min={256} max={65536} step={1024} value={maxTokens}
              onChange={e => setMaxTokens(parseInt(e.target.value))} style={{ width: '100%' }} />
          </div>

          <div className="modal-section-row" style={{ alignItems: 'center' }}>
            <span className="label">并发数</span>
            <input type="number" className="llm-input" style={{ width: 70, textAlign: 'center' }}
              min={1} max={8} value={packConcurrency}
              onChange={e => setPackConcurrency(Math.max(1, Math.min(8, Number(e.target.value) || 1)))}
            />
            <span style={{ fontSize: 11, color: '#888', marginLeft: 8 }}>建议 1，避免 session 并发风险</span>
          </div>

          <div style={{ marginTop: 8 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 13 }}>
              <input type="checkbox" checked={skipExisting} onChange={e => setSkipExisting(e.target.checked)} />
              skip_existing（跳过已有同名回路）
            </label>
          </div>

          <div className="modal-section-row" style={{ alignItems: 'center', marginTop: 8 }}>
            <span className="label">预算上限 (¥)</span>
            <input type="number" className="llm-input" style={{ width: 100, textAlign: 'center' }}
              placeholder="可选" value={budgetCny}
              onChange={e => setBudgetCny(e.target.value)}
            />
            <span style={{ fontSize: 11, color: '#888', marginLeft: 8 }}>当前仅保存，不做拦截</span>
          </div>
        </div>

        {/* Extraction mode */}
        <div className="modal-section">
          <p className="modal-section-title">提取模式</p>
          <div style={{ display: 'flex', gap: 16 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 14 }}>
              <input type="radio" name="extractMode" checked={!dryRun} onChange={() => setDryRun(false)} /> 正式提取
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 14 }}>
              <input type="radio" name="extractMode" checked={dryRun} onChange={() => setDryRun(true)} /> Dry Run 预览
            </label>
          </div>
          {dryRun && (
            <div style={{ marginTop: 8, padding: '8px 12px', background: '#f0f7ff', borderRadius: 6, fontSize: 12, color: '#555' }}>
              <div>📊 构建所有 packs，估算 token 用量和费用</div>
              <div>🚫 不调用 LLM，不写入数据库</div>
            </div>
          )}
        </div>

        {/* Run config summary */}
        {cfg && (
          <div className="modal-section" style={{
            background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8, padding: '12px 14px',
          }}>
            <p className="modal-section-title" style={{ marginTop: 0 }}>当前运行配置摘要</p>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 16px', fontSize: 12 }}>
              <span style={{ color: '#888' }}>提取模式</span><span style={{ fontWeight: 600 }}>{preset?.label}</span>
              <span style={{ color: '#888' }}>后端接口</span><code style={{ fontSize: 11 }}>{preset?.endpoint_type}</code>
              <span style={{ color: '#888' }}>脑区数</span><span style={{ fontWeight: 600 }}>{cfg.candidate_ids.length}</span>
              <span style={{ color: '#888' }}>预计包数</span><span style={{ fontWeight: 600, color: '#2563eb' }}>{cfg.estimated_pack_count}</span>
              <span style={{ color: '#888' }}>每包脑区数</span><span>{cfg.candidates_per_pack}</span>
              <span style={{ color: '#888' }}>Shuffle 轮数</span><span>{cfg.shuffle_rounds}</span>
              <span style={{ color: '#888' }}>Provider</span><span>{llmProvider}</span>
              <span style={{ color: '#888' }}>Model</span><span>{llmModel}</span>
              <span style={{ color: '#888' }}>Temperature</span><span>{temperature.toFixed(1)}</span>
              <span style={{ color: '#888' }}>Max Tokens</span><span>{maxTokens.toLocaleString()}</span>
              <span style={{ color: '#888' }}>并发</span><span>{packConcurrency}</span>
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="modal-footer">
        <button className="llm-btn" onClick={() => setWizardStep(1)}>上一步</button>
        <button className="llm-btn" onClick={handleClose}>取消</button>
        <button
          className="llm-btn llm-btn-primary"
          onClick={() => {
            if (!cfg) return
            console.log('[llm-config][next]', {
              preset_id: cfg.preset_id,
              pool_type: cfg.pool_type,
              pool_id: cfg.pool_id,
              candidate_count: cfg.candidate_ids.length,
              estimated_pack_count: cfg.estimated_pack_count,
              provider: llmProvider,
              model_name: llmModel,
              temperature,
              max_tokens: maxTokens,
              pack_concurrency: packConcurrency,
              candidates_per_pack: cfg.candidates_per_pack,
              shuffle_rounds: cfg.shuffle_rounds,
            })
            console.log('[llm-prompt-config][enter]', {
              preset_id: preset?.preset_id,
              extraction_target: preset?.target,
              prompt_template_key: preset?.prompt_template_key,
              output_tables: preset?.output_tables,
              candidate_count: cfg.candidate_ids.length,
              estimated_pack_count: cfg.estimated_pack_count,
              provider: llmProvider,
              model_name: llmModel,
            })
            setWizardStep(3)
          }}
        >
          下一步
        </button>
      </div>
    </>
    )
  }

  // ── Render: step 3 (task target + prompt config) ──────────────────────────
  const renderStep3 = () => {
    const cfg = packConfig
    const targetLabel = preset?.target ?? '—'
    const templateKey = preset?.prompt_template_key ?? '—'
    const outputTables = preset?.output_tables ?? []
    return (
    <>
      <div className="modal-header">
        <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: '#1a1a2e' }}>
          任务目标与提示词配置
        </h3>
        <button className="btn-close" onClick={handleClose}>x</button>
      </div>

      <div style={{ padding: '0 20px', flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* 1. Extraction mode summary */}
        <div className="modal-section" style={{ background: '#eef2ff', border: '1px solid #c7d2fe', borderRadius: 8, padding: '12px 14px' }}>
          <p className="modal-section-title" style={{ marginTop: 0 }}>提取模式</p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 16px', fontSize: 12 }}>
            <span style={{ color: '#888' }}>提取模式</span><span style={{ fontWeight: 600 }}>{preset?.label}</span>
            <span style={{ color: '#888' }}>输入类型</span><span>{preset?.input_pool_type === 'region_pool' ? '脑区池' : '连接池'}</span>
            <span style={{ color: '#888' }}>提取目标</span><code style={{ fontSize: 11 }}>{targetLabel}</code>
            <span style={{ color: '#888' }}>后端接口</span><code style={{ fontSize: 11 }}>{preset?.endpoint_type}</code>
            <span style={{ color: '#888' }}>分包策略</span><span style={{ fontSize: 11 }}>{preset?.pack_strategy || '—'}</span>
          </div>
        </div>

        {/* 2. Built-in prompt binding */}
        <div className="modal-section" style={{ background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginTop: 12 }}>
          <p className="modal-section-title" style={{ marginTop: 0 }}>内置 Prompt 绑定</p>
          <div className="modal-section-row">
            <span className="label">模板 Key</span>
            <code style={{ fontSize: 12, background: '#f0f2f5', padding: '2px 6px', borderRadius: 3 }}>{templateKey}</code>
          </div>
          <div className="modal-section-row">
            <span className="label">来源</span>
            <span>系统内置</span>
          </div>
          <div className="modal-section-row">
            <span className="label">允许编辑</span>
            <span style={{ color: '#999' }}>否（由 Task Preset 自动绑定）</span>
          </div>
        </div>

        {/* 3. Output tables */}
        <div className="modal-section" style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8, padding: '12px 14px', marginTop: 12 }}>
          <p className="modal-section-title" style={{ marginTop: 0 }}>输出表</p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {outputTables.map((t: string) => (
              <code key={t} style={{ fontSize: 11, background: '#d9f99d', padding: '2px 8px', borderRadius: 4, color: '#166534' }}>{t}</code>
            ))}
            {outputTables.length === 0 && <span style={{ color: '#888', fontSize: 12 }}>—</span>}
          </div>
        </div>

        {/* 4. Prompt template config (restored) */}
        <div className="modal-section" style={{ marginTop: 12 }}>
          <p className="modal-section-title">提示词模板</p>
          {primaryTemplateKey || primaryTemplate ? (
            <div style={{ fontSize: 13, color: '#555' }}>
              <code style={{ fontSize: 12, background: '#f0f2f5', padding: '2px 6px', borderRadius: 3 }}>{primaryTemplateKey || '—'}</code>
              {primaryTemplate && (
                <span style={{ marginLeft: 8, color: '#888' }}>
                  {primaryTemplate.display_name ?? primaryTemplate.title}
                </span>
              )}
            </div>
          ) : (
            <div style={{ fontSize: 12, color: '#999', fontStyle: 'italic' }}>加载中或模板不可用...</div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
            <button type="button" className="llm-btn"
              onClick={() => {
                if (editingPrompt && primaryTemplate) {
                  setCustomSystemPrompt(primaryTemplate.system_prompt)
                  setCustomUserPrompt(primaryTemplate.template)
                }
                setEditingPrompt(!editingPrompt)
              }}
            >
              {editingPrompt ? '恢复默认' : '编辑提示词'}
            </button>
          </div>

          {editingPrompt && (
            <>
              <div className="modal-section" style={{ marginTop: 8 }}>
                <p className="modal-section-title">System Prompt</p>
                <textarea style={{
                  width: '100%', minHeight: 80, fontSize: 12, fontFamily: 'monospace',
                  lineHeight: 1.5, border: '1px solid #d0d7e2', borderRadius: 4, padding: '8px 10px',
                  resize: 'vertical', background: '#fff',
                }} value={customSystemPrompt} onChange={e => setCustomSystemPrompt(e.target.value)} />
              </div>
              <div className="modal-section" style={{ marginTop: 8 }}>
                <p className="modal-section-title">User Prompt</p>
                <textarea style={{
                  width: '100%', minHeight: 100, fontSize: 12, fontFamily: 'monospace',
                  lineHeight: 1.5, border: '1px solid #d0d7e2', borderRadius: 4, padding: '8px 10px',
                  resize: 'vertical', background: '#fff',
                }} value={customUserPrompt} onChange={e => setCustomUserPrompt(e.target.value)} />
              </div>
              <div style={{ padding: '8px 12px', marginTop: 8, background: '#fff7e6', borderRadius: 6, fontSize: 12, color: '#d48806' }}>
                ⚠ 输出 JSON schema 由后端固定，修改 prompt 时请保留输出格式要求。
              </div>
            </>
          )}
        </div>

        {/* 5. Run instruction overlay (new addition) */}
        <div className="modal-section" style={{ marginTop: 12 }}>
          <p className="modal-section-title">本次提取补充要求</p>
          <p style={{ fontSize: 11, color: '#888', marginBottom: 6 }}>
            该说明只作为本次任务的附加要求，系统仍使用内置/配置的提示词模板。
          </p>
          <textarea
            style={{
              width: '100%', minHeight: 60, fontSize: 12, lineHeight: 1.5,
              border: '1px solid #d0d7e2', borderRadius: 4, padding: '8px 10px', resize: 'vertical',
            }}
            placeholder="例如：本次重点提取 AAL3 macro 脑区之间可能形成的认知控制相关回路，要求输出回路名称、步骤顺序、涉及脑区和功能说明。"
            value={runInstructionOverlay}
            onChange={e => setRunInstructionOverlay(e.target.value)}
          />
        </div>

        {/* Config summary */}
        {cfg && (
          <div className="modal-section" style={{
            background: '#f8fafb', border: '1px solid #e2e8f0', borderRadius: 8, padding: '12px 14px', marginTop: 12,
          }}>
            <p className="modal-section-title" style={{ marginTop: 0 }}>完整配置摘要</p>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 16px', fontSize: 12 }}>
              <span style={{ color: '#888' }}>脑区数</span><span style={{ fontWeight: 600 }}>{cfg.candidate_ids.length}</span>
              <span style={{ color: '#888' }}>预计包数</span><span style={{ fontWeight: 600, color: '#2563eb' }}>{cfg.estimated_pack_count}</span>
              <span style={{ color: '#888' }}>每包脑区数</span><span>{cfg.candidates_per_pack}</span>
              <span style={{ color: '#888' }}>Shuffle 轮数</span><span>{cfg.shuffle_rounds}</span>
              <span style={{ color: '#888' }}>Provider</span><span>{llmProvider}</span>
              <span style={{ color: '#888' }}>Model</span><span>{llmModel}</span>
              <span style={{ color: '#888' }}>Temperature</span><span>{temperature.toFixed(1)}</span>
              <span style={{ color: '#888' }}>Max Tokens</span><span>{maxTokens.toLocaleString()}</span>
              <span style={{ color: '#888' }}>提取目标</span><code style={{ fontSize: 11 }}>{targetLabel}</code>
              <span style={{ color: '#888' }}>内置提示词</span><code style={{ fontSize: 11 }}>{templateKey}</code>
              <span style={{ color: '#888' }}>输出表</span><span style={{ fontSize: 11 }}>{outputTables.join(', ') || '—'}</span>
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="modal-footer">
        <button className="llm-btn" onClick={() => setWizardStep(2)}>上一步</button>
        <button className="llm-btn" onClick={handleClose}>取消</button>
        <button
          className="llm-btn llm-btn-primary"
          onClick={() => {
            console.log('[llm-prompt-config][next]', {
              preset_id: preset?.preset_id,
              extraction_target: preset?.target,
              prompt_template_key: templateKey,
              output_tables: outputTables,
              run_instruction_overlay_length: runInstructionOverlay.length,
              candidate_count: cfg?.candidate_ids.length ?? 0,
              estimated_pack_count: cfg?.estimated_pack_count ?? 0,
              provider: llmProvider,
              model_name: llmModel,
              temperature,
              max_tokens: maxTokens,
            })
            setWizardStep(4)
          }}
        >
          下一步
        </button>
      </div>
    </>
    )
  }

  const renderStep4 = () => {
    const cfg = packConfig
    if (!cfg) return null

    const handleDryRun = async () => {
      if (!preset || (preset.endpoint_type !== 'circuit_extraction' && preset.endpoint_type !== 'composite_workflow')) {
        setDryRunError('当前 preset 暂不支持 Dry Run')
        return
      }
      setDryRunLoading(true)
      setDryRunError(null)
      setDryRunResult(null)

      const isConnPool = preset?.input_pool_type === 'connection_pool'
      const body: any = {
        provider: llmProvider,
        model_name: llmModel || undefined,
        pool_id: cfg.pool_id || undefined,
        candidates_per_pack: cfg.candidates_per_pack,
        shuffle_rounds: cfg.shuffle_rounds,
        temperature,
        max_tokens: maxTokens,
        pack_concurrency: packConcurrency,
        skip_existing: skipExisting,
        dry_run: true,
        preset_id: preset.preset_id,
        extraction_target: preset.target,
        prompt_template_key: preset.prompt_template_key,
        output_tables: preset.output_tables,
        run_instruction_overlay: runInstructionOverlay || undefined,
      }
      if (isConnPool) {
        body.connection_ids = cfg.candidate_ids
      } else {
        body.candidate_ids = cfg.candidate_ids
      }

      console.log('[llm-run-config][dry-run-request]', {
        preset_id: preset.preset_id,
        endpoint_type: preset.endpoint_type,
        input_count: cfg.candidate_ids.length,
        input_type: isConnPool ? 'connections' : 'regions',
        candidates_per_pack: cfg.candidates_per_pack,
        shuffle_rounds: cfg.shuffle_rounds,
        estimated_pack_count: cfg.estimated_pack_count,
        provider: llmProvider,
        model_name: llmModel,
        temperature,
        max_tokens: maxTokens,
        pack_concurrency: packConcurrency,
        prompt_template_key: preset.prompt_template_key,
        output_tables: preset.output_tables,
        run_instruction_overlay_length: runInstructionOverlay.length,
      })

      try {
        const { runCircuitExtraction } = await import('../../../api/endpoints')
        const resp = await runCircuitExtraction(body)
        const match = cfg.estimated_pack_count === resp.estimated_packs
        console.log('[llm-run-config][dry-run-response]', {
          run_id: (resp as any).run_id,
          candidate_count: (resp as any).candidate_count,
          frontend_estimated_pack_count: cfg.estimated_pack_count,
          backend_estimated_packs: resp.estimated_packs,
          estimated_llm_calls: resp.estimated_llm_calls,
          estimated_input_tokens: resp.estimated_input_tokens,
          estimated_output_tokens: resp.estimated_output_tokens,
          estimated_cost_cny: resp.estimated_cost_cny,
          pack_count_matched: match,
        })
        setDryRunResult({ ...resp, pack_count_matched: match })
      } catch (e: any) {
        setDryRunError(e.message || String(e))
      } finally {
        setDryRunLoading(false)
      }
    }

    const result = dryRunResult
    const packMatch = result?.pack_count_matched ?? true

    return (
    <>
      <div className="modal-header">
        <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: '#1a1a2e' }}>
          运行前确认
        </h3>
        <button className="btn-close" onClick={handleClose}>x</button>
      </div>

      <div style={{ padding: '0 20px', flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
        {/* Config summary cards */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          {/* Task info */}
          <div className="modal-section" style={{ background: '#f9fafb', borderRadius: 8, padding: 10, border: '1px solid #e5e7eb' }}>
            <p style={{ fontWeight: 600, fontSize: 13, margin: '0 0 6px' }}>任务信息</p>
            <div style={{ fontSize: 11, lineHeight: 1.8 }}>
              <div><span style={{ color: '#888' }}>preset:</span> {preset?.preset_id}</div>
              <div><span style={{ color: '#888' }}>label:</span> {preset?.label}</div>
              <div><span style={{ color: '#888' }}>endpoint:</span> <code>{preset?.endpoint_type}</code></div>
              <div><span style={{ color: '#888' }}>target:</span> {preset?.target}</div>
              <div><span style={{ color: '#888' }}>prompt:</span> <code style={{ fontSize: 10 }}>{preset?.prompt_template_key}</code></div>
              <div><span style={{ color: '#888' }}>output:</span> {(preset?.output_tables ?? []).join(', ')}</div>
            </div>
          </div>

          {/* Input pool */}
          <div className="modal-section" style={{ background: '#f9fafb', borderRadius: 8, padding: 10, border: '1px solid #e5e7eb' }}>
            <p style={{ fontWeight: 600, fontSize: 13, margin: '0 0 6px' }}>输入池</p>
            <div style={{ fontSize: 11, lineHeight: 1.8 }}>
              <div><span style={{ color: '#888' }}>pool_type:</span> {cfg.pool_type}</div>
              <div><span style={{ color: '#888' }}>pool_id:</span> <code style={{ fontSize: 10 }}>{cfg.pool_id?.slice(0, 12)}…</code></div>
              <div><span style={{ color: '#888' }}>{preset?.input_pool_type === 'connection_pool' ? '连接数' : '脑区数'}:</span> <strong>{cfg.candidate_ids.length}</strong></div>
            </div>
          </div>

          {/* Pack plan */}
          <div className="modal-section" style={{ background: '#f9fafb', borderRadius: 8, padding: 10, border: '1px solid #e5e7eb' }}>
            <p style={{ fontWeight: 600, fontSize: 13, margin: '0 0 6px' }}>分包计划</p>
            <div style={{ fontSize: 11, lineHeight: 1.8 }}>
              <div><span style={{ color: '#888' }}>strategy:</span> {cfg.pack_strategy}</div>
              {preset?.input_pool_type !== 'connection_pool' && (
                <div><span style={{ color: '#888' }}>每包:</span> {cfg.candidates_per_pack} | <span style={{ color: '#888' }}>轮数:</span> {cfg.shuffle_rounds}</div>
              )}
              <div><span style={{ color: '#888' }}>预计包数:</span> <strong style={{ color: '#2563eb', fontSize: 14 }}>{cfg.estimated_pack_count}</strong></div>
            </div>
          </div>

          {/* LLM config */}
          <div className="modal-section" style={{ background: '#f9fafb', borderRadius: 8, padding: 10, border: '1px solid #e5e7eb' }}>
            <p style={{ fontWeight: 600, fontSize: 13, margin: '0 0 6px' }}>LLM 配置</p>
            <div style={{ fontSize: 11, lineHeight: 1.8 }}>
              <div><span style={{ color: '#888' }}>provider:</span> {llmProvider}</div>
              <div><span style={{ color: '#888' }}>model:</span> {llmModel}</div>
              <div><span style={{ color: '#888' }}>temperature:</span> {temperature.toFixed(1)}</div>
              <div><span style={{ color: '#888' }}>max_tokens:</span> {maxTokens.toLocaleString()}</div>
              <div><span style={{ color: '#888' }}>concurrency:</span> {packConcurrency} | <span style={{ color: '#888' }}>skip:</span> {String(skipExisting)}</div>
            </div>
          </div>
        </div>

        {/* Prompt overlay */}
        {runInstructionOverlay && (
          <div className="modal-section" style={{ background: '#fffbe6', borderRadius: 8, padding: 10, marginTop: 10, border: '1px solid #ffe58f' }}>
            <p style={{ fontWeight: 600, fontSize: 13, margin: '0 0 4px' }}>补充要求</p>
            <p style={{ fontSize: 12, color: '#555', margin: 0, whiteSpace: 'pre-wrap' }}>{runInstructionOverlay}</p>
          </div>
        )}

        {/* Dry Run result */}
        {dryRunError && (
          <div style={{ marginTop: 12, padding: 10, background: '#fff2f0', borderRadius: 6, border: '1px solid #ffccc7', fontSize: 13, color: '#cf1322' }}>
            Dry Run 失败: {dryRunError}
          </div>
        )}

        {result && (
          <div className="modal-section" style={{
            marginTop: 12, padding: 14, borderRadius: 8,
            background: !packMatch ? '#fff2f0' : '#f0fdf4',
            border: !packMatch ? '2px solid #ff4d4f' : '1px solid #bbf7d0',
          }}>
            <p className="modal-section-title" style={{ marginTop: 0 }}>
              {!packMatch ? '⚠️ 包数不一致！' : '✅ Dry Run 通过'}
            </p>
            {!packMatch && (
              <p style={{ fontSize: 12, color: '#cf1322', fontWeight: 600, marginBottom: 8 }}>
                前端预估 {cfg.estimated_pack_count} 包 ≠ 后端 {result.estimated_packs} 包。请先修复，不允许正式提取。
              </p>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 16px', fontSize: 12 }}>
              <span style={{ color: '#888' }}>预估包数</span><span style={{ fontWeight: 600 }}>{result.estimated_packs}</span>
              <span style={{ color: '#888' }}>LLM 调用</span><span>{result.estimated_llm_calls}</span>
              <span style={{ color: '#888' }}>输入 tokens</span><span>{result.estimated_input_tokens?.toLocaleString()}</span>
              <span style={{ color: '#888' }}>输出 tokens</span><span>{result.estimated_output_tokens?.toLocaleString()}</span>
              <span style={{ color: '#888' }}>预估费用</span><span style={{ fontWeight: 600, color: '#16a34a' }}>¥{result.estimated_cost_cny?.toFixed(4)}</span>
              <span style={{ color: '#888' }}>脑区数</span><span>{result.candidate_count}</span>
              {result.run_id && <><span style={{ color: '#888' }}>run_id</span><code style={{ fontSize: 10 }}>{result.run_id?.slice(0, 16)}…</code></>}
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="modal-footer" style={{ display: 'flex', gap: 8, justifyContent: 'space-between' }}>
        <div>
          <button className="llm-btn" onClick={() => setWizardStep(3) as any}>上一步</button>
          <button className="llm-btn" onClick={handleClose}>取消</button>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {preset?.endpoint_type === 'circuit_extraction' && preset?.input_pool_type !== 'connection_pool' && (
          <button className="llm-btn llm-btn-primary" onClick={handleDryRun} disabled={dryRunLoading}>
            {dryRunLoading ? '预估中…' : 'Dry Run 预估'}
          </button>
          )}
          {(() => {
            const isConnPool = preset?.input_pool_type === 'connection_pool'
            // Connection mode: skip Dry Run entirely (backend graph packing differs from frontend estimate)
            const needsDryRun = preset?.endpoint_type === 'circuit_extraction'
            const canStart = isConnPool
              ? (cfg.candidate_ids.length >= 2 && llmProvider && llmModel && cfg.candidates_per_pack >= 5)
              : needsDryRun
                ? (result && packMatch && cfg.candidate_ids.length >= 2 && llmProvider && llmModel && cfg.candidates_per_pack >= 5 && cfg.shuffle_rounds >= 1)
                : (cfg.candidate_ids.length >= 2 && llmProvider && llmModel)
            const disabledReasons: string[] = []
            if (cfg.candidate_ids.length < 2) disabledReasons.push(isConnPool ? '连接数不足' : '脑区数不足')
            if (!llmProvider || !llmModel) disabledReasons.push('请配置模型')
            if (needsDryRun && !isConnPool) {
              if (!result) disabledReasons.push('请先执行 Dry Run')
              if (!packMatch) disabledReasons.push('前后端包数不一致')
            }

            const handleStart = async () => {
              if (!canStart) return
              const body: any = {
                provider: llmProvider,
                model_name: llmModel || undefined,
                pool_id: cfg.pool_id || undefined,
                candidates_per_pack: cfg.candidates_per_pack,
                shuffle_rounds: cfg.shuffle_rounds,
                temperature,
                max_tokens: maxTokens,
                pack_concurrency: packConcurrency,
                skip_existing: skipExisting,
                dry_run: false,
                preset_id: preset?.preset_id,
                extraction_target: preset?.target,
                prompt_template_key: preset?.prompt_template_key,
                output_tables: preset?.output_tables,
                run_instruction_overlay: runInstructionOverlay || undefined,
              }
              // Connection pool → send connection_ids; region pool → send candidate_ids
              if (isConnPool) {
                body.connection_ids = cfg.candidate_ids
              } else {
                body.candidate_ids = cfg.candidate_ids
              }
              console.log('[llm-run-config][start-request]', {
                preset_id: preset?.preset_id,
                endpoint_type: preset?.endpoint_type,
                input_count: cfg.candidate_ids.length,
                input_type: isConnPool ? 'connections' : 'regions',
                candidates_per_pack: cfg.candidates_per_pack,
                shuffle_rounds: cfg.shuffle_rounds,
                frontend_estimated_pack_count: cfg.estimated_pack_count,
                dry_run_estimated_packs: result?.estimated_packs,
                provider: llmProvider,
                model_name: llmModel,
                temperature,
                max_tokens: maxTokens,
                pack_concurrency: packConcurrency,
                prompt_template_key: preset?.prompt_template_key,
                output_tables: preset?.output_tables,
                run_instruction_overlay_length: runInstructionOverlay.length,
              })
              try {
                // Route to correct API based on endpoint type
                if (preset?.endpoint_type === 'composite_workflow' || preset?.endpoint_type === 'field_or_composite') {
                  const { startCompositeWorkflow } = await import('../../../api/endpoints')
                  const resp = await startCompositeWorkflow({
                    workflow_type: (preset?.prompt_template_key?.includes('connection') ? 'connection_with_function' : 'circuit_with_function_steps') as any,
                    provider: body.provider,
                    model_name: body.model_name,
                    candidate_ids: isConnPool ? undefined : body.candidate_ids,
                    resource_id: pool?.resource_id || undefined,
                    batch_id: pool?.batch_id || undefined,
                    source_atlas: pool?.source_atlas || (cfg.pool_type === 'region_pool' ? 'AAL3' : undefined),
                    granularity_level: pool?.granularity_level || 'macro',
                    dry_run: false,
                    temperature: body.temperature,
                    max_tokens: body.max_tokens,
                    create_mirror_records: true,
                    create_evidence: true,
                    prompt_template_key: preset?.prompt_template_key || undefined,
                    prompt_overrides: editingPrompt && primaryTemplateKey ? { [primaryTemplateKey]: customUserPrompt } : undefined,
                  })
                  setProgress(prev => ({
                    ...prev,
                    workflowRunId: resp.workflow_run_id,
                    workflowStatus: resp.status,
                    progressPercent: 0,
                    processedPacks: 0,
                    totalPacks: cfg.estimated_pack_count,
                    errors: [],
                  }))
                } else {
                  const { runCircuitExtraction } = await import('../../../api/endpoints')
                  const resp = await runCircuitExtraction(body)
                  setProgress(prev => ({
                    ...prev,
                    workflowRunId: (resp as any).run_id || resp.run_id,
                    workflowStatus: 'pending',
                    progressPercent: 0,
                    processedPacks: 0,
                    totalPacks: (resp as any).estimated_packs || cfg.estimated_pack_count,
                  }))
                }
                startTimeRef.current = Date.now()
                setProgress(prev => ({ ...prev, successPacks: 0, failedPacks: 0, noConnectionPacks: 0, connectionsFound: 0, functionCount: 0, createdCount: 0 }))
                setModalState('progress')
              } catch (e: any) {
                setDryRunError('正式提取启动失败: ' + (e.message || String(e)))
              }
            }

            return (
              <button
                className="llm-btn"
                style={{ background: canStart ? '#16a34a' : '#ccc', color: '#fff', border: 'none' }}
                disabled={!canStart}
                title={disabledReasons.join('; ') || '开始正式提取'}
                onClick={handleStart}
              >
                开始正式提取
                {!canStart && disabledReasons.length > 0 && (
                  <span style={{ fontSize: 10, display: 'block' }}>{disabledReasons[0]}</span>
                )}
              </button>
            )
          })()}
        </div>
      </div>
    </>
    )
  }

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
              {(() => {
                // Progress text — dynamic based on available backend data
                if (effectiveProcessed > processed) {
                  return `正在处理第 ${currentPack}/${total} 包`
                }
                if (processed > 0) {
                  return `已完成 ${processed}/${total} 包`
                }
                // No packs completed yet — show what stage we're at
                if (progress.inFlightPacks > 0) {
                  return `${progress.inFlightPacks}/${progress.concurrency || 1} 包正在调用 LLM…`
                }
                if (progress.providerCallCount > 0) {
                  return `已发送 ${progress.providerCallCount} 次 LLM 请求`
                }
                if (progress.modelCalls > 0) {
                  return `已构建 ${progress.modelCalls}/${total} 包，等待 LLM 调用…`
                }
                if (total > 0) {
                  return `已规划 ${total} 包，排队中…`
                }
                if (progress.workflowStatus === 'running') {
                  return '后台任务运行中，正在构建 Prompt 包…'
                }
                return '正在启动后台任务…'
              })()}
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
              <div className="metric-label" style={{ color: '#d48806' }}>{isCircuitPackWorkflow(workflowType, preset) ? '无发现包' : '无连接包'}</div>
              <div className="metric-value" style={{ color: '#d48806' }}>
                {progress.noConnectionPacks > 0 ? progress.noConnectionPacks : '—'}
              </div>
            </div>
          </div>
        </div>

        {/* Circuit extraction stats — always show when in circuit mode */}
        {isCircuitPackWorkflow(workflowType, preset) && (
          <div className="modal-section">
            <p className="modal-section-title">回路提取统计</p>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
              <div style={{ background: '#f5f3ff', borderRadius: 6, padding: '10px 12px', textAlign: 'center' }}>
                <div style={{ fontSize: 20, fontWeight: 700, color: progress.connectionsFound > 0 ? '#7c3aed' : '#bbb' }}>{progress.connectionsFound}</div>
                <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>回路</div>
              </div>
              <div style={{ background: '#eff6ff', borderRadius: 6, padding: '10px 12px', textAlign: 'center' }}>
                <div style={{ fontSize: 20, fontWeight: 700, color: progress.functionCount > 0 ? '#2563eb' : '#bbb' }}>{progress.functionCount}</div>
                <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>步骤</div>
              </div>
              <div style={{ background: '#f0fdf4', borderRadius: 6, padding: '10px 12px', textAlign: 'center' }}>
                <div style={{ fontSize: 20, fontWeight: 700, color: progress.createdCount > 0 ? '#16a34a' : '#bbb' }}>{progress.createdCount}</div>
                <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>功能</div>
              </div>
            </div>
            {/* Real-time token & cost from backend */}
            <div style={{ display: 'flex', gap: 16, marginTop: 10, fontSize: 12, color: '#888' }}>
              <span>📥 prompt: <strong style={{ color: '#2563eb' }}>{progress.actualPromptTokens.toLocaleString()}</strong></span>
              <span>📤 completion: <strong style={{ color: '#16a34a' }}>{progress.actualCompletionTokens.toLocaleString()}</strong></span>
              <span>💰 cost: <strong style={{ color: '#dc2626' }}>{estimateCost(progress.actualPromptTokens, progress.actualCompletionTokens)}</strong></span>
            </div>
          </div>
        )}

        {/* Token usage (composite workflow) */}
        {!isCircuitPackWorkflow(workflowType, preset) && (
        <div className="modal-section">
          <p className="modal-section-title">用量</p>
          <div className="modal-section-row">
            <span className="label">预估输入</span>
            <span className="value">{progress.estimatedInputTokens.toLocaleString()} tokens</span>
          </div>
          <div className="modal-section-row">
            <span className="label">预估输出</span>
            <span className="value">{progress.estimatedOutputTokens.toLocaleString()} tokens</span>
          </div>
          {(progress.actualPromptTokens > 0 || progress.actualCompletionTokens > 0) && (
            <>
              <div className="modal-section-row">
                <span className="label">实际输入</span>
                <span className="value">{progress.actualPromptTokens.toLocaleString()} tokens</span>
              </div>
              <div className="modal-section-row">
                <span className="label">实际输出</span>
                <span className="value">{progress.actualCompletionTokens.toLocaleString()} tokens</span>
              </div>
              <div className="modal-section-row">
                <span className="label">预估费用</span>
                <span className="value" style={{ fontWeight: 600, color: '#2563eb' }}>
                  {estimateCost(progress.actualPromptTokens, progress.actualCompletionTokens)}
                </span>
              </div>
            </>
          )}
        </div>
        )}

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
        {progress.workflowStatus === 'dry_run' && (
          <div className="modal-section" style={{ background: '#f0f7ff', borderRadius: 8, padding: '12px 16px', border: '1px solid #bae0ff' }}>
            <p className="modal-section-title" style={{ color: '#0958d9' }}>📋 Dry Run 预览结果</p>
            <div className="modal-section-row">
              <span className="label">计划包数</span>
              <span className="value" style={{ fontWeight: 600 }}>{progress.totalPacks} 包</span>
            </div>
            <div className="modal-section-row">
              <span className="label">预估输入 tokens</span>
              <span className="value">{progress.estimatedInputTokens.toLocaleString()}</span>
            </div>
            <div className="modal-section-row">
              <span className="label">预估输出 tokens</span>
              <span className="value">{progress.estimatedOutputTokens.toLocaleString()}</span>
            </div>
            <div className="modal-section-row">
              <span className="label">预估费用</span>
              <span className="value" style={{ fontWeight: 600, color: '#2563eb' }}>
                {estimateCost(progress.estimatedInputTokens, progress.estimatedOutputTokens)}
              </span>
            </div>
            {progress.connectionsFound > 0 && (
              <div style={{ marginTop: 8, padding: '8px 12px', background: '#f6ffed', borderRadius: 6, fontSize: 12, border: '1px solid #b7eb8f' }}>
                ✅ 样本包解析到 {progress.connectionsFound} 条连接（仅预览，未写入数据库）
              </div>
            )}
            {progress.errors.length > 0 && (
              <div style={{ marginTop: 8, padding: '8px 12px', background: '#fff2f0', borderRadius: 6, fontSize: 12, border: '1px solid #ffccc7' }}>
                ⚠ 样本包执行异常: {progress.errors[0]}
              </div>
            )}
          </div>
        )}
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

        {/* Cost */}
        {(progress.actualPromptTokens > 0 || progress.actualCompletionTokens > 0) && (
          <div className="modal-section">
            <p className="modal-section-title">费用</p>
            <div className="modal-section-row">
              <span className="label">输入 tokens</span>
              <span className="value">{progress.actualPromptTokens.toLocaleString()}</span>
            </div>
            <div className="modal-section-row">
              <span className="label">输出 tokens</span>
              <span className="value">{progress.actualCompletionTokens.toLocaleString()}</span>
            </div>
            <div className="modal-section-row">
              <span className="label">预估费用</span>
              <span className="value" style={{ fontSize: 16, fontWeight: 600, color: '#2563eb' }}>
                {estimateCost(progress.actualPromptTokens, progress.actualCompletionTokens)}
              </span>
            </div>
          </div>
        )}

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
        {progress.failedPacks > 0 && (
          <button
            className="llm-btn llm-btn-primary"
            onClick={async () => {
              try {
                const resp = await retryFailedCompositeWorkflow(progress.workflowRunId)
                setProgress(prev => ({
                  ...prev,
                  workflowRunId: resp.workflow_run_id,
                  workflowStatus: resp.status,
                  progressPercent: 0,
                  processedPacks: 0,
                  totalPacks: resp.pair_count ? Math.ceil(resp.pair_count / 30) : prev.totalPacks,
                  successPacks: 0,
                  failedPacks: 0,
                  connectionsFound: 0,
                  createdCount: 0,
                  updatedCount: 0,
                  errors: [],
                  elapsedSec: 0,
                  startedAt: new Date().toISOString(),
                }))
                startTimeRef.current = Date.now()
                setModalState('progress')
              } catch (err: any) {
                setProgress(prev => ({
                  ...prev,
                  errors: [...prev.errors, `重试失败: ${err?.message || err}`],
                }))
              }
            }}
          >
            重试失败包 ({progress.failedPacks})
          </button>
        )}
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
          minHeight: wizardStep !== 1 ? lockedPanelHeight : 520,
          maxHeight: '85vh',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {modalState === 'prepare' && wizardStep === 1 && renderStep1()}
        {modalState === 'prepare' && wizardStep === 2 && renderStep2()}
        {modalState === 'prepare' && wizardStep === 3 && renderStep3()}
        {modalState === 'prepare' && (wizardStep as number) === 4 && renderStep4()}
        {modalState === 'progress' && renderProgress()}
        {modalState === 'result' && renderResult()}
      </div>
    </div>
  )
}
