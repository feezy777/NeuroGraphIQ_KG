/**
 * Composite extraction runner — prefers server-side composite workflow API,
 * with frontend-only orchestration as fallback when the endpoint is unavailable.
 *
 * Rules:
 * - Backend composite workflow is the primary path when available.
 * - If backend returns 404, fall back to existing single-step frontend orchestration.
 * - If a fallback endpoint is missing, substep = skipped + warning (never fake success).
 * - dry_run=true → no Mirror writes.
 * - Never writes final_* or kg_*.
 */

import {
  runCompositeWorkflow,
  startCompositeWorkflow,
  getCompositeWorkflowRun,
  runSameGranularityConnectionExtraction,
  runSameGranularityCircuitExtraction,
  runCircuitToStepsExtraction,
  runCircuitToFunctionsExtraction,
  runProjectionToFunctionsExtraction,
  consolidateMirrorTriples,
  listMirrorConnections,
  listMirrorCircuits,
  type CompositeWorkflowRunRequest,
  type CompositeWorkflowRunResponse,
  type CompositeWorkflowRunRead,
  type CompositeWorkflowType,
  type CompositeWorkflowCreatedTarget,
  type SameGranularityConnectionExtractionRequest,
  type SameGranularityCircuitExtractionRequest,
} from '../../../api/endpoints'
import type { LlmWorkflowEvent } from '../../../api/endpoints'
import { ApiError } from '../../../api/client'
import { API_MAX_LIMIT } from '../llmTableLimits'
import { logCompositeProgressSnapshot, logWorkflowEvents } from './llmExtractionLogBridge'

// ── Candidate count minimums (backend min_length constraints) ─────────────────
// backend/app/schemas/llm_extraction.py — max_length has been removed; only min enforced.
// Large candidate counts (>50) produce a non-blocking warning, not an error.
const LARGE_CANDIDATE_WARNING_THRESHOLD = 50
const LARGE_PAIR_COUNT_WARNING_THRESHOLD = 200

const CANDIDATE_MINIMUMS: Record<string, number> = {
  composite_connection_with_function:        2,
  composite_circuit_with_function_and_steps: 2,
  composite_triple_generation:               0,
}

// ── Types ─────────────────────────────────────────────────────────────────────

export type CompositeExtractionTaskId =
  | 'composite_connection_with_function'
  | 'composite_circuit_with_function_and_steps'
  | 'composite_triple_generation'

export interface CompositeExtractionContext {
  provider: string
  modelName: string
  dryRun: boolean
  selectedCandidateIds: string[]
  debugSinglePack?: boolean
  debugMaxPacks?: number | null
  scope: {
    batch_id?: string
    resource_id?: string
    source_atlas?: string
    granularity_level?: string
    granularity_family?: string
  }
}

export type SubstepStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'skipped'
  | 'skipped_no_projection'
  | 'skipped_dependency_failed'
  | 'cancelled'
  | 'failed_validation'

export interface CompositeSubstepResult {
  id: string
  label: string
  status: SubstepStatus
  runId?: string
  createdCount?: number
  createdIds?: string[]
  warnings?: string[]
  error?: string
  executionSummary?: Record<string, unknown>
}

export type CompositeExtractionStatus =
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

export interface CompositeExtractionResult {
  taskId: CompositeExtractionTaskId
  status: CompositeExtractionStatus
  substeps: CompositeSubstepResult[]
  warnings: string[]
  validationError?: string
  workflowRunId?: string
  serverSide?: boolean
  createdTargets?: CompositeWorkflowCreatedTarget[]
  recentEvents?: LlmWorkflowEvent[]
  outcome?: string
  displayStatus?: string
  semanticStatus?: string
  resultSummary?: Record<string, unknown>
  providerAudit?: Record<string, unknown>
  diagnostics?: Array<Record<string, unknown>>
}

export interface CompositeProgressMeta {
  phase: 'starting' | 'running' | 'complete'
  workflowRunId?: string
  progressPercent?: number
  indeterminate?: boolean
  workflowStatus?: string
  workflowOutcome?: string
  elapsedMs?: number
  recentEvents?: LlmWorkflowEvent[]
  resultSummary?: Record<string, unknown>
  providerAudit?: Record<string, unknown>
  diagnostics?: Array<Record<string, unknown>>
}

export interface CompositeRunCallbacks {
  onSubstepStart: (id: string) => void
  onSubstepComplete: (result: CompositeSubstepResult) => void
  onProgress: (substeps: CompositeSubstepResult[], meta?: CompositeProgressMeta) => void
}

// ── Candidate count validation ────────────────────────────────────────────────

function buildValidationFailedResult(
  taskId: CompositeExtractionTaskId,
  substepDefs: Array<{ id: string; label: string }>,
  message: string,
): CompositeExtractionResult {
  const [first, ...rest] = substepDefs.map(s => makeSubstepDef(s.id, s.label))
  const substeps: CompositeSubstepResult[] = [
    { ...first, status: 'failed_validation', error: message },
    ...rest.map(s => ({ ...s, status: 'skipped' as SubstepStatus, error: '前端校验失败，已跳过该子步骤。' })),
  ]
  return {
    taskId,
    status: 'failed_validation',
    substeps,
    warnings: [message],
    validationError: message,
  }
}

