import { useCallback, useState } from 'react'
import { useI18n } from '../../../i18n-context'
import { MultiTargetFieldCompletionModal } from '../../data-center/MultiTargetFieldCompletionModal'
import type { CompositeSubstepResult } from '../services/compositeExtractionRunner'
import {
  hasCircuitBundleCreation,
  resolveCircuitBundleForExtraction,
} from '../utils/extractionToFieldCompletion'
import type { CircuitBundleFieldCompletionGroup } from '../../data-center/circuitBundleTypes'

import type { LlmWorkflowEvent } from '../../../api/endpoints'

const PROVIDER_SCHEDULING_TIMEOUT_SECONDS = 60

const TERMINAL_PROVIDER_FAILURE_STATUSES = new Set([
  'failed_provider_not_called',
  'failed',
  'failed_no_output',
  'failed_parse_error',
  'failed_provider_empty_response',
  'failed_provider_error',
])

export type ProviderAuditTone = 'info' | 'warning' | 'danger' | 'muted'

export function resolveProviderAudit(
  dryRun: boolean,
  summary?: Record<string, unknown>,
  displayStatus?: string,
  elapsedMs?: number,
  connectionStepStatus?: string,
): { message?: string; tone?: ProviderAuditTone } {
  if (displayStatus === 'cleanup_done') {
    return { message: '本轮已取消并清理，不再继续调用模型。', tone: 'muted' }
  }
  if (displayStatus === 'cancelled' || displayStatus === 'cancelling') {
    return { message: '本轮已取消。', tone: 'muted' }
  }
  if (displayStatus === 'cleanup_failed') {
    return { message: '本轮已取消，但清理失败，请重试清理。', tone: 'danger' }
  }
  if (!summary) return {}
  const lateIgnored = Number(summary.late_provider_response_ignored ?? 0)
  if (lateIgnored > 0) {
    return { message: '取消后仍有模型响应返回，系统已忽略且未写库。', tone: 'warning' }
  }
  if (dryRun) return {}

  const providerCallCount = Number(summary.provider_call_count ?? 0)
  const outputCount = Number(summary.created_projection_count ?? summary.mirror_connection_created_count ?? 0)
  const noConnectionCount = Number(summary.no_connection_count ?? 0)
  const pairCount = Number(summary.pair_count ?? 0)
  const packCount = Number(summary.pack_count ?? 0)
  const promptBuiltCount = Number(summary.prompt_built_count ?? 0)
  const promptSentCount = Number(summary.prompt_sent_count ?? 0)
  const parseErrorCount = Number(summary.parse_error_count ?? 0)
  const schemaErrorCount = Number(summary.schema_error_count ?? 0)
  const transportErrorCount = Number(summary.provider_transport_error_count ?? 0)
  const execStatus = String(summary.status ?? '')

  const isRunningPhase =
    displayStatus === 'running'
    || displayStatus === 'pending'
    || displayStatus === 'starting'
    || displayStatus === 'cleanup_in_progress'

  if (isRunningPhase) {
    if (providerCallCount > 0) {
      return { message: '模型调用进行中。', tone: 'info' }
    }
    const elapsedSec = (elapsedMs ?? 0) / 1000
    if (
      elapsedSec >= PROVIDER_SCHEDULING_TIMEOUT_SECONDS
      && packCount > 0
      && promptBuiltCount === 0
      && promptSentCount === 0
      && providerCallCount === 0
    ) {
      return {
        message: '模型调用尚未开始，可能仍在构建 prompt 或等待调度；若长时间不变化，请检查后端日志。',
        tone: 'warning',
      }
    }
    if (packCount > 0 && promptBuiltCount === 0 && promptSentCount === 0) {
      return { message: '正在构建 pack / 调度 provider 调用。', tone: 'info' }
    }
    return { message: '正在等待模型调用开始。若长时间保持 0，请检查 pack 调度日志。', tone: 'info' }
  }

  const isTerminalFailure =
    TERMINAL_PROVIDER_FAILURE_STATUSES.has(displayStatus ?? '')
    || connectionStepStatus === 'failed_provider_not_called'
    || execStatus === 'failed_provider_not_called'
    || (
      pairCount > 0
      && providerCallCount === 0
      && displayStatus !== 'cancelled'
      && displayStatus !== 'cleanup_done'
      && displayStatus !== 'succeeded_no_edges'
      && displayStatus !== 'no_edges'
      && !dryRun
      && !isRunningPhase
    )

  if (isTerminalFailure && providerCallCount === 0) {
    return { message: '未真正调用模型。', tone: 'danger' }
  }

  if (providerCallCount > 0 && (parseErrorCount > 0 || schemaErrorCount > 0) && outputCount === 0) {
    return {
      message: '模型已调用，但返回格式不可解析。',
      tone: 'danger',
    }
  }
  if (transportErrorCount > 0 && providerCallCount > 0 && outputCount === 0 && parseErrorCount === 0) {
    return {
      message: '模型请求传输失败（HTTP/超时/网络）。请检查网络、API Key 与限流，而非 JSON 解析。',
      tone: 'danger',
    }
  }
  if (providerCallCount > 0 && outputCount === 0 && (parseErrorCount > 0 || schemaErrorCount > 0)) {
    return {
      message: '模型已调用，但返回内容无法解析为要求的 JSON。请展开查看 raw response preview，并检查 prompt 或 parser。',
      tone: 'danger',
    }
  }
  if (providerCallCount > 0 && outputCount === 0 && noConnectionCount >= pairCount && pairCount > 0) {
    return { message: '模型已完成 pair 判断，但未发现可写入 Projection。', tone: 'info' }
  }
  if (providerCallCount > 0 && outputCount === 0) {
    return { message: '模型已调用，但没有生成可写入 Projection。', tone: 'warning' }
  }
  return {}
}

function resolveProviderAuditMessage(
  dryRun: boolean,
  summary?: Record<string, unknown>,
  displayStatus?: string,
  elapsedMs?: number,
  connectionStepStatus?: string,
): string | undefined {
  return resolveProviderAudit(dryRun, summary, displayStatus, elapsedMs, connectionStepStatus).message
}

