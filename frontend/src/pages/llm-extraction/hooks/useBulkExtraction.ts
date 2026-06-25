import { useCallback, useState } from 'react'
import {
  runRegionFieldCompletion,
  runSameGranularityConnectionExtraction,
  runSameGranularityFunctionExtraction,
  runSameGranularityCircuitExtraction,
} from '../../../api/endpoints'
import { ApiError } from '../../../api/client'

export type BulkExtractionTask =
  | 'region_field_completion'
  | 'same_granularity_connection_completion'
  | 'same_granularity_function_completion'
  | 'same_granularity_circuit_completion'

export interface BulkRunStatus {
  taskType: string
  total: number
  completed: number
  failed: number
  running: number
  errors: Array<{ id: string; error: string }>
  runId?: string
  finished: boolean
}

interface RunBulkOptions {
  taskType: BulkExtractionTask
  candidateIds: string[]
  provider: string
  modelName: string
  dryRun: boolean
  batchId?: string
}

const BATCH_SIZE = 10
const MAX_CONCURRENT = 3

/** Tasks that must send all candidate_ids in one request (no auto-chunking). */
const SINGLE_SHOT_TASKS = new Set<BulkExtractionTask>([
  'same_granularity_connection_completion',
  'same_granularity_function_completion',
  'same_granularity_circuit_completion',
])

async function runSingleBatch(
  taskType: BulkExtractionTask,
  ids: string[],
  provider: string,
  modelName: string,
  dryRun: boolean,
  batchId?: string,
): Promise<{ succeeded: number; failed: number; errors: Array<{ id: string; error: string }>; runId?: string }> {
  const scope = batchId ? { batch_id: batchId } : undefined
  try {
    if (taskType === 'region_field_completion') {
      const res = await runRegionFieldCompletion({
        provider,
        model_name: modelName || undefined,
        candidate_ids: ids,
        dry_run: dryRun,
      })
      const failed = res.failed
      const succeeded = res.succeeded
      const errors: Array<{ id: string; error: string }> = []
      if (failed > 0) {
        errors.push({ id: 'batch', error: `${failed} items failed in run ${res.run_id}` })
      }
      return { succeeded, failed, errors, runId: res.run_id }
    }
    if (taskType === 'same_granularity_connection_completion') {
      const res = await runSameGranularityConnectionExtraction({
        provider,
        model_name: modelName || undefined,
        candidate_ids: ids,
        scope,
        dry_run: dryRun,
        create_mirror_records: !dryRun,
        create_triples: !dryRun,
        create_evidence: !dryRun,
      })
      return { succeeded: ids.length, failed: 0, errors: [], runId: res.run_id ?? undefined }
    }
    if (taskType === 'same_granularity_function_completion') {
      const res = await runSameGranularityFunctionExtraction({
        provider,
        model_name: modelName || undefined,
        candidate_ids: ids,
        scope,
        dry_run: dryRun,
        create_mirror_records: !dryRun,
        create_triples: !dryRun,
        create_evidence: !dryRun,
      })
      return { succeeded: ids.length, failed: 0, errors: [], runId: res.run_id ?? undefined }
    }
    if (taskType === 'same_granularity_circuit_completion') {
      const res = await runSameGranularityCircuitExtraction({
        provider,
        model_name: modelName || undefined,
        candidate_ids: ids,
        scope,
        dry_run: dryRun,
        create_mirror_records: !dryRun,
        create_triples: !dryRun,
        create_evidence: !dryRun,
      })
      return { succeeded: ids.length, failed: 0, errors: [], runId: res.run_id ?? undefined }
    }
    return { succeeded: 0, failed: ids.length, errors: [{ id: 'unknown', error: 'Unknown task type' }] }
  } catch (e) {
    const msg = e instanceof ApiError ? e.message : String(e)
    return {
      succeeded: 0,
      failed: ids.length,
      errors: ids.map(id => ({ id, error: msg })),
    }
  }
}

export function useBulkExtraction() {
  const [status, setStatus] = useState<BulkRunStatus | null>(null)
  const [running, setRunning] = useState(false)

  const runBulk = useCallback(async (options: RunBulkOptions) => {
    const { taskType, candidateIds, provider, modelName, dryRun, batchId } = options
    if (candidateIds.length === 0) return null

    setRunning(true)
    const initial: BulkRunStatus = {
      taskType,
      total: candidateIds.length,
      completed: 0,
      failed: 0,
      running: candidateIds.length,
      errors: [],
      finished: false,
    }
    setStatus(initial)

    const batches: string[][] = []
    if (SINGLE_SHOT_TASKS.has(taskType)) {
      batches.push(candidateIds)
    } else {
      for (let i = 0; i < candidateIds.length; i += BATCH_SIZE) {
        batches.push(candidateIds.slice(i, i + BATCH_SIZE))
      }
    }

    let completed = 0
    let failed = 0
    const errors: Array<{ id: string; error: string }> = []
    let lastRunId: string | undefined

    for (let i = 0; i < batches.length; i += MAX_CONCURRENT) {
      const chunk = batches.slice(i, i + MAX_CONCURRENT)
      const results = await Promise.all(
        chunk.map(batch =>
          runSingleBatch(taskType, batch, provider, modelName, dryRun, batchId),
        ),
      )
      for (const res of results) {
        completed += res.succeeded
        failed += res.failed
        errors.push(...res.errors)
        if (res.runId) lastRunId = res.runId
      }
      setStatus({
        taskType,
        total: candidateIds.length,
        completed,
        failed,
        running: Math.max(0, candidateIds.length - completed - failed),
        errors: [...errors],
        runId: lastRunId,
        finished: false,
      })
    }

    const finalStatus: BulkRunStatus = {
      taskType,
      total: candidateIds.length,
      completed,
      failed,
      running: 0,
      errors,
      runId: lastRunId,
      finished: true,
    }
    setStatus(finalStatus)
    setRunning(false)
    return finalStatus
  }, [])

  const clearStatus = useCallback(() => setStatus(null), [])

  return { status, running, runBulk, clearStatus }
}