// ── Composite runner ──────────────────────────────────────────────────────────

function makeSubstepDef(id: string, label: string): CompositeSubstepResult {
  return { id, label, status: 'pending' }
}

function makeSubstep(id: string, label: string): CompositeSubstepResult {
  return { id, label, status: 'pending' }
}

function overallStatus(substeps: CompositeSubstepResult[]): CompositeExtractionResult['status'] {
  const hasFailure = substeps.some(s => s.status === 'failed')
  const hasSkipped = substeps.some(s => s.status === 'skipped')
  const hasSuccess = substeps.some(s => s.status === 'succeeded')
  if (hasFailure && !hasSuccess) return 'failed'
  if (hasFailure || hasSkipped) return 'partially_succeeded'
  return 'succeeded'
}

// ── Task: composite_connection_with_function ──────────────────────────────────
// Step A: same-granularity connection extraction
// Step B: projection-to-functions (using connection IDs from scope)

async function runConnectionWithFunction(
  ctx: CompositeExtractionContext,
  cb: CompositeRunCallbacks,
): Promise<CompositeExtractionResult> {
  const taskId: CompositeExtractionTaskId = 'composite_connection_with_function'
  const substepDefs = [
    { id: 'connection', label: 'llm.composite.substepConnection' },
    { id: 'projection_function', label: 'llm.composite.substepProjectionFunction' },
  ]

  const minRequired = CANDIDATE_MINIMUMS[taskId] ?? 1
  const n = ctx.selectedCandidateIds.length
  if (n < minRequired) {
    const msg = `连接提取至少需要 ${minRequired} 个候选脑区，当前只选择了 ${n} 个。`
    const result = buildValidationFailedResult(taskId, substepDefs, msg)
    cb.onProgress([...result.substeps])
    return result
  }

  const substeps: CompositeSubstepResult[] = [
    makeSubstep('connection', 'llm.composite.substepConnection'),
    makeSubstep('projection_function', 'llm.composite.substepProjectionFunction'),
  ]
  cb.onProgress([...substeps])

  const warnings: string[] = []

  if (n > LARGE_CANDIDATE_WARNING_THRESHOLD || (n * (n - 1) / 2) > LARGE_PAIR_COUNT_WARNING_THRESHOLD) {
    const pairCount = n * (n - 1) / 2
    if (pairCount > LARGE_PAIR_COUNT_WARNING_THRESHOLD) {
      warnings.push(`当前将形成 ${pairCount} 个候选连接 pair。系统不会截断 pair，也不会自动分批，可能导致 prompt 较大或运行时间较长。`)
    }
    if (n > LARGE_CANDIDATE_WARNING_THRESHOLD) {
      warnings.push(`当前选择了 ${n} 个候选脑区，模型输入、费用和运行时间可能明显增加。系统不会自动截断或分批，请确认继续。`)
    }
  }

  // ── Step A: connection extraction ─────────────────────────────────────────
  substeps[0] = { ...substeps[0], status: 'running' }
  cb.onSubstepStart('connection')
  cb.onProgress([...substeps])

  let connectionRunId: string | undefined
  let connectionOk = false

  try {
    const payload: SameGranularityConnectionExtractionRequest = {
      provider: ctx.provider,
      model_name: ctx.modelName || undefined,
      candidate_ids: ctx.selectedCandidateIds,
      scope: ctx.scope,
      dry_run: ctx.dryRun,
      create_mirror_records: true,
      create_triples: false,
      create_evidence: true,
    }
    const res = await runSameGranularityConnectionExtraction(payload)
    connectionRunId = res.run_id ?? undefined
    connectionOk = true
    substeps[0] = {
      ...substeps[0],
      status: 'succeeded',
      runId: connectionRunId,
      createdCount: res.mirror_connection_created_count ?? 0,
      warnings: res.warnings ?? [],
    }
    if (res.warnings?.length) warnings.push(...res.warnings)
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    substeps[0] = { ...substeps[0], status: 'failed', error: msg }
    cb.onSubstepComplete(substeps[0])
    cb.onProgress([...substeps])
    // Step A failed → skip Step B
    substeps[1] = {
      ...substeps[1],
      status: 'skipped',
      error: 'Step A (connection extraction) failed — skipping projection function extraction.',
    }
    cb.onSubstepComplete(substeps[1])
    cb.onProgress([...substeps])
    return {
      taskId,
      status: 'failed',
      substeps,
      warnings,
    }
  }

  cb.onSubstepComplete(substeps[0])
  cb.onProgress([...substeps])

  // ── Step B: projection → functions ────────────────────────────────────────
  substeps[1] = { ...substeps[1], status: 'running' }
  cb.onSubstepStart('projection_function')
  cb.onProgress([...substeps])

  try {
    // Fetch recent connections from scope to get projection IDs
    const scopeFilter = {
      ...ctx.scope,
      limit: API_MAX_LIMIT,
    }
    const connData = await listMirrorConnections(scopeFilter)
    const projectionIds = (connData.items ?? []).map(c => c.id)

    if (projectionIds.length === 0) {
      const warn = 'No mirror connections found in scope — skipping projection_to_functions.'
      warnings.push(warn)
      substeps[1] = { ...substeps[1], status: 'skipped', warnings: [warn] }
    } else {
      const res = await runProjectionToFunctionsExtraction({
        provider: ctx.provider,
        model_name: ctx.modelName || undefined,
        projection_ids: projectionIds,
        dry_run: ctx.dryRun,
        create_mirror_records: true,
        create_triples: false,
        create_evidence: true,
        include_circuit_context: true,
        include_region_context: true,
      })
      substeps[1] = {
        ...substeps[1],
        status: 'succeeded',
        runId: res.run_id,
        createdCount: res.mirror_projection_function_created_count ?? 0,
        warnings: res.warnings ?? [],
      }
      if (res.warnings?.length) warnings.push(...res.warnings)
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    substeps[1] = { ...substeps[1], status: 'failed', error: msg }
  }

  cb.onSubstepComplete(substeps[1])
  cb.onProgress([...substeps])

  return {
    taskId,
    status: overallStatus(substeps),
    substeps,
    warnings,
  }
}

// ── Task: composite_circuit_with_function_and_steps ───────────────────────────
// Step A: circuit extraction
// Step B: circuit_to_steps (loop per circuit)
// Step C: circuit_to_functions (SKIPPED — no backend endpoint)

async function runCircuitWithFunctionAndSteps(
  ctx: CompositeExtractionContext,
  cb: CompositeRunCallbacks,
): Promise<CompositeExtractionResult> {
  const taskId: CompositeExtractionTaskId = 'composite_circuit_with_function_and_steps'
  const substepDefs = [
    { id: 'circuit', label: 'llm.composite.substepCircuit' },
    { id: 'circuit_steps', label: 'llm.composite.substepCircuitStep' },
    { id: 'circuit_functions', label: 'llm.composite.substepCircuitFunction' },
  ]

  const minRequired = CANDIDATE_MINIMUMS[taskId] ?? 1
  const n = ctx.selectedCandidateIds.length
  if (n < minRequired) {
    const msg = `回路提取至少需要 ${minRequired} 个候选脑区，当前只选择了 ${n} 个。`
    const result = buildValidationFailedResult(taskId, substepDefs, msg)
    cb.onProgress([...result.substeps])
    return result
  }

  const substeps: CompositeSubstepResult[] = [
    makeSubstep('circuit', 'llm.composite.substepCircuit'),
    makeSubstep('circuit_steps', 'llm.composite.substepCircuitStep'),
    makeSubstep('circuit_functions', 'llm.composite.substepCircuitFunction'),
  ]
  cb.onProgress([...substeps])

  const warnings: string[] = []

  if (n > LARGE_CANDIDATE_WARNING_THRESHOLD) {
    warnings.push(`当前选择了 ${n} 个候选脑区，模型输入和运行时间可能明显增加。该操作不会自动分批，请确认是否继续。`)
  }

  // ── Step A: circuit extraction ────────────────────────────────────────────
  substeps[0] = { ...substeps[0], status: 'running' }
  cb.onSubstepStart('circuit')
  cb.onProgress([...substeps])

  let circuitOk = false

  try {
    const payload: SameGranularityCircuitExtractionRequest = {
      provider: ctx.provider,
      model_name: ctx.modelName || undefined,
      candidate_ids: ctx.selectedCandidateIds,
      scope: ctx.scope,
      dry_run: ctx.dryRun,
      create_mirror_records: true,
      create_triples: false,
      create_evidence: true,
    }
    const res = await runSameGranularityCircuitExtraction(payload)
    circuitOk = true
    substeps[0] = {
      ...substeps[0],
      status: 'succeeded',
      runId: res.run_id ?? undefined,
      createdCount: res.mirror_circuit_created_count ?? 0,
      warnings: res.warnings ?? [],
    }
    if (res.warnings?.length) warnings.push(...res.warnings)
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    substeps[0] = { ...substeps[0], status: 'failed', error: msg }
    cb.onSubstepComplete(substeps[0])
    cb.onProgress([...substeps])
    // Skip B and C
    for (let i = 1; i <= 2; i++) {
      substeps[i] = { ...substeps[i], status: 'skipped', error: 'Step A (circuit) failed.' }
      cb.onSubstepComplete(substeps[i])
    }
    cb.onProgress([...substeps])
    return { taskId, status: 'failed', substeps, warnings }
  }

  cb.onSubstepComplete(substeps[0])
  cb.onProgress([...substeps])

  // ── Step B: circuit → steps (loop per circuit) ────────────────────────────
  substeps[1] = { ...substeps[1], status: 'running' }
  cb.onSubstepStart('circuit_steps')
  cb.onProgress([...substeps])

  try {
    const circuitData = await listMirrorCircuits({ ...ctx.scope, limit: API_MAX_LIMIT })
    const circuits = circuitData.items ?? []

    if (circuits.length === 0) {
      const warn = 'No mirror circuits found in scope — skipping circuit_to_steps.'
      warnings.push(warn)
      substeps[1] = { ...substeps[1], status: 'skipped', warnings: [warn] }
    } else {
      let totalStepsCreated = 0
      const stepWarnings: string[] = []
      const stepErrors: string[] = []

      for (const circuit of circuits) {
        try {
          const res = await runCircuitToStepsExtraction({
            provider: ctx.provider,
            model_name: ctx.modelName || undefined,
            circuit_id: circuit.id,
            dry_run: ctx.dryRun,
            create_mirror_records: true,
            include_circuit_regions: true,
          })
          totalStepsCreated += res.mirror_step_created_count ?? 0
          if (res.warnings?.length) stepWarnings.push(...res.warnings)
        } catch (e) {
          stepErrors.push(`circuit ${circuit.id.slice(0, 8)}: ${e instanceof Error ? e.message : String(e)}`)
        }
      }

      if (stepErrors.length > 0 && totalStepsCreated === 0) {
        substeps[1] = {
          ...substeps[1],
          status: 'failed',
          error: stepErrors.join('; '),
          warnings: stepWarnings,
        }
      } else {
        if (stepErrors.length > 0) stepWarnings.push(...stepErrors)
        substeps[1] = {
          ...substeps[1],
          status: stepErrors.length > 0 ? 'failed' : 'succeeded',
          createdCount: totalStepsCreated,
          warnings: stepWarnings,
        }
        warnings.push(...stepWarnings)
      }
    }
  } catch (e) {
    substeps[1] = { ...substeps[1], status: 'failed', error: e instanceof Error ? e.message : String(e) }
  }

  cb.onSubstepComplete(substeps[1])
  cb.onProgress([...substeps])

// Step C: circuit → functions (uses circuit ids from Step A run)

  substeps[2] = { ...substeps[2], status: 'running' }
  cb.onSubstepStart('circuit_functions')
  cb.onProgress([...substeps])

  try {
    let circuitIds: string[] = []
    if (substeps[0].runId) {
      const circuitData = await listMirrorCircuits({ llm_run_id: substeps[0].runId, limit: API_MAX_LIMIT })
      circuitIds = (circuitData.items ?? []).map(c => c.id)
    }

    if (circuitIds.length === 0) {
      const warn = 'No circuit ids from Step A — skipping circuit_to_functions.'
      warnings.push(warn)
      substeps[2] = { ...substeps[2], status: 'skipped', warnings: [warn] }
    } else {
      const res = await runCircuitToFunctionsExtraction({
        provider: ctx.provider,
        model_name: ctx.modelName || undefined,
        circuit_ids: circuitIds,
        batch_id: ctx.scope.batch_id,
        resource_id: ctx.scope.resource_id,
        dry_run: ctx.dryRun,
      })
      const fnWarnings = [...(res.warnings ?? [])]
      if (ctx.dryRun) {
        fnWarnings.push('dry_run=true — circuit functions were not written to mirror_circuit_functions.')
      }
      substeps[2] = {
        ...substeps[2],
        status: res.status === 'failed' ? 'failed' : 'succeeded',
        createdCount: res.created_count ?? 0,
        createdIds: res.created_ids,
        warnings: fnWarnings,
      }
      warnings.push(...fnWarnings)
    }
  } catch (e) {
    const msg = e instanceof ApiError
      ? (typeof e.meta?.responseBody === 'object'
        && e.meta.responseBody !== null
        && (e.meta.responseBody as { detail?: { code?: string } }).detail?.code === 'MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED')
        ? 'llmExtraction.circuitFunctionsMigrationMissing'
        : e.message
      : e instanceof Error ? e.message : String(e)
    substeps[2] = {
      ...substeps[2],
      status: 'failed',
      error: msg.startsWith('llmExtraction.') ? msg : msg,
      warnings: msg.startsWith('llmExtraction.') ? [msg] : undefined,
    }
    if (!msg.startsWith('llmExtraction.')) {
      warnings.push(msg)
    }
  }

  cb.onSubstepComplete(substeps[2])
  cb.onProgress([...substeps])

  return {
    taskId,
    status: overallStatus(substeps),
    substeps,
    warnings,
  }
}

// ── Task: composite_triple_generation ─────────────────────────────────────────
// Uses consolidateMirrorTriples (existing endpoint)

async function runTripleGeneration(
  ctx: CompositeExtractionContext,
  cb: CompositeRunCallbacks,
): Promise<CompositeExtractionResult> {
  const taskId: CompositeExtractionTaskId = 'composite_triple_generation'
  const substeps: CompositeSubstepResult[] = [
    makeSubstep('triple', 'llm.composite.substepTriple'),
  ]
  cb.onProgress([...substeps])

  const warnings: string[] = []

  substeps[0] = { ...substeps[0], status: 'running' }
  cb.onSubstepStart('triple')
  cb.onProgress([...substeps])

  try {
    const res = await consolidateMirrorTriples({
      source_types: ['connection', 'function', 'circuit'],
      scope: {
        batch_id: ctx.scope.batch_id,
        resource_id: ctx.scope.resource_id,
        source_atlas: ctx.scope.source_atlas,
        granularity_level: ctx.scope.granularity_level,
        granularity_family: ctx.scope.granularity_family,
      },
      dry_run: ctx.dryRun,
      limit: 1000,
    })
    substeps[0] = {
      ...substeps[0],
      status: 'succeeded',
      createdCount: res.created_triple_count ?? 0,
      warnings: res.warnings ?? [],
    }
    if (res.warnings?.length) warnings.push(...res.warnings)
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    substeps[0] = { ...substeps[0], status: 'failed', error: msg }
  }

  cb.onSubstepComplete(substeps[0])
  cb.onProgress([...substeps])

  return {
    taskId,
    status: overallStatus(substeps),
    substeps,
    warnings,
  }
}

// ── Backend composite workflow mapping ────────────────────────────────────────

const TASK_TO_WORKFLOW_TYPE: Record<CompositeExtractionTaskId, CompositeWorkflowType> = {
  composite_connection_with_function: 'connection_with_function',
  composite_circuit_with_function_and_steps: 'circuit_with_function_steps',
  composite_triple_generation: 'triple_generation',
}

const STEP_KEY_TO_SUBSTEP: Record<string, { id: string; label: string }> = {
  extract_connections: { id: 'connection', label: 'llm.composite.substepConnection' },
  extract_projection_functions: { id: 'projection_function', label: 'llm.composite.substepProjectionFunction' },
  extract_circuits: { id: 'circuit', label: 'llm.composite.substepCircuit' },
  extract_circuit_steps: { id: 'circuit_steps', label: 'llm.composite.substepCircuitStep' },
  extract_circuit_functions: { id: 'circuit_functions', label: 'llm.composite.substepCircuitFunction' },
  generate_triples: { id: 'triple', label: 'llm.composite.substepTriple' },
}

const POLL_INTERVAL_MS = 1200

const TERMINAL_WORKFLOW_STATUSES = new Set([
  'succeeded',
  'partially_succeeded',
  'failed',
  'failed_provider_not_called',
  'failed_provider_empty_response',
  'failed_parse_error',
  'failed_no_output',
  'no_edges',
  'succeeded_no_edges',
  'dry_run',
  'cancelled',
  'cleanup_done',
  'cleanup_failed',
])

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function mapServerStepsFromRead(detail: CompositeWorkflowRunRead): CompositeSubstepResult[] {
  const steps = detail.steps ?? []
  const providerAudit = (detail.provider_audit ?? detail.result_summary?.provider_audit) as
    | Record<string, unknown>
    | undefined
  const substeps = steps.map(step => {
    const meta = STEP_KEY_TO_SUBSTEP[step.step_key] ?? { id: step.step_key, label: step.step_key }
    const created = step.created_counts ?? {}
    const createdTotal = Object.values(created).reduce((a, b) => a + (typeof b === 'number' ? b : 0), 0)
    let executionSummary = step.execution_summary as Record<string, unknown> | undefined
    if (step.step_key === 'extract_connections' && providerAudit) {
      executionSummary = {
        ...(executionSummary ?? {}),
        ...providerAudit,
        pack_summaries: providerAudit.pack_summaries ?? executionSummary?.pack_summaries,
        provider_audit: providerAudit,
      }
    }
    return {
      id: meta.id,
      label: meta.label,
      status: step.status,
      runId: step.llm_run_id ?? undefined,
      createdCount: createdTotal > 0 ? createdTotal : undefined,
      warnings: step.warnings,
      error: step.errors?.[0],
      executionSummary,
    }
  })
  const fromSummary = detail.result_summary?.created_targets as CompositeWorkflowCreatedTarget[] | undefined
  return applyCreatedTargetsToSubsteps(substeps, fromSummary)
}

function resolveWorkflowSemanticStatus(
  detail: Pick<CompositeWorkflowRunRead, 'status' | 'outcome' | 'display_status' | 'semantic_status' | 'result_summary'>,
): string {
  return (
    detail.display_status
    ?? detail.outcome
    ?? detail.semantic_status
    ?? (detail.result_summary?.display_status as string | undefined)
    ?? (detail.result_summary?.outcome as string | undefined)
    ?? detail.status
  )
}

function readToRunResponse(detail: CompositeWorkflowRunRead): CompositeWorkflowRunResponse {
  return {
    workflow_run_id: detail.id,
    workflow_type: detail.workflow_type,
    status: detail.status,
    dry_run: detail.dry_run,
    candidate_count: detail.candidate_count,
    pair_count: detail.pair_count,
    steps: detail.steps ?? [],
    progress_percent: detail.progress_percent,
    result_summary: detail.result_summary,
    created_targets: (detail.result_summary?.created_targets ?? []) as CompositeWorkflowCreatedTarget[],
    warnings: detail.warnings,
    errors: detail.errors,
    started_at: detail.started_at,
    completed_at: detail.completed_at,
    created_at: detail.created_at,
    recent_events: detail.recent_events,
    outcome: detail.outcome,
    display_status: detail.display_status,
    semantic_status: detail.semantic_status,
  }
}

function formatValidation422Message(detail: unknown): string | null {
  if (!Array.isArray(detail)) return null
  for (const item of detail) {
    if (!item || typeof item !== 'object') continue
    const loc = (item as { loc?: unknown }).loc
    const field = Array.isArray(loc) ? loc[loc.length - 1] : null
    if (field === 'resource_id' || field === 'batch_id') {
      const input = (item as { input?: unknown }).input
      if (input === '' || input === null || input === undefined) {
        return `请求参数错误：${String(field)} 为空字符串。若未选择对应资源，应留空而不是发送空字符串。`
      }
      return `请求参数错误：${String(field)} 不是合法 UUID。请检查 scope 配置或刷新页面后重试。`
    }
  }
  return '请求参数错误：composite workflow 请求校验失败。请检查 batch_id / resource_id / candidate_ids 格式。'
}

function formatCompositeWorkflowError(error: unknown): string {
  const rawMsg = error instanceof Error ? error.message : String(error)
  const haystack = rawMsg.toLowerCase()

  if (haystack.includes('too_long') && haystack.includes('candidate_ids')) {
    return '后端仍存在 candidate_ids 上限校验或服务未重启。请重启后端并确认 schema 已移除 max_length=50。'
  }
  if (haystack.includes('too_many_candidate_pairs') || haystack.includes('too many candidate pairs')) {
    return '后端仍存在 pair_count 阻断逻辑。请确认 connection service 不再因 pair 数量返回 400。'
  }
  if (haystack.includes('unexpected keyword argument') || haystack.includes('unsupported keyword')) {
    return '后端 composite workflow 调用单步服务参数不匹配。请查看后端日志中的 TypeError。'
  }
  if (error instanceof ApiError && error.status === 404) {
    return '后端进度接口未注册（/composite-workflows/start）。将尝试回退同步 /run。'
  }

  if (error instanceof ApiError) {
    const body = error.meta?.responseBody
    if (body && typeof body === 'object' && body !== null) {
      const detail = (body as { detail?: unknown }).detail
      if (error.status === 422) {
        const validationMsg = formatValidation422Message(detail)
        if (validationMsg) return validationMsg
      }
      if (typeof detail === 'string') {
        if (detail.toLowerCase().includes('most 50 items') || detail.toLowerCase().includes('max_length')) {
          return '后端仍存在 candidate_ids 上限校验或服务未重启。'
        }
        if (detail.toLowerCase().includes('too many candidate pairs')) {
          return '后端仍存在 pair_count 阻断逻辑。'
        }
      }
      if (detail && typeof detail === 'object' && detail !== null) {
        const d = detail as Record<string, unknown>
        if (d.code === 'TOO_MANY_CANDIDATE_PAIRS') {
          return '后端仍存在 pair_count 阻断逻辑。'
        }
        const parts = [
          d.code ? String(d.code) : null,
          d.message ? String(d.message) : null,
          d.workflow_run_id ? `workflow_run_id=${String(d.workflow_run_id)}` : null,
          d.hint ? String(d.hint) : null,
        ].filter(Boolean)
        if (parts.length) return parts.join(' — ')
      }
    }
    if (error.status === 500) {
      return '后端 composite workflow 内部异常，请查看 workflow run 或后端日志。'
    }
  }
  if (rawMsg === 'Internal Server Error' || rawMsg.includes('HTTP 500')) {
    return '后端 composite workflow 内部异常，请查看 workflow run 或后端日志。'
  }
  return rawMsg.length > 280 ? `${rawMsg.slice(0, 280)}…` : rawMsg
}

async function pollCompositeWorkflowRun(
  workflowRunId: string,
  cb: CompositeRunCallbacks,
  startedAt: number,
  initialSubsteps: CompositeSubstepResult[],
  signal?: AbortSignal,
): Promise<CompositeWorkflowRunRead> {
  let substeps = initialSubsteps
  while (true) {
    if (signal?.aborted) {
      // Caller cancelled — return the last known detail as best-effort
      const detail = await getCompositeWorkflowRun(workflowRunId).catch(() => null)
      if (detail) return detail
      throw new DOMException('Polling aborted', 'AbortError')
    }
    const detail = await getCompositeWorkflowRun(workflowRunId)
    substeps = mapServerStepsFromRead(detail)
    logWorkflowEvents(detail.recent_events)
    logCompositeProgressSnapshot(substeps, {
      phase: TERMINAL_WORKFLOW_STATUSES.has(detail.status) ? 'complete' : 'running',
      workflowRunId,
      progressPercent: detail.progress_percent,
      workflowStatus: detail.status,
      elapsedMs: Date.now() - startedAt,
      recentEvents: detail.recent_events,
    }, {
      workflowWarnings: detail.warnings,
      workflowErrors: detail.errors,
      workflowRunId,
    })
    cb.onProgress(substeps, {
      phase: TERMINAL_WORKFLOW_STATUSES.has(detail.status) ? 'complete' : 'running',
      workflowRunId,
      progressPercent: detail.progress_percent,
      workflowStatus: detail.status,
      workflowOutcome: resolveWorkflowSemanticStatus(detail),
      elapsedMs: Date.now() - startedAt,
      recentEvents: detail.recent_events,
      resultSummary: detail.result_summary,
      providerAudit: (detail.provider_audit ?? detail.result_summary?.provider_audit) as Record<string, unknown> | undefined,
      diagnostics: detail.diagnostics,
    })
    if (TERMINAL_WORKFLOW_STATUSES.has(detail.status)) {
      return detail
    }
    await sleep(POLL_INTERVAL_MS)
  }
}

function mapServerStatus(
  status: CompositeWorkflowRunResponse['status'],
  dryRun: boolean,
  semanticStatus?: string,
): CompositeExtractionStatus {
  const semantic = semanticStatus ?? status
  if (status === 'dry_run') return 'dry_run'
  if (dryRun && status === 'succeeded') return 'dry_run'
  if (status === 'partially_succeeded') return 'partially_succeeded'
  if (status === 'cancelling' || status === 'cancelled') return 'cancelled'
  if (status === 'cleanup_in_progress' || status === 'cleanup_done') return 'cleanup_done'
  if (status === 'cleanup_failed') return 'cleanup_failed'
  if (semantic === 'succeeded_no_edges' || status === 'no_edges' || status === 'succeeded_no_edges') return 'no_edges'
  if (status === 'failed_provider_not_called') return 'failed_provider_not_called'
  if (
    status === 'failed'
    || status === 'failed_provider_empty_response'
    || status === 'failed_parse_error'
    || status === 'failed_no_output'
  ) return 'failed'
  if (status === 'succeeded') return 'succeeded'
  return 'failed'
}

function applyCreatedTargetsToSubsteps(
  substeps: CompositeSubstepResult[],
  createdTargets?: CompositeWorkflowCreatedTarget[],
): CompositeSubstepResult[] {
  if (!createdTargets?.length) return substeps
  const next = substeps.map(s => ({ ...s }))
  const bySubstepId: Record<string, string> = {
    circuit: 'circuit',
    circuit_step: 'circuit_steps',
    circuit_function: 'circuit_functions',
  }
  for (const target of createdTargets) {
    const substepId = bySubstepId[target.target_type]
    if (!substepId) continue
    const step = next.find(s => s.id === substepId)
    if (!step) continue
    if (target.ids?.length) {
      step.createdIds = target.ids
    }
    if (typeof target.count === 'number' && target.count > 0) {
      step.createdCount = target.count
    }
  }
  return next
}

function mapServerSteps(response: CompositeWorkflowRunResponse): CompositeSubstepResult[] {
  const substeps = response.steps.map(step => {
    const meta = STEP_KEY_TO_SUBSTEP[step.step_key] ?? { id: step.step_key, label: step.step_key }
    const created = step.created_counts ?? {}
    const createdTotal = Object.values(created).reduce((a, b) => a + (typeof b === 'number' ? b : 0), 0)
    return {
      id: meta.id,
      label: meta.label,
      status: step.status,
      runId: step.llm_run_id ?? undefined,
      createdCount: createdTotal > 0 ? createdTotal : undefined,
      warnings: step.warnings,
      error: step.errors?.[0],
      executionSummary: step.execution_summary,
    }
  })
  const fromSummary = (response.result_summary?.created_targets ?? response.created_targets) as
    | CompositeWorkflowCreatedTarget[]
    | undefined
  return applyCreatedTargetsToSubsteps(substeps, fromSummary)
}

function buildCompositeRequest(
  taskId: CompositeExtractionTaskId,
  ctx: CompositeExtractionContext,
): CompositeWorkflowRunRequest {
  const debugSinglePack = ctx.debugSinglePack ?? false
  return {
    workflow_type: TASK_TO_WORKFLOW_TYPE[taskId],
    provider: ctx.provider,
    model_name: ctx.modelName || undefined,
    dry_run: ctx.dryRun,
    candidate_ids: ctx.selectedCandidateIds,
    resource_id: ctx.scope.resource_id,
    batch_id: ctx.scope.batch_id,
    source_atlas: ctx.scope.source_atlas,
    granularity_level: ctx.scope.granularity_level,
    granularity_family: ctx.scope.granularity_family,
    create_mirror_records: true,
    create_triples: taskId === 'composite_triple_generation',
    create_evidence: taskId !== 'composite_triple_generation',
    debug_single_pack: debugSinglePack,
    debug_max_packs: debugSinglePack ? 1 : null,
  }
}

async function runViaBackendCompositeWorkflow(
  taskId: CompositeExtractionTaskId,
  ctx: CompositeExtractionContext,
  cb: CompositeRunCallbacks,
  signal?: AbortSignal,
): Promise<CompositeExtractionResult> {
  const minRequired = CANDIDATE_MINIMUMS[taskId] ?? 0
  const n = ctx.selectedCandidateIds.length
  if (n < minRequired) {
    const substepDefs = COMPOSITE_TASK_SUBSTEP_LABELS[taskId].map((label, i) => ({
      id: Object.values(STEP_KEY_TO_SUBSTEP)[i]?.id ?? `step_${i}`,
      label,
    }))
    const msg = taskId.includes('connection')
      ? `连接提取至少需要 ${minRequired} 个候选脑区，当前只选择了 ${n} 个。`
      : `回路提取至少需要 ${minRequired} 个候选脑区，当前只选择了 ${n} 个。`
    const result = buildValidationFailedResult(taskId, substepDefs, msg)
    cb.onProgress([...result.substeps], { phase: 'complete' })
    return result
  }

  const payload = buildCompositeRequest(taskId, ctx)
  console.info('[LLM Extraction] composite request debug flags', {
    debug_single_pack: payload.debug_single_pack ?? false,
    debug_max_packs: payload.debug_max_packs ?? null,
    workflow_type: payload.workflow_type,
    dry_run: payload.dry_run ?? false,
  })
  const startedAt = Date.now()
  const pendingSubsteps = COMPOSITE_TASK_SUBSTEP_LABELS[taskId].map((label, i) => ({
    ...makeSubstep(
      Object.values(STEP_KEY_TO_SUBSTEP)[i]?.id ?? `step_${i}`,
      label,
    ),
  }))
  cb.onProgress([...pendingSubsteps], { phase: 'starting' })

  let response: CompositeWorkflowRunResponse
  let finalDetail: CompositeWorkflowRunRead | undefined
  let usedSyncFallback = false

  try {
    const started = await startCompositeWorkflow(payload)
    const initialSubsteps = mapServerSteps({
      workflow_run_id: started.workflow_run_id,
      workflow_type: started.workflow_type,
      status: started.status,
      dry_run: started.dry_run,
      candidate_count: started.candidate_count,
      pair_count: started.pair_count,
      steps: started.steps,
      progress_percent: started.progress_percent,
      warnings: started.warnings,
    })
    cb.onProgress(initialSubsteps, {
      phase: 'running',
      workflowRunId: started.workflow_run_id,
      progressPercent: started.progress_percent,
      workflowStatus: started.status,
      elapsedMs: 0,
    })
    finalDetail = await pollCompositeWorkflowRun(
      started.workflow_run_id,
      cb,
      startedAt,
      initialSubsteps,
      signal,
    )
    response = readToRunResponse(finalDetail)
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      usedSyncFallback = true
      cb.onProgress([...pendingSubsteps], {
        phase: 'running',
        indeterminate: true,
        elapsedMs: Date.now() - startedAt,
      })
      response = await runCompositeWorkflow(payload)
    } else {
      throw new Error(formatCompositeWorkflowError(e))
    }
  }

  const substeps = finalDetail ? mapServerStepsFromRead(finalDetail) : mapServerSteps(response)
  const topProviderAudit = (
    finalDetail?.provider_audit
    ?? response.result_summary?.provider_audit
  ) as Record<string, unknown> | undefined
  cb.onProgress(substeps, {
    phase: 'complete',
    workflowRunId: response.workflow_run_id,
    progressPercent: usedSyncFallback ? undefined : (response.progress_percent ?? 100),
    indeterminate: usedSyncFallback,
    workflowStatus: response.status,
    workflowOutcome: resolveWorkflowSemanticStatus(response),
    elapsedMs: Date.now() - startedAt,
    recentEvents: response.recent_events,
    resultSummary: response.result_summary,
    providerAudit: topProviderAudit,
    diagnostics: finalDetail?.diagnostics,
  })

  const warnings = [...(response.warnings ?? [])]
  if (response.errors?.length) {
    warnings.push(...response.errors)
  }
  if (usedSyncFallback) {
    warnings.push('后端 start 接口不可用，已回退到同步 /run；进度条为不确定模式。')
  }

  return {
    taskId,
    status: mapServerStatus(response.status, ctx.dryRun, response.display_status ?? response.outcome ?? undefined),
    substeps,
    warnings,
    workflowRunId: response.workflow_run_id,
    serverSide: true,
    createdTargets: response.created_targets
      ?? (response.result_summary?.created_targets as CompositeWorkflowCreatedTarget[] | undefined),
    recentEvents: response.recent_events,
    outcome: response.outcome ?? undefined,
    displayStatus: response.display_status ?? undefined,
    semanticStatus: response.semantic_status ?? undefined,
    resultSummary: response.result_summary,
    providerAudit: topProviderAudit,
    diagnostics: finalDetail?.diagnostics,
  }
}