function extractConnectionExecutionSummary(
  substeps?: CompositeSubstepResult[],
  data?: ExtractionResultModalData,
): Record<string, unknown> | undefined {
  const connStep = substeps?.find(s => s.id === 'connection')
  const fromSubstep = connStep?.executionSummary as Record<string, unknown> | undefined
  const topProviderAudit = data?.providerAudit as Record<string, unknown> | undefined
  const resultSummary = data?.resultSummary as Record<string, unknown> | undefined
  const resultSummaryProviderAudit = resultSummary?.provider_audit as Record<string, unknown> | undefined
  const fromSubstepProviderAudit = fromSubstep?.provider_audit as Record<string, unknown> | undefined
  const providerAudit = topProviderAudit
    ?? resultSummaryProviderAudit
    ?? fromSubstepProviderAudit
    ?? (data?.executionSummary?.provider_audit as Record<string, unknown> | undefined)
  const packSummaries = resolvePackSummaries(
    topProviderAudit,
    resultSummary,
    fromSubstep,
    providerAudit,
    data?.recentEvents,
  )

  const merged: Record<string, unknown> = {
    ...(fromSubstep ?? {}),
    ...(resultSummary ?? {}),
    ...(data?.executionSummary ?? {}),
  }
  if (providerAudit) {
    merged.provider_audit = providerAudit
    for (const [key, val] of Object.entries(providerAudit)) {
      if (key === 'errors' || key === 'pack_summaries') continue
      if (val != null) merged[key] = val
    }
  }
  if (packSummaries.length > 0) {
    merged.pack_summaries = packSummaries
  }
  return Object.keys(merged).length > 0 ? merged : undefined
}

function resolvePackSummaries(
  topProviderAudit?: Record<string, unknown>,
  resultSummary?: Record<string, unknown>,
  executionSummary?: Record<string, unknown>,
  nestedProviderAudit?: Record<string, unknown>,
  recentEvents?: LlmWorkflowEvent[],
): PackSummary[] {
  const paths: unknown[] = [
    topProviderAudit?.pack_summaries,
    (resultSummary?.provider_audit as Record<string, unknown> | undefined)?.pack_summaries,
    resultSummary?.pack_summaries,
    nestedProviderAudit?.pack_summaries,
    executionSummary?.pack_summaries,
    (executionSummary?.provider_audit as Record<string, unknown> | undefined)?.pack_summaries,
  ]
  for (const candidate of paths) {
    if (Array.isArray(candidate) && candidate.length > 0) {
      return candidate as PackSummary[]
    }
  }
  const fromEvents: PackSummary[] = []
  for (const event of recentEvents ?? []) {
    if (event.event !== 'provider_response_parse_error') continue
    const preview = event.data?.raw_response_preview
    if (typeof preview !== 'string' || !preview) continue
    fromEvents.push({
      pack_id: Number(event.data?.pack_id ?? fromEvents.length),
      parse_error: String(event.data?.parse_error ?? event.message),
      parse_error_type: String(event.data?.parse_error_type ?? 'json_decode_error'),
      raw_response_preview: preview,
      response_received: true,
    })
  }
  return fromEvents
}

function resolveProviderAuditCounts(summary?: Record<string, unknown>): {
  providerSuccessCount: number
  parseErrorCount: number
  failedPackCount: number
} {
  const packs = (summary?.pack_summaries as PackSummary[] | undefined) ?? []
  const responseReceived = packs.filter(p => p.response_received).length
  const providerSuccessCount = Math.max(
    Number(summary?.provider_success_count ?? 0),
    Number(summary?.response_received_count ?? 0),
    responseReceived,
  )
  return {
    providerSuccessCount,
    parseErrorCount: Number(summary?.parse_error_count ?? 0),
    failedPackCount: Number(
      summary?.failed_pack_count
      ?? packs.filter(p => p.parse_error || p.parse_error_type === 'json_decode_error' || p.parse_error_type === 'schema_error').length,
    ),
  }
}

function ParseFailureDetails({
  execSummary,
  t,
}: {
  execSummary: Record<string, unknown>
  t: (key: string, params?: Record<string, string | number>) => string
}) {
  const counts = resolveProviderAuditCounts(execSummary)
  const packs = (execSummary.pack_summaries as PackSummary[] | undefined) ?? []
  const failed = packs.filter(
    p => p.parse_error
      || p.parse_error_type === 'json_decode_error'
      || p.parse_error_type === 'schema_error',
  )
  if (counts.parseErrorCount <= 0 && failed.length === 0) return null

  const [open, setOpen] = useState(counts.parseErrorCount > 0)
  const previewPacks = failed.slice(0, 3)
  const missingSummaries = counts.parseErrorCount > 0 && packs.length === 0
  const failFast = Boolean(execSummary.fail_fast_triggered)
  const remainingSkipped = Number(execSummary.remaining_pack_count_skipped ?? 0)

  return (
    <div className="llm-result-parse-diagnostics">
      {failFast && (
        <div className="llm-result-provider-audit llm-result-provider-audit-warning">
          {t('llm.resultModal.failFastMessage', { count: remainingSkipped })}
        </div>
      )}
      {missingSummaries && (
        <div className="llm-result-provider-audit llm-result-provider-audit-danger">
          {t('llm.resultModal.missingProviderAuditPackSummariesError')}
        </div>
      )}
      <div className="llm-result-parse-diagnostics-intro">
        {t('llm.resultModal.parseFailureIntro')}
      </div>
      <button type="button" className="llm-btn llm-btn-xs llm-btn-ghost" onClick={() => setOpen(o => !o)}>
        {open ? t('llm.resultModal.hideParseFailureDetails') : t('llm.resultModal.showParseFailureDetails')}
        {' '}({Math.max(counts.parseErrorCount, failed.length)})
      </button>
      {open && (
        <div className="llm-result-parse-diagnostics-list">
          {previewPacks.map((p, i) => (
            <ParseFailurePackRow key={p.pack_id ?? i} pack={p} t={t} defaultExpanded={i === 0} />
          ))}
        </div>
      )}
    </div>
  )
}

