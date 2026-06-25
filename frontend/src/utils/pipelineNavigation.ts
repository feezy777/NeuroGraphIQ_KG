import type { PipelineIds } from '../hooks/useSessionIds'
import type { ImportBatchRunHistoryResponse } from '../api/endpoints'

export type PipelineStageKey =
  | 'parsed'
  | 'candidate_generated'
  | 'validated'
  | 'reviewed'
  | 'promoted'

export interface StageNavContext {
  stage: PipelineStageKey
  active: boolean
  currentCount: number
  runId?: string
  deleted: boolean
  fullViewPath: string
  fullViewQuery: Record<string, string>
}

export function readHashQueryParams(): Record<string, string> {
  const hash = typeof window !== 'undefined' ? window.location.hash.slice(1) : ''
  const q = hash.indexOf('?')
  if (q < 0) return {}
  const params = new URLSearchParams(hash.slice(q + 1))
  const out: Record<string, string> = {}
  params.forEach((v, k) => { out[k] = v })
  return out
}

export function buildHashUrl(path: string, query: Record<string, string | undefined>): string {
  const base = path.startsWith('/') ? path : `/${path}`
  const qs = Object.entries(query)
    .filter((entry): entry is [string, string] => Boolean(entry[1]))
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
  return qs ? `#${base}?${qs}` : `#${base}`
}

export function navigateWithQuery(path: string, query: Record<string, string | undefined>, ids?: Partial<PipelineIds>) {
  if (ids && typeof window !== 'undefined') {
    try {
      const KEY = 'ngiq_pipeline_ids'
      const prev = JSON.parse(sessionStorage.getItem(KEY) ?? '{}') as PipelineIds
      sessionStorage.setItem(KEY, JSON.stringify({ ...prev, ...ids }))
    } catch {
      /* ignore */
    }
  }
  window.location.hash = buildHashUrl(path, { ...query, from_pipeline: '1' })
}

export function resolvePipelineFilters(): PipelineIds & { fromPipeline: boolean } {
  const q = readHashQueryParams()
  let sess: PipelineIds = {}
  try {
    sess = JSON.parse(sessionStorage.getItem('ngiq_pipeline_ids') ?? '{}') as PipelineIds
  } catch {
    sess = {}
  }
  return {
    batch_id: q.batch_id || sess.batch_id,
    resource_id: q.resource_id || sess.resource_id,
    file_id: q.file_id || sess.file_id,
    parse_run_id: q.parse_run_id || sess.parse_run_id,
    generation_run_id: q.generation_run_id || sess.generation_run_id,
    validation_run_id: q.validation_run_id || sess.validation_run_id,
    rollback_record_id: q.rollback_record_id || sess.rollback_record_id,
    candidate_id: q.candidate_id || sess.candidate_id,
    final_region_id: q.final_region_id || sess.final_region_id,
    fromPipeline: q.from_pipeline === '1' || Boolean(q.batch_id),
  }
}

export function buildStageNavContext(
  stage: PipelineStageKey,
  batchId: string,
  resourceId: string,
  isMacro96: boolean,
  runHistory: ImportBatchRunHistoryResponse | null,
): StageNavContext {
  const summary = runHistory?.summary
  const active = runHistory?.current_active

  switch (stage) {
    case 'parsed': {
      const count = summary?.raw_row_count ?? 0
      const runId = active?.raw_parse_run_id ?? undefined
      return {
        stage,
        active: count > 0,
        currentCount: count,
        runId,
        deleted: count === 0 && Boolean(runHistory?.raw_parse_runs.some(r => !r.active && r.output_count > 0)),
        fullViewPath: isMacro96 ? '/raw-macro96' : '/raw-aal3',
        fullViewQuery: {
          batch_id: batchId,
          resource_id: resourceId,
          ...(runId ? { parse_run_id: runId } : {}),
        },
      }
    }
    case 'candidate_generated': {
      const count = summary?.candidate_count ?? 0
      const runId = active?.candidate_generation_run_id ?? undefined
      return {
        stage,
        active: count > 0,
        currentCount: count,
        runId,
        deleted: count === 0 && Boolean(runHistory?.candidate_generation_runs.some(r => !r.active && r.output_count > 0)),
        fullViewPath: '/candidates',
        fullViewQuery: {
          batch_id: batchId,
          resource_id: resourceId,
          ...(runId ? { generation_run_id: runId } : {}),
          ...(active?.raw_parse_run_id ? { parse_run_id: active.raw_parse_run_id } : {}),
          ...(isMacro96 ? { source_atlas: 'Macro96' } : {}),
        },
      }
    }
    case 'validated': {
      const count = summary?.validation_result_count ?? 0
      const runId = active?.validation_run_id ?? undefined
      return {
        stage,
        active: count > 0,
        currentCount: count,
        runId,
        deleted: count === 0 && Boolean(runHistory?.rule_validation_runs.some(r => !r.active && (r.passed_count + r.failed_count > 0))),
        fullViewPath: '/rule-validation',
        fullViewQuery: {
          batch_id: batchId,
          ...(runId ? { validation_run_id: runId } : {}),
          ...(active?.candidate_generation_run_id ? { generation_run_id: active.candidate_generation_run_id } : {}),
        },
      }
    }
    case 'reviewed': {
      const count = summary?.review_record_count ?? 0
      return {
        stage,
        active: count > 0,
        currentCount: count,
        deleted: false,
        fullViewPath: '/human-review',
        fullViewQuery: { batch_id: batchId, tab: 'records' },
      }
    }
    case 'promoted': {
      const count = (summary?.promotion_record_count ?? 0) + (summary?.final_region_count ?? 0)
      return {
        stage,
        active: count > 0,
        currentCount: count,
        deleted: false,
        fullViewPath: '/final-regions',
        fullViewQuery: { batch_id: batchId, resource_id: resourceId },
      }
    }
  }
}