// ── Main entry point ──────────────────────────────────────────────────────────

export async function runCompositeExtractionTask(
  taskId: CompositeExtractionTaskId,
  ctx: CompositeExtractionContext,
  cb: CompositeRunCallbacks,
  signal?: AbortSignal,
): Promise<CompositeExtractionResult> {
  try {
    return await runViaBackendCompositeWorkflow(taskId, ctx, cb, signal)
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      return runCompositeExtractionTaskFallback(taskId, ctx, cb)
    }
    if (e instanceof Error && e.message) {
      throw e
    }
    throw new Error(formatCompositeWorkflowError(e))
  }
}

async function runCompositeExtractionTaskFallback(
  taskId: CompositeExtractionTaskId,
  ctx: CompositeExtractionContext,
  cb: CompositeRunCallbacks,
): Promise<CompositeExtractionResult> {
  switch (taskId) {
    case 'composite_connection_with_function':
      return runConnectionWithFunction(ctx, cb)
    case 'composite_circuit_with_function_and_steps':
      return runCircuitWithFunctionAndSteps(ctx, cb)
    case 'composite_triple_generation':
      return runTripleGeneration(ctx, cb)
    default:
      return {
        taskId,
        status: 'skipped',
        substeps: [],
        warnings: [`Unknown composite task: ${taskId}`],
        serverSide: false,
      }
  }
}

// ── Frontend fallback orchestration (legacy) ──────────────────────────────────

// ── Substep label helpers (used by UI) ────────────────────────────────────────

export const COMPOSITE_TASK_SUBSTEP_LABELS: Record<CompositeExtractionTaskId, string[]> = {
  composite_connection_with_function: [
    'llm.composite.substepConnection',
    'llm.composite.substepProjectionFunction',
  ],
  composite_circuit_with_function_and_steps: [
    'llm.composite.substepCircuit',
    'llm.composite.substepCircuitStep',
    'llm.composite.substepCircuitFunction',
  ],
  composite_triple_generation: [
    'llm.composite.substepTriple',
  ],
}

export const COMPOSITE_TASK_LABELS: Record<CompositeExtractionTaskId, string> = {
  composite_connection_with_function: 'llm.composite.connectionWithFunction',
  composite_circuit_with_function_and_steps: 'llm.composite.circuitWithFunctionAndSteps',
  composite_triple_generation: 'llm.composite.tripleGeneration',
}