function ParseFailurePackRow({
  pack,
  t,
  defaultExpanded = false,
}: {
  pack: PackSummary
  t: (key: string, params?: Record<string, string | number>) => string
  defaultExpanded?: boolean
}) {
  const [previewOpen, setPreviewOpen] = useState(defaultExpanded)
  return (
    <div className="llm-result-pack-trace">
      <div className="llm-result-pack-trace-head">
        pack #{pack.pack_id ?? pack.pack_index ?? '?'}
        {pack.parse_error_type ? ` · ${pack.parse_error_type}` : ''}
        {pack.response_char_count != null ? ` · ${pack.response_char_count} chars` : ''}
      </div>
      {pack.parse_error && <div className="llm-result-pack-trace-error">{pack.parse_error}</div>}
      {pack.raw_response_preview && (
        <>
          <button
            type="button"
            className="llm-btn llm-btn-xs llm-btn-ghost"
            onClick={() => setPreviewOpen(o => !o)}
          >
            {previewOpen ? t('llm.resultModal.hideRawPreview') : t('llm.resultModal.showRawPreview')}
          </button>
          {previewOpen && (
            <pre className="llm-result-raw-preview">{pack.raw_response_preview}</pre>
          )}
        </>
      )}
    </div>
  )
}

interface PackSummary {
  pack_id?: number
  pack_index?: number
  parse_error?: string
  parse_error_type?: string
  schema_error?: string
  raw_response_preview?: string
  prompt_display_name?: string
  response_received?: boolean
  response_char_count?: number
}

