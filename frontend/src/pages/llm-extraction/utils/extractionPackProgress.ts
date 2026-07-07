import type { CompositeWorkflowRunRead, CompositeWorkflowStartResponse } from '../../../api/endpoints'

/** Matches backend DEFAULT_PAIRS_PER_PACK / DEFAULT_PAIRS_PER_PACK_OVERRIDE (30). */
export const DEFAULT_PAIRS_PER_PACK = 30

export function estimatePackCountFromPairs(pairCount: number, pairsPerPack: number = DEFAULT_PAIRS_PER_PACK): number {
  if (pairCount <= 0) return 0
  return Math.ceil(pairCount / pairsPerPack)
}

export function readProgressMetric(
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

export function resolveConnectionStepExec(
  detail: CompositeWorkflowRunRead,
): Record<string, unknown> {
  const connStep = (detail.steps ?? []).find(s => s.step_key === 'extract_connections')
  return (connStep?.execution_summary ?? {}) as Record<string, unknown>
}

/** Live polls prefer committed structured fields + result_summary.
 *  Step execution_summary is NOT committed during execution (step_commit=False),
 *  so it MUST be checked last to avoid stale 0s overwriting real values. */
export function buildProgressMetricSources(
  detail: CompositeWorkflowRunRead,
  terminal: boolean,
): Record<string, unknown>[] {
  const stepExec = resolveConnectionStepExec(detail)
  const stepPa = (stepExec.provider_audit ?? {}) as Record<string, unknown>
  const topPa = (detail.provider_audit ?? {}) as Record<string, unknown>
  const rs = (detail.result_summary ?? {}) as Record<string, unknown>
  const rsPa = (rs.provider_audit ?? {}) as Record<string, unknown>
  const flatProgress = normalizeRunProgress(detail as unknown as Record<string, unknown>)
  // rs (raw committed flat dict) first — source of truth from callback write.
  // flatProgress second — structured fields as fallback/supplement.
  // stepExec/stepPa LAST — stale because step_commit=False.
  return [rs, rsPa, flatProgress, topPa, stepExec, stepPa]
}

export function resolveTotalPackCount(input: {
  dryRunTotalPackCount?: number | null
  pairCount?: number | null
  plannedPackCount?: number | null
  packCount?: number | null
}): number {
  if (input.packCount != null && input.packCount > 0) return input.packCount
  if (input.plannedPackCount != null && input.plannedPackCount > 0) return input.plannedPackCount
  if (input.dryRunTotalPackCount != null && input.dryRunTotalPackCount > 0) {
    return input.dryRunTotalPackCount
  }
  if (input.pairCount != null && input.pairCount > 0) {
    return estimatePackCountFromPairs(input.pairCount)
  }
  return 0
}

export function readStartResponsePackCount(
  response: CompositeWorkflowStartResponse,
  dryRunTotalPackCount?: number | null,
): number {
  const connStep = (response.steps ?? []).find(s => s.step_key === 'extract_connections')
  const exec = (connStep?.execution_summary ?? {}) as Record<string, unknown>
  return resolveTotalPackCount({
    dryRunTotalPackCount,
    pairCount: response.pair_count,
    packCount: readProgressMetric([exec], 'pack_count'),
    plannedPackCount: readProgressMetric([exec], 'planned_pack_count'),
  })
}

/** Flatten backend structured fields into flat keys. ALWAYS set every key
 *  to prevent stale step.response_json from being read by fallthrough. */
export function normalizeRunProgress(detail: Record<string, unknown>): Record<string, unknown> {
  const flat: Record<string, unknown> = {}
  const pg = (detail.progress ?? {}) as Record<string, unknown>
  const cs = (detail.connection_summary ?? {}) as Record<string, unknown>
  const fs = (detail.function_summary ?? {}) as Record<string, unknown>
  const us = (detail.usage_summary ?? {}) as Record<string, unknown>

  // ProgressDetail
  flat.total_pack_count = pg.total_pack_count ?? flat.total_pack_count
  flat.processed_pack_count = pg.completed_pack_count ?? 0
  flat.succeeded_pack_count = pg.succeeded_pack_count ?? 0
  flat.failed_pack_count = pg.failed_pack_count ?? 0
  flat.in_flight_pack_count = pg.running_pack_count ?? 0
  flat.queued_pack_count = pg.queued_pack_count ?? 0
  flat.pack_progress_percent = pg.progress_percent ?? 0

  // ConnectionSummary
  flat.screened_likely_connection_count = cs.screened_likely_connection_count ?? 0
  flat.parsed_projection_count = cs.parsed_connection_count ?? cs.connection_count ?? 0
  flat.parsed_connection_count = cs.parsed_connection_count ?? cs.connection_count ?? 0
  flat.created_projection_count = cs.mirror_created_count ?? 0
  flat.updated_projection_count = cs.mirror_updated_count ?? 0
  flat.skipped_duplicate_count = cs.mirror_skipped_duplicate_count ?? 0
  flat.no_connection_count = cs.no_connection_count ?? 0

  // FunctionSummary
  flat.parsed_function_count = fs.extracted_function_count ?? fs.function_count ?? 0

  // UsageSummary
  flat.prompt_tokens = us.prompt_tokens ?? 0
  flat.completion_tokens = us.completion_tokens ?? 0
  flat.total_tokens = us.total_tokens ?? ((Number(us.prompt_tokens ?? 0)) + (Number(us.completion_tokens ?? 0)))

  return flat
}

/** Avoid out-of-order poll responses regressing counters while the run is active. */
export function mergeMonotonicCounter(
  previous: number,
  next: number | null | undefined,
  terminal: boolean,
): number {
  const value = next ?? 0
  if (terminal) return value
  return Math.max(previous, value)
}
