import type { PreviewColumn } from '../components/pipeline/StageDataPreviewDrawer'
import type { PipelineStageKey } from './pipelineNavigation'
import {
  fetchCandidates,
  fetchRawAal3Labels,
  fetchReviewRecords,
  fetchRuleValidationRunResults,
  listRawMacro96Rows,
} from '../api/endpoints'

export interface StagePreviewLoadResult {
  rows: Record<string, unknown>[]
  columns: PreviewColumn[]
  total: number
  apiNotImplemented: boolean
}

export async function loadStagePreview(
  stage: PipelineStageKey,
  opts: {
    batchId: string
    isMacro96: boolean
    parseRunId?: string
    generationRunId?: string
    validationRunId?: string
  },
): Promise<StagePreviewLoadResult> {
  const limit = 10
  const { batchId, isMacro96, parseRunId, generationRunId, validationRunId } = opts

  if (stage === 'parsed') {
    if (isMacro96) {
      const res = await listRawMacro96Rows({
        batch_id: batchId,
        parse_run_id: parseRunId,
        limit,
      })
      return {
        total: res.total,
        apiNotImplemented: false,
        columns: [
          { key: 'region_index', header: 'region_index' },
          { key: 'en_name', header: 'en_name' },
          { key: 'cn_name', header: 'cn_name' },
          { key: 'source_sheet', header: 'source_sheet' },
        ],
        rows: res.items.map(r => ({
          region_index: r.region_index,
          en_name: r.en_name,
          cn_name: r.cn_name ?? '—',
          source_sheet: r.source_sheet ?? '—',
        })),
      }
    }
    const res = await fetchRawAal3Labels({ batch_id: batchId, parse_run_id: parseRunId, limit })
    return {
      total: res.total,
      apiNotImplemented: false,
      columns: [
        { key: 'label_index', header: 'label_index' },
        { key: 'cn_name', header: 'cn_name' },
        { key: 'en_name', header: 'en_name' },
        { key: 'laterality', header: 'laterality' },
      ],
      rows: res.items.map(r => ({
        label_index: r.label_index ?? '—',
        cn_name: r.cn_name ?? r.raw_name,
        en_name: r.en_name ?? '—',
        laterality: r.laterality,
      })),
    }
  }

  if (stage === 'candidate_generated') {
    const res = await fetchCandidates({
      batch_id: batchId,
      generation_run_id: generationRunId,
      parse_run_id: parseRunId,
      limit,
    })
    return {
      total: res.total,
      apiNotImplemented: false,
      columns: [
        { key: 'en_name', header: 'en_name' },
        { key: 'cn_name', header: 'cn_name' },
        { key: 'source_atlas', header: 'source_atlas' },
        { key: 'candidate_status', header: 'status' },
      ],
      rows: res.items.map(r => ({
        en_name: r.en_name ?? '—',
        cn_name: r.cn_name ?? '—',
        source_atlas: r.source_atlas,
        candidate_status: r.candidate_status,
      })),
    }
  }

  if (stage === 'validated') {
    if (!validationRunId) {
      return { rows: [], columns: [], total: 0, apiNotImplemented: false }
    }
    const res = await fetchRuleValidationRunResults(validationRunId, { limit })
    return {
      total: res.total,
      apiNotImplemented: false,
      columns: [
        { key: 'overall_status', header: 'status' },
        { key: 'error_count', header: 'errors' },
        { key: 'warning_count', header: 'warnings' },
        { key: 'candidate_id', header: 'candidate_id' },
      ],
      rows: res.items.map(r => ({
        overall_status: r.overall_status,
        error_count: r.error_count,
        warning_count: r.warning_count,
        candidate_id: r.candidate_id.slice(0, 10) + '…',
      })),
    }
  }

  if (stage === 'reviewed') {
    const res = await fetchReviewRecords({ batch_id: batchId, limit })
    return {
      total: res.total,
      apiNotImplemented: false,
      columns: [
        { key: 'action', header: 'action' },
        { key: 'from_status', header: 'from' },
        { key: 'to_status', header: 'to' },
        { key: 'reviewed_by', header: 'reviewed_by' },
      ],
      rows: res.items.map(r => ({
        action: r.action,
        from_status: r.from_status,
        to_status: r.to_status,
        reviewed_by: r.reviewed_by,
      })),
    }
  }

  if (stage === 'promoted') {
    return {
      rows: [],
      columns: [],
      total: 0,
      apiNotImplemented: true,
    }
  }

  return { rows: [], columns: [], total: 0, apiNotImplemented: true }
}