function WorkflowEventsPanel({
  events,
  t,
}: {
  events: LlmWorkflowEvent[]
  t: (key: string, params?: Record<string, string | number>) => string
}) {
  const errorCount = events.filter(e => e.level === 'error').length
  const [open, setOpen] = useState(errorCount > 0)
  const [expandedPreview, setExpandedPreview] = useState<Record<number, boolean>>({})

  if (events.length === 0) return null

  const sorted = [...events].sort((a, b) => a.ts.localeCompare(b.ts))

  return (
    <div className="llm-result-section llm-result-workflow-events">
      <button
        type="button"
        className="llm-result-section-title llm-result-events-toggle"
        onClick={() => setOpen(o => !o)}
      >
        {t('llm.resultModal.workflowEvents')}
        {errorCount > 0 && <span className="llm-result-events-error-count">{errorCount}</span>}
        <span className="llm-result-events-count">({events.length})</span>
      </button>
      {open && (
        <div className="llm-result-events-list">
          {sorted.map((ev, i) => {
            const preview = ev.data?.raw_response_preview
            const hasPreview = typeof preview === 'string' && preview.length > 0
            return (
              <div key={ev.event_id ?? `${ev.ts}-${i}`} className={`llm-result-event llm-result-event-${ev.level}`}>
                <div className="llm-result-event-head">
                  <span className="llm-result-event-ts">{ev.ts.slice(11, 19)}</span>
                  <span className="llm-result-event-level">{ev.level}</span>
                  {ev.step_key && <span className="llm-result-event-step">{ev.step_key}</span>}
                  <span className="llm-result-event-name">{ev.event}</span>
                </div>
                <div className="llm-result-event-message">{ev.message}</div>
                {ev.data && Object.keys(ev.data).length > 0 && (
                  <div className="llm-result-event-data">
                    {Object.entries(ev.data)
                      .filter(([k]) => k !== 'raw_response_preview')
                      .map(([k, v]) => (
                        <span key={k} className="llm-result-event-kv">{k}={String(v)}</span>
                      ))}
                  </div>
                )}
                {hasPreview && (
                  <>
                    <button
                      type="button"
                      className="llm-btn llm-btn-xs llm-btn-ghost"
                      onClick={() => setExpandedPreview(prev => ({ ...prev, [i]: !prev[i] }))}
                    >
                      {expandedPreview[i] ? t('llm.resultModal.hideRawPreview') : t('llm.resultModal.showRawPreview')}
                    </button>
                    {expandedPreview[i] && (
                      <pre className="llm-result-raw-preview">{preview}</pre>
                    )}
                  </>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function formatElapsed(ms?: number): string {
  if (ms == null || ms < 0) return '0s'
  const sec = Math.floor(ms / 1000)
  if (sec < 60) return `${sec}s`
  const min = Math.floor(sec / 60)
  return `${min}m ${sec % 60}s`
}

export interface ExtractionResultModalData {
  status:
    | 'succeeded'
    | 'partially_succeeded'
    | 'failed'
    | 'skipped'
    | 'failed_validation'
    | 'dry_run'
    | 'no_edges'
    | 'failed_provider_not_called'
    | 'cancelled'
    | 'cleanup_done'
    | 'cleanup_failed'
  taskId: string
  taskLabel: string
  provider: string
  modelName: string
  dryRun: boolean
  selectedCount: number
  pairCount?: number
  phase?: 'starting' | 'running' | 'complete'
  progressPercent?: number
  indeterminate?: boolean
  elapsedMs?: number
  workflowStatus?: string
  workflowOutcome?: string
  substeps?: CompositeSubstepResult[]
  createdCounts?: Record<string, number>
  skippedDuplicates?: Record<string, number>
  warnings?: string[]
  errors?: string[]
  runIds?: string[]
  workflowRunId?: string
  serverSide?: boolean
  cancelPhase?: 'idle' | 'confirm' | 'cancelling' | 'cleanup_done' | 'cleanup_failed'
  cancelError?: string
  cleanupDeleted?: Record<string, number>
  targets?: string[]
  executionSummary?: Record<string, unknown>
  providerAudit?: Record<string, unknown>
  resultSummary?: Record<string, unknown>
  diagnostics?: Array<Record<string, unknown>>
  providerAuditMessage?: string
  providerAuditTone?: ProviderAuditTone
  recentEvents?: LlmWorkflowEvent[]
  uiPaused?: boolean
}

interface Props {
  data: ExtractionResultModalData | null
  minimized?: boolean
  onClose: () => void
  onMinimize?: () => void
  onTogglePause?: () => void
  onCancelAndCleanup?: (workflowRunId: string) => Promise<void>
  onRetryCleanup?: (workflowRunId: string) => Promise<void>
  onViewMirror?: () => void
  onOpenDataCenter?: (hash: string) => void
  onViewRuns?: () => void
  onViewItems?: () => void
  onBundleCompleted?: () => void
}

type WorkflowDisplayTone = 'success' | 'warning' | 'danger' | 'info' | 'muted'

export interface WorkflowDisplayStatus {
  status: string
  label: string
  tone: WorkflowDisplayTone
}

const WORKFLOW_DISPLAY_MAP: Record<string, { label: string; tone: WorkflowDisplayTone }> = {
  succeeded: { label: '成功', tone: 'success' },
  partially_succeeded: { label: '部分成功', tone: 'warning' },
  failed: { label: '失败', tone: 'danger' },
  failed_no_output: { label: '失败：无输出', tone: 'danger' },
  failed_provider_not_called: { label: '未真正调用模型', tone: 'danger' },
  failed_provider_empty_response: { label: '模型空返回', tone: 'danger' },
  failed_parse_error: { label: '返回解析失败', tone: 'danger' },
  failed_provider_error: { label: 'Provider 错误', tone: 'danger' },
  skipped: { label: '已跳过', tone: 'muted' },
  failed_validation: { label: '前端校验失败', tone: 'danger' },
  dry_run: { label: 'Dry Run 预览', tone: 'info' },
  no_output: { label: '无输出', tone: 'warning' },
  no_edges: { label: '未生成连接', tone: 'warning' },
  succeeded_no_edges: { label: '未生成连接', tone: 'warning' },
  skipped_no_projection: { label: '无连接可提取功能', tone: 'muted' },
  running: { label: '运行中', tone: 'info' },
  pending: { label: '等待中', tone: 'info' },
  cancelling: { label: '正在取消', tone: 'warning' },
  cancelled: { label: '已取消', tone: 'muted' },
  cleanup_in_progress: { label: '正在清理', tone: 'warning' },
  cleanup_done: { label: '已取消并清理', tone: 'muted' },
  cleanup_failed: { label: '清理失败', tone: 'danger' },
  unknown: { label: '未知', tone: 'muted' },
}

// Statuses where the card must NEVER be shown as a green "success".
const NON_SUCCESS_WORKFLOW_STATUSES = new Set<string>([
  'no_edges',
  'succeeded_no_edges',
  'cancelling',
  'cancelled',
  'cleanup_in_progress',
  'cleanup_done',
  'cleanup_failed',
  'failed',
  'failed_provider_not_called',
  'failed_provider_empty_response',
  'failed_parse_error',
  'failed_no_output',
  'failed_provider_error',
])

function resolveRawWorkflowStatus(data: ExtractionResultModalData): string {
  const cancelPhase = data.cancelPhase ?? 'idle'
  if (cancelPhase === 'cleanup_done') return 'cleanup_done'
  if (cancelPhase === 'cleanup_failed') return 'cleanup_failed'
  if (cancelPhase === 'cancelling') return 'cancelling'
  const semantic = data.workflowOutcome
    ?? (data.executionSummary?.display_status as string | undefined)
    ?? (data.executionSummary?.semantic_status as string | undefined)
    ?? (data.executionSummary?.outcome as string | undefined)
  if (semantic === 'succeeded_no_edges' || semantic === 'no_edges') return 'succeeded_no_edges'
  if (semantic === 'skipped_no_projection') return 'skipped_no_projection'
  if (data.phase === 'starting' || data.phase === 'running') {
    if (data.workflowStatus === 'cancelling') return 'cancelling'
    if (data.workflowStatus === 'cleanup_in_progress') return 'cleanup_in_progress'
    return data.workflowStatus ?? 'running'
  }
  // Prefer the authoritative backend workflow status when it is a terminal
  // cancel/cleanup/failure state, so a stale default 'succeeded' is never shown.
  if (data.workflowStatus && NON_SUCCESS_WORKFLOW_STATUSES.has(data.workflowStatus)) {
    return data.workflowStatus
  }
  return data.status || data.workflowStatus || 'unknown'
}

export function getWorkflowDisplayStatus(data: ExtractionResultModalData): WorkflowDisplayStatus {
  const status = resolveRawWorkflowStatus(data)
  const mapped = WORKFLOW_DISPLAY_MAP[status]
  if (mapped) return { status, ...mapped }
  return { status, label: status, tone: 'muted' }
}

const COUNT_LABELS: Record<string, string> = {
  connections: '连接 (mirror_region_connections)',
  functions: '功能 (mirror_region_functions)',
  circuits: '回路 (mirror_region_circuits)',
  circuit_steps: '回路步骤 (mirror_circuit_steps)',
  circuit_functions: '回路功能 (mirror_circuit_functions)',
  projection_functions: '连接功能 (mirror_projection_functions)',
  memberships: 'Membership (mirror_circuit_projection_memberships)',
  triples: '三元组 (mirror_kg_triples)',
  evidence: '证据 (mirror_evidence_records)',
}

const SUBSTEP_STATUS_LABELS: Record<string, string> = {
  pending: 'pending',
  running: 'running',
  succeeded: 'succeeded',
  failed: 'failed',
  skipped: 'skipped',
  skipped_no_projection: '无连接可提取功能',
  skipped_dependency_failed: '依赖步骤失败',
  cancelled: 'cancelled',
  failed_validation: 'failed_validation',
}

export function ExtractionResultModal({
  data,
  minimized = false,
  onClose,
  onMinimize,
  onTogglePause,
  onCancelAndCleanup,
  onRetryCleanup,
  onViewMirror,
  onOpenDataCenter,
  onViewRuns,
  onViewItems,
  onBundleCompleted,
}: Props) {
  const { t } = useI18n()
  const [bundleOpen, setBundleOpen] = useState(false)
  const [bundleLoading, setBundleLoading] = useState(false)
  const [circuitBundle, setCircuitBundle] = useState<CircuitBundleFieldCompletionGroup | null>(null)
  const [bundleWarnings, setBundleWarnings] = useState<string[]>([])
  const [showAdvancedCompletion, setShowAdvancedCompletion] = useState(false)
  const [cancelConfirmOpen, setCancelConfirmOpen] = useState(false)

  const openCircuitBundle = useCallback(() => {
    if (!data) return
    setBundleOpen(true)
    setBundleLoading(true)
    setCircuitBundle(null)
    setBundleWarnings([])
    void resolveCircuitBundleForExtraction(data)
      .then(({ bundle, warnings }) => {
        setCircuitBundle(bundle)
        setBundleWarnings(warnings)
      })
      .finally(() => setBundleLoading(false))
  }, [data])

  if (!data || minimized) return null

  const isRunning = data.phase === 'starting' || data.phase === 'running'
  const uiPaused = data.uiPaused ?? false
  const createdEntries = Object.entries(data.createdCounts ?? {}).filter(([, v]) => v > 0)
  const showCircuitBundle = hasCircuitBundleCreation(data)
  const circuitCount = data.createdCounts?.circuits ?? 0
  const stepCount = data.createdCounts?.circuit_steps ?? 0
  const functionCount = data.createdCounts?.circuit_functions ?? 0
  const execSummary = data.executionSummary
    ?? extractConnectionExecutionSummary(data.substeps, data)
  const cancelPhase = data.cancelPhase ?? 'idle'
  const isCancelling = cancelPhase === 'cancelling'
  const cleanupFailed = cancelPhase === 'cleanup_failed'
  const cleanupDone = cancelPhase === 'cleanup_done'
  const displayStatus = getWorkflowDisplayStatus(data)
  const connStep = data.substeps?.find(s => s.id === 'connection')
  const providerAudit = data.providerAuditMessage != null && data.providerAuditTone != null
    ? { message: data.providerAuditMessage, tone: data.providerAuditTone }
    : resolveProviderAudit(
      data.dryRun,
      execSummary,
      displayStatus.status,
      data.elapsedMs,
      connStep?.status,
    )
  const providerAuditMessage = providerAudit.message
  const providerAuditTone = providerAudit.tone ?? 'info'
  const auditCounts = execSummary ? resolveProviderAuditCounts(execSummary) : null
  const packCount = Number(execSummary?.pack_count ?? 0)
  const executedPackCount = Number(execSummary?.executed_pack_count ?? 0)
  const plannedPackCount = Number(execSummary?.planned_pack_count ?? 0)
  const skippedDebugPackCount = Number(execSummary?.skipped_debug_pack_count ?? 0)
  const debugSinglePackEnabled = Boolean(execSummary?.debug_single_pack)
  const providerCallCountForDebug = Number(execSummary?.provider_call_count ?? 0)

  const handleClose = () => {
    if (cleanupFailed) return
    if (isRunning && data.serverSide && data.workflowRunId && onCancelAndCleanup && !cleanupDone) {
      setCancelConfirmOpen(true)
      return
    }
    onClose()
  }

  const handleContinueRunning = () => {
    setCancelConfirmOpen(false)
  }

  const handleCancelAndCleanup = async () => {
    if (!data.workflowRunId || !onCancelAndCleanup) return
    setCancelConfirmOpen(false)
    await onCancelAndCleanup(data.workflowRunId)
  }

  return (
    <>
      <MultiTargetFieldCompletionModal
        open={bundleOpen}
        bundle={circuitBundle}
        resolveWarnings={bundleWarnings}
        loading={bundleLoading}
        onClose={() => setBundleOpen(false)}
        onCompleted={() => {
          onBundleCompleted?.()
        }}
        onOpenDataCenter={onOpenDataCenter ? () => onOpenDataCenter('#/data-center?tab=mirror') : undefined}
      />
      <div className="llm-result-modal-backdrop" onClick={cleanupFailed ? undefined : handleClose} />
      <div className="llm-result-modal" role="dialog" aria-modal="true">
        {cancelConfirmOpen && (
          <div className="llm-result-cancel-confirm">
            <div className="llm-result-cancel-confirm-title">{t('llm.resultModal.cancelConfirmTitle')}</div>
            <p className="llm-result-cancel-confirm-body">{t('llm.resultModal.cancelConfirmBody')}</p>
            <div className="llm-result-cancel-confirm-actions">
              <button type="button" className="llm-btn" onClick={handleContinueRunning}>
                {t('llm.resultModal.continueRunning')}
              </button>
              <button type="button" className="llm-btn llm-btn-danger" onClick={() => void handleCancelAndCleanup()}>
                {t('llm.resultModal.cancelAndCleanup')}
              </button>
            </div>
          </div>
        )}
        <div className="llm-result-modal-header">
          <div>
            <div className="llm-result-modal-title">
              {isRunning ? t('llm.resultModal.runningTitle') : t('llm.resultModal.title')}
            </div>
            <div className="llm-result-modal-subtitle">{data.taskLabel}</div>
          </div>
          <div className="llm-result-modal-header-actions">
            {isRunning && onTogglePause && (
              <button type="button" className="llm-btn llm-btn-ghost llm-btn-sm" onClick={onTogglePause}>
                {uiPaused ? t('llm.resultModal.resumeUi') : t('llm.resultModal.pauseUi')}
              </button>
            )}
            {isRunning && onMinimize && (
              <button type="button" className="llm-btn llm-btn-ghost llm-btn-sm" onClick={onMinimize}>
                {t('llm.resultModal.minimize')}
              </button>
            )}
            <button type="button" className="llm-btn llm-btn-ghost" onClick={handleClose}>✕</button>
          </div>
        </div>

        <div className="llm-result-modal-body">
          {isRunning && uiPaused && (
            <div className="llm-result-ui-paused-banner">
              {t('llm.resultModal.uiPausedBanner')}
            </div>
          )}
          {isRunning && (
            <div className="llm-extraction-progress">
              <div className="llm-extraction-progress-meta">
                {data.workflowRunId && (
                  <span>{t('llm.resultModal.workflowRunId')}: <code>{data.workflowRunId.slice(0, 12)}…</code></span>
                )}
                {data.workflowStatus && <span>{t('llm.resultModal.status')}: {data.workflowStatus}</span>}
                {isCancelling && <span>{t('llm.resultModal.cancelling')}</span>}
                {cleanupDone && <span>{t('llm.resultModal.cleanupDone')}</span>}
                {cleanupFailed && <span>{t('llm.resultModal.cleanupFailed')}</span>}
                <span>{t('llm.resultModal.elapsed')}: {formatElapsed(data.elapsedMs)}</span>
              </div>
              <div className="llm-extraction-progress-bar" aria-hidden="true">
                <div
                  className={`llm-extraction-progress-fill${data.indeterminate ? ' llm-extraction-progress-indeterminate' : ''}`}
                  style={data.indeterminate ? undefined : { width: `${Math.min(100, Math.max(0, data.progressPercent ?? 0))}%` }}
                />
              </div>
              {!data.indeterminate && (
                <div className="llm-extraction-progress-meta">
                  {t('llm.resultModal.progress')}: {data.progressPercent ?? 0}%
                </div>
              )}
              <div className="llm-extraction-running-note">{t('llm.resultModal.runningNote')}</div>
            </div>
          )}
          {cleanupFailed && data.cancelError && (
            <div className="llm-result-section">
              <div className="llm-result-section-title">{t('llm.resultModal.errors')}</div>
              <div className="llm-result-error-item">{data.cancelError}</div>
              {data.workflowRunId && onRetryCleanup && (
                <button type="button" className="llm-btn" onClick={() => void onRetryCleanup(data.workflowRunId!)}>
                  {t('llm.resultModal.retryCleanup')}
                </button>
              )}
            </div>
          )}
          {cleanupDone && data.cleanupDeleted && (
            <div className="llm-result-section">
              <div className="llm-result-section-title">{t('llm.resultModal.cleanupDeleted')}</div>
              <div className="llm-result-summary-grid">
                {Object.entries(data.cleanupDeleted).filter(([, v]) => v > 0).map(([key, val]) => (
                  <div key={key} className="llm-result-count-card">
                    <span className="llm-result-count-label">{key}</span>
                    <span className="llm-result-count-value">{val}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="llm-result-summary-grid">
            <div className="llm-result-count-card">
              <span className="llm-result-count-label">{t('llm.resultModal.status')}</span>
              <span className={`llm-result-status llm-result-status-${displayStatus.status} llm-result-status-tone-${displayStatus.tone}`}>
                {displayStatus.label}
              </span>
            </div>
            <div className="llm-result-count-card">
              <span className="llm-result-count-label">{t('llm.resultModal.task')}</span>
              <span>{data.selectedCount} 候选</span>
            </div>
            {data.pairCount != null && data.pairCount > 0 && (
              <div className="llm-result-count-card">
                <span className="llm-result-count-label">Pair 数</span>
                <span>{data.pairCount}</span>
              </div>
            )}
            <div className="llm-result-count-card">
              <span className="llm-result-count-label">Provider</span>
              <span>{data.provider} / {data.modelName || 'default'}</span>
            </div>
            <div className="llm-result-count-card">
              <span className="llm-result-count-label">Dry Run</span>
              <span>{data.dryRun ? 'Yes' : 'No'}</span>
            </div>
            {data.serverSide && (
              <div className="llm-result-count-card">
                <span className="llm-result-count-label">{t('llm.resultModal.serverWorkflow')}</span>
                <span>{t('llm.resultModal.serverWorkflowYes')}</span>
              </div>
            )}
          </div>

          {execSummary && (
            <div className="llm-result-section">
              <div className="llm-result-section-title">{t('llm.resultModal.providerAudit')}</div>
              <div className="llm-result-summary-grid">
                {(() => {
                  const counts = auditCounts ?? resolveProviderAuditCounts(execSummary)
                  const gridEntries: Array<[string, unknown]> = [
                    ['provider_call_count', execSummary.provider_call_count],
                    ['provider_success_count', counts.providerSuccessCount],
                    ['provider_transport_error_count', execSummary.provider_transport_error_count],
                    ['parse_error_count', counts.parseErrorCount],
                    ['schema_error_count', execSummary.schema_error_count],
                    ['failed_pack_count', counts.failedPackCount],
                    ['provider_empty_response_count', execSummary.provider_empty_response_count],
                    ['pack_count', packCount],
                    ['executed_pack_count', executedPackCount > 0 ? executedPackCount : null],
                    ['planned_pack_count', plannedPackCount > 0 ? plannedPackCount : null],
                    ['skipped_debug_pack_count', skippedDebugPackCount > 0 ? skippedDebugPackCount : null],
                    ['processed_pair_count', execSummary.processed_pair_count],
                    ['created_projection_count', execSummary.created_projection_count],
                    ['no_connection_count', execSummary.no_connection_count],
                    ['unprocessed_pair_count', execSummary.unprocessed_pair_count],
                    ['rejected_item_count', execSummary.rejected_item_count],
                    ['prompt_sent_count', execSummary.prompt_sent_count],
                    ['late_provider_response_ignored', execSummary.late_provider_response_ignored],
                  ]
                  return gridEntries.map(([key, val]) => (
                    val != null && (
                      <div key={String(key)} className="llm-result-count-card">
                        <span className="llm-result-count-label">{t(`llm.resultModal.${key}`)}</span>
                        <span className="llm-result-count-value">{String(val)}</span>
                      </div>
                    )
                  ))
                })()}
              </div>
              <div className="llm-result-provider-audit-note">
                {t('llm.resultModal.providerSuccessNote')}
              </div>
              {auditCounts && auditCounts.parseErrorCount > 0 && auditCounts.providerSuccessCount === 0 && (
                <div className="llm-result-provider-audit llm-result-provider-audit-warning">
                  {t('llm.resultModal.providerSuccessAuditAnomaly')}
                </div>
              )}
              {debugSinglePackEnabled && (
                <div className="llm-result-provider-audit llm-result-provider-audit-info">
                  {t('llm.resultModal.debugSinglePackEnabled', {
                    planned: String(plannedPackCount || '?'),
                  })}
                </div>
              )}
              {debugSinglePackEnabled && providerCallCountForDebug > 1 && (
                <div className="llm-result-provider-audit llm-result-provider-audit-danger">
                  {t('llm.resultModal.debugSinglePackNotEffective')}
                </div>
              )}
              {Boolean(execSummary.fail_fast_triggered) && (
                <div className="llm-result-count-card">
                  <span className="llm-result-count-label">{t('llm.resultModal.fail_fast_triggered')}</span>
                  <span className="llm-result-count-value">{String(execSummary.fail_fast_triggered)}</span>
                </div>
              )}
              {execSummary.remaining_pack_count_skipped != null && Number(execSummary.remaining_pack_count_skipped) > 0 && (
                <div className="llm-result-count-card">
                  <span className="llm-result-count-label">{t('llm.resultModal.remaining_pack_count_skipped')}</span>
                  <span className="llm-result-count-value">{String(execSummary.remaining_pack_count_skipped)}</span>
                </div>
              )}
              {providerAuditMessage && (
                <div className={`llm-result-provider-audit llm-result-provider-audit-${providerAuditTone}`}>
                  {providerAuditMessage}
                </div>
              )}
              <ParseFailureDetails execSummary={execSummary} t={t} />
            </div>
          )}

          {data.recentEvents && data.recentEvents.length > 0 && (
            <WorkflowEventsPanel events={data.recentEvents} t={t} />
          )}

          {data.workflowRunId && (
            <div className="llm-result-section">
              <span className="llm-result-count-label">{t('llm.resultModal.workflowRunId')}</span>
              <code className="llm-result-run-id">{data.workflowRunId}</code>
            </div>
          )}

          {data.substeps && data.substeps.length > 0 && (
            <div className={`llm-result-substep-list${isRunning ? ' llm-extraction-step-list' : ''}`}>
              <div className="llm-result-section-title">{t('llm.resultModal.substeps')}</div>
              {data.substeps.map(step => (
                <div
                  key={step.id}
                  className={`llm-result-substep llm-result-substep-${step.status}${isRunning ? ` llm-extraction-step-item llm-extraction-step-${step.status}` : ''}${step.status === 'running' ? ' llm-extraction-step-running' : ''}`}
                >
                  <span className="llm-result-substep-name">{t(step.label)}</span>
                  <span className="llm-result-substep-status">{SUBSTEP_STATUS_LABELS[step.status] ?? step.status}</span>
                  {step.createdCount != null && step.createdCount > 0 && (
                    <span className="llm-result-substep-count">+{step.createdCount}</span>
                  )}
                  {step.error && (
                    <span className="llm-result-substep-error">
                      {step.error.startsWith('llmExtraction.') ? t(step.error) : step.error}
                    </span>
                  )}
                  {step.warnings?.map(w => (
                    <span key={w} className="llm-result-substep-warning">
                      {w.startsWith('llmExtraction.') ? t(w) : w}
                    </span>
                  ))}
                </div>
              ))}
            </div>
          )}

          {createdEntries.length > 0 && (
            <div className="llm-result-section">
              <div className="llm-result-section-title">{t('llm.resultModal.createdCounts')}</div>
              <div className="llm-result-summary-grid">
                {createdEntries.map(([key, val]) => (
                  <div key={key} className="llm-result-count-card">
                    <span className="llm-result-count-label">{COUNT_LABELS[key] ?? key}</span>
                    <span className="llm-result-count-value">+{val}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {!isRunning && showCircuitBundle && (
            <div className="llm-result-section llm-result-bundle-completion">
              <div className="llm-result-section-title">{t('dataCenter.circuitBundleCompletion')}</div>
              <p className="llm-result-bundle-desc">{t('dataCenter.circuitBundleCompletionDesc')}</p>
              <div className="llm-result-bundle-counts">
                <span>{t('dataCenter.bundleGroupCircuit')}：{circuitCount}</span>
                <span>{t('dataCenter.bundleGroupCircuitStep')}：{stepCount}</span>
                <span>{t('dataCenter.bundleGroupCircuitFunction')}：{functionCount}</span>
              </div>
              <button type="button" className="llm-btn llm-btn-primary" onClick={openCircuitBundle}>
                {t('dataCenter.executeBundleCompletionOneClick')}
              </button>
              <details className="llm-result-bundle-advanced">
                <summary onClick={() => setShowAdvancedCompletion(v => !v)}>
                  {t('dataCenter.bundleAdvancedSingleType')}
                </summary>
                {showAdvancedCompletion && (
                  <p className="llm-result-bundle-advanced-note">{t('dataCenter.bundleAdvancedSingleTypeNote')}</p>
                )}
              </details>
            </div>
          )}

          {data.targets && data.targets.length > 0 && (
            <div className="llm-result-section">
              <div className="llm-result-section-title">{t('llm.resultModal.targets')}</div>
              <ul className="llm-result-target-list">
                {data.targets.map(tgt => <li key={tgt}><code>{tgt}</code></li>)}
              </ul>
            </div>
          )}

          {data.warnings && data.warnings.length > 0 && (
            <details className="llm-result-warning">
              <summary>{t('llm.resultModal.warnings')} ({data.warnings.length})</summary>
              <ul>{data.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </details>
          )}

          {data.errors && data.errors.length > 0 && (
            <details className="llm-result-error">
              <summary>{t('llm.resultModal.errors')} ({data.errors.length})</summary>
              <ul>{data.errors.map((e, i) => (
                <li key={i}>{e.length > 500 ? `${e.slice(0, 500)}…` : e}</li>
              ))}</ul>
            </details>
          )}

          {data.runIds && data.runIds.length > 0 && (
            <div className="llm-result-section">
              <span className="llm-result-count-label">Run ID</span>
              {data.runIds.map(id => (
                <code key={id} className="llm-result-run-id">{id.slice(0, 12)}…</code>
              ))}
            </div>
          )}

          <div className="llm-result-boundary">{t('llm.resultModal.noFinalNoKg')}</div>
        </div>

        <div className="llm-result-modal-footer">
          {!isRunning && onViewMirror && (
            <button type="button" className="llm-btn" onClick={onViewMirror}>
              {t('llm.resultModal.viewMirrorResults')}
            </button>
          )}
          {!isRunning && onOpenDataCenter && (
            <>
              <button type="button" className="llm-btn" onClick={() => onOpenDataCenter('#/data-center?tab=mirror')}>
                {t('llm.resultModal.openDataCenterMirror')}
              </button>
              <button type="button" className="llm-btn" onClick={() => onOpenDataCenter('#/data-center?tab=macro')}>
                {t('llm.resultModal.openDataCenterMacro')}
              </button>
            </>
          )}
          {!isRunning && onViewRuns && (
            <button type="button" className="llm-btn llm-btn-ghost" onClick={onViewRuns}>
              {t('llm.resultModal.viewRuns')}
            </button>
          )}
          {!isRunning && onViewItems && (
            <button type="button" className="llm-btn llm-btn-ghost" onClick={onViewItems}>
              {t('llm.resultModal.viewItems')}
            </button>
          )}
          {isRunning && onMinimize && (
            <button type="button" className="llm-btn" onClick={onMinimize}>
              {t('llm.resultModal.minimize')}
            </button>
          )}
          <button type="button" className="llm-btn llm-btn-primary" onClick={cleanupDone ? onClose : handleClose}>
            {isRunning && !cleanupDone ? t('llm.resultModal.cancelExtract') : t('llm.resultModal.close')}
          </button>
        </div>
      </div>
    </>
  )
}

/** Build modal data from a composite extraction result. */
function mergeExecutionSummary(
  stepSummary?: Record<string, unknown>,
  providerAudit?: Record<string, unknown>,
  resultSummary?: Record<string, unknown>,
): Record<string, unknown> | undefined {
  const merged: Record<string, unknown> = {
    ...(stepSummary ?? {}),
    ...(resultSummary ?? {}),
  }
  const audit = providerAudit
    ?? (resultSummary?.provider_audit as Record<string, unknown> | undefined)
    ?? (stepSummary?.provider_audit as Record<string, unknown> | undefined)
  if (audit) {
    merged.provider_audit = audit
    for (const [key, val] of Object.entries(audit)) {
      if (key === 'errors' || key === 'pack_summaries') continue
      if (val != null) merged[key] = val
    }
    if (Array.isArray(audit.pack_summaries) && audit.pack_summaries.length > 0) {
      merged.pack_summaries = audit.pack_summaries
    }
  }
  return Object.keys(merged).length > 0 ? merged : undefined
}

export function buildCompositeModalData(
  taskId: string,
  taskLabel: string,
  provider: string,
  modelName: string,
  dryRun: boolean,
  selectedCount: number,
  result: import('../services/compositeExtractionRunner').CompositeExtractionResult,
): ExtractionResultModalData {
  const pairCount = taskId.includes('connection')
    ? selectedCount * (selectedCount - 1) / 2
    : undefined

  const createdCounts: Record<string, number> = {}
  const runIds: string[] = []
  const errors: string[] = []

  for (const step of result.substeps) {
    if (step.runId) runIds.push(step.runId)
    if (step.error) errors.push(step.error)
    if (step.createdCount != null && step.createdCount > 0) {
      if (step.id === 'connection') createdCounts.connections = (createdCounts.connections ?? 0) + step.createdCount
      else if (step.id === 'projection_function') createdCounts.projection_functions = (createdCounts.projection_functions ?? 0) + step.createdCount
      else if (step.id === 'circuit') createdCounts.circuits = (createdCounts.circuits ?? 0) + step.createdCount
      else if (step.id === 'circuit_steps') createdCounts.circuit_steps = (createdCounts.circuit_steps ?? 0) + step.createdCount
      else if (step.id === 'circuit_functions') createdCounts.circuit_functions = (createdCounts.circuit_functions ?? 0) + step.createdCount
      else if (step.id === 'triple') createdCounts.triples = (createdCounts.triples ?? 0) + step.createdCount
    }
  }

  const substeps = result.substeps.map(step => ({ ...step }))
  for (const target of result.createdTargets ?? []) {
    const substepId =
      target.target_type === 'circuit' ? 'circuit'
      : target.target_type === 'circuit_step' ? 'circuit_steps'
      : target.target_type === 'circuit_function' ? 'circuit_functions'
      : null
    if (!substepId) continue
    const step = substeps.find(s => s.id === substepId)
    if (!step) continue
    if (target.ids?.length) step.createdIds = target.ids
    if ((target.count ?? 0) > 0) step.createdCount = target.count
  }

  const targets: string[] = []
  if (createdCounts.connections) targets.push('mirror_region_connections')
  if (createdCounts.projection_functions) targets.push('mirror_projection_functions')
  if (createdCounts.circuits) targets.push('mirror_region_circuits')
  if (createdCounts.circuit_steps) targets.push('mirror_circuit_steps')
  if (createdCounts.circuit_functions) targets.push('mirror_circuit_functions')
  if (createdCounts.triples) targets.push('mirror_kg_triples')
  if (runIds.length) targets.push('llm_extraction_runs', 'llm_extraction_items')
  if (result.workflowRunId) targets.push('llm_composite_workflow_runs', 'llm_composite_workflow_steps')

  const connStep = substeps.find(s => s.id === 'connection')
  const executionSummary = mergeExecutionSummary(
    connStep?.executionSummary as Record<string, unknown> | undefined,
    result.providerAudit,
    result.resultSummary,
  )
  const semanticOutcome =
    result.displayStatus
    ?? result.outcome
    ?? result.semanticStatus
    ?? (executionSummary?.display_status as string | undefined)
    ?? (executionSummary?.outcome as string | undefined)
    ?? (result.status === 'no_edges' ? 'succeeded_no_edges' : undefined)
  const terminalStatus = dryRun && result.status === 'succeeded'
    ? 'dry_run'
    : (semanticOutcome ?? result.status)
  const providerAuditDisplay = resolveProviderAudit(
    dryRun,
    executionSummary,
    terminalStatus,
    undefined,
    connStep?.status,
  )

  return {
    status: dryRun && result.status === 'succeeded' ? 'dry_run' : result.status,
    taskId,
    taskLabel,
    provider,
    modelName,
    dryRun,
    selectedCount,
    pairCount,
    substeps: substeps,
    createdCounts,
    warnings: result.warnings,
    errors: errors.length ? errors : undefined,
    runIds: runIds.length ? runIds : undefined,
    workflowRunId: result.workflowRunId,
    serverSide: result.serverSide,
    targets: targets.length ? targets : undefined,
    executionSummary,
    providerAudit: (executionSummary?.provider_audit as Record<string, unknown> | undefined)
      ?? result.providerAudit,
    resultSummary: result.resultSummary,
    diagnostics: result.diagnostics,
    providerAuditMessage: providerAuditDisplay.message,
    providerAuditTone: providerAuditDisplay.tone,
    recentEvents: result.recentEvents,
    workflowOutcome: semanticOutcome,
  }
}