export function pipelineReturnUrl(batchId: string): string {
  return buildHashUrl('/import-pipeline', { batch_id: batchId })
}

export type RunHistoryKind = 'raw' | 'candidate' | 'validation'

export function buildRunHistoryNavContext(
  kind: RunHistoryKind,
  run: {
    id: string
    active: boolean
    output_count?: number
    raw_row_count?: number
    candidate_count?: number
    result_count?: number
    passed_count?: number
    failed_count?: number
  },
  batchId: string,
  resourceId: string,
  isMacro96: boolean,
  activeParseRunId?: string,
): StageNavContext {
  if (kind === 'raw') {
    const currentCount = run.raw_row_count ?? 0
    const deleted = !run.active && (run.output_count ?? 0) > 0 && currentCount === 0
    return {
      stage: 'parsed',
      active: run.active && currentCount > 0,
      currentCount,
      runId: run.id,
      deleted,
      fullViewPath: isMacro96 ? '/raw-macro96' : '/raw-aal3',
      fullViewQuery: { batch_id: batchId, resource_id: resourceId, parse_run_id: run.id },
    }
  }
  if (kind === 'candidate') {
    const currentCount = run.candidate_count ?? 0
    const deleted = !run.active && (run.output_count ?? 0) > 0 && currentCount === 0
    return {
      stage: 'candidate_generated',
      active: run.active && currentCount > 0,
      currentCount,
      runId: run.id,
      deleted,
      fullViewPath: '/candidates',
      fullViewQuery: {
        batch_id: batchId,
        resource_id: resourceId,
        generation_run_id: run.id,
        ...(activeParseRunId ? { parse_run_id: activeParseRunId } : {}),
        ...(isMacro96 ? { source_atlas: 'Macro96' } : {}),
      },
    }
  }
  const currentCount = run.result_count ?? 0
  const historicalOutput = (run.passed_count ?? 0) + (run.failed_count ?? 0)
  const deleted = !run.active && historicalOutput > 0 && currentCount === 0
  return {
    stage: 'validated',
    active: run.active && currentCount > 0,
    currentCount,
    runId: run.id,
    deleted,
    fullViewPath: '/rule-validation',
    fullViewQuery: { batch_id: batchId, validation_run_id: run.id },
  }
}

export function stageViewLabelKey(stage: PipelineStageKey, isMacro96: boolean): string {
  switch (stage) {
    case 'parsed': return isMacro96 ? 'pipeline.viewRawMacro96' : 'pipeline.viewRawAal3'
    case 'candidate_generated': return 'pipeline.viewCandidates'
    case 'validated': return 'pipeline.viewValidationResults'
    case 'reviewed': return 'pipeline.viewReviewRecords'
    case 'promoted': return 'pipeline.viewFinalRegions'
  }
}

export function timelineStepToStage(stepKey: string): PipelineStageKey | null {
  if (stepKey === 'parsed') return 'parsed'
  if (stepKey === 'candidate_generated') return 'candidate_generated'
  if (stepKey === 'validated') return 'validated'
  if (stepKey === 'reviewed') return 'reviewed'
  if (stepKey === 'promoted') return 'promoted'
  return null
}
