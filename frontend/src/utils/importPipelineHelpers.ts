import {
  isAal3Batch,
  isMacro96Batch,
  type BoundFilePipelineRead,
  type ImportBatch,
  type ImportBatchEvent,
  type ImportBatchPipelineOverview,
  type ImportBatchStatus,
  type ParserKey,
} from '../api/endpoints'
export { isAal3Batch, isMacro96Batch, type ImportBatchStatus, type ParserKey } from '../api/endpoints'

export interface PipelineDataSnapshot {
  rawParseRunId?: string
  rawParserKey?: string
  rawParseStatus?: string
  rawRowCount?: number
  rawFinishedAt?: string
  candidateGenerationRunId?: string
  candidateGeneratorKey?: string
  candidateCount?: number
  validationRunId?: string
  validationPassed?: number
  validationWarning?: number
  validationFailed?: number
  reviewSubmitted?: number
  reviewApproved?: number
  reviewRejected?: number
  promotedCount?: number
}

export interface BatchFileCompatibility {
  compatible: boolean
  canParse: boolean
  reason: string | null
}

export interface TimelineStepDef {
  key: string
  labelKey: string
  statusRank: number
  dataLabelKey?: string
}

export const PIPELINE_TIMELINE_STEPS: TimelineStepDef[] = [
  { key: 'created', labelKey: 'pipeline.stepCreated', statusRank: 0 },
  { key: 'queued', labelKey: 'pipeline.stepQueued', statusRank: 1 },
  { key: 'running', labelKey: 'pipeline.stepRunning', statusRank: 2 },
  { key: 'parsed', labelKey: 'pipeline.stepParsed', statusRank: 3, dataLabelKey: 'pipeline.rawData' },
  { key: 'candidate_generated', labelKey: 'pipeline.stepCandidates', statusRank: 4, dataLabelKey: 'pipeline.candidateData' },
  { key: 'validated', labelKey: 'pipeline.stepValidated', statusRank: 5, dataLabelKey: 'pipeline.validationData' },
  { key: 'reviewed', labelKey: 'pipeline.stepReviewed', statusRank: 6 },
  { key: 'promoted', labelKey: 'pipeline.stepPromoted', statusRank: 7 },
]

const STATUS_RANK: Record<string, number> = {
  created: 0,
  queued: 1,
  running: 2,
  parsed: 3,
  candidate_generated: 4,
  validated: 5,
  validation_dispatched: 5,
  reviewed: 6,
  promoted: 7,
}

export function batchStatusRank(status: string): number {
  return STATUS_RANK[status] ?? -1
}

export function timelineStepState(
  stepRank: number,
  batchStatus: string,
): 'done' | 'current' | 'pending' {
  const current = batchStatusRank(batchStatus)
  if (current < 0) return 'pending'
  if (stepRank < current) return 'done'
  if (stepRank === current) return 'current'
  return 'pending'
}

export function getMacro96BoundFileCompatibility(file: BoundFilePipelineRead): BatchFileCompatibility {
  const hasRole = file.file_role_in_batch === 'macro_region_pool_source'
  const active = file.is_active
  const intermediateReady = file.intermediate_status === 'ready'
  const kindOk = (file.latest_intermediate_kind ?? '').includes('macro_region_table')

  if (!hasRole) {
    return { compatible: false, canParse: false, reason: 'not_macro_region_pool_source' }
  }
  if (!active) {
    return { compatible: false, canParse: false, reason: 'file_not_active' }
  }
  if (!intermediateReady || !kindOk) {
    return { compatible: false, canParse: false, reason: 'macro_region_table_required' }
  }
  return { compatible: true, canParse: true, reason: 'macro_region_table_ready' }
}

export function getAal3BoundFileCompatibility(file: BoundFilePipelineRead): BatchFileCompatibility {
  const compatible = file.parser_compatible_for_aal3_xml
  const canParse = file.can_parse && compatible && file.is_active
  const reason = compatible
    ? (file.is_active ? (file.can_parse ? 'aal3_ready' : 'aal3_not_ready') : 'file_not_active')
    : (file.parser_incompatible_reason ?? 'aal3_incompatible')
  return { compatible, canParse, reason: reason ?? null }
}

export function getBatchFileCompatibility(
  file: BoundFilePipelineRead,
  parserKey: string | null | undefined,
): BatchFileCompatibility {
  if (isMacro96Batch({ parser_key: parserKey })) {
    return getMacro96BoundFileCompatibility(file)
  }
  if (isAal3Batch({ parser_key: parserKey })) {
    return getAal3BoundFileCompatibility(file)
  }
  return { compatible: false, canParse: false, reason: 'unknown_parser' }
}

export function buildDataSnapshot(
  overview: ImportBatchPipelineOverview,
  isMacro96: boolean,
): PipelineDataSnapshot {
  const latestParse = overview.parse_runs[0]
  const latestGen = overview.generation_runs[0]
  const latestVal = overview.validation_runs[0]
  const valSummary = overview.latest_validation_summary

  return {
    rawParseRunId: latestParse?.id,
    rawParserKey: latestParse?.parser_key,
    rawParseStatus: latestParse?.status,
    rawRowCount: isMacro96
      ? (latestParse?.output_count ?? undefined)
      : (overview.raw_label_count || latestParse?.output_count),
    rawFinishedAt: latestParse?.finished_at ?? undefined,
    candidateGenerationRunId: latestGen?.id,
    candidateGeneratorKey: latestGen?.generator_key,
    candidateCount: overview.candidate_count || latestGen?.output_count,
    validationRunId: latestVal?.id,
    validationPassed: valSummary?.passed_count ?? latestVal?.passed_count,
    validationWarning: valSummary?.warning_count ?? latestVal?.warning_count,
    validationFailed: valSummary?.failed_count ?? latestVal?.failed_count,
  }
}

export function resourceShortLabel(batch: ImportBatch): string {
  if (isMacro96Batch(batch)) return 'Macro96'
  if (isAal3Batch(batch)) return 'AAL3'
  return batch.parser_key ?? '—'
}

export function parserBadgeClass(parserKey: string | null | undefined): string {
  if (isMacro96Batch({ parser_key: parserKey })) return 'pipeline-parser-badge pipeline-parser-badge--macro96'
  if (isAal3Batch({ parser_key: parserKey })) return 'pipeline-parser-badge pipeline-parser-badge--aal3'
  return 'pipeline-parser-badge'
}

const EVENT_TYPE_I18N: Record<string, string> = {
  created: 'pipeline.eventCreated',
  file_attached: 'pipeline.eventFileAttached',
  status_changed: 'pipeline.eventStatusChanged',
  parse_started: 'pipeline.eventParseStarted',
  parse_succeeded: 'pipeline.eventParseSucceeded',
  parse_failed: 'pipeline.eventParseFailed',
  parse_macro96_started: 'pipeline.eventParseMacro96Started',
  parse_macro96_succeeded: 'pipeline.eventParseMacro96Succeeded',
  parse_macro96_failed: 'pipeline.eventParseMacro96Failed',
  candidate_generation_started: 'pipeline.eventCandidateGenStarted',
  candidate_generation_succeeded: 'pipeline.eventCandidateGenSucceeded',
  candidate_generation_failed: 'pipeline.eventCandidateGenFailed',
  rule_validation_started: 'pipeline.eventValidationStarted',
  rule_validation_succeeded: 'pipeline.eventValidationSucceeded',
  rule_validation_failed: 'pipeline.eventValidationFailed',
  cancelled: 'pipeline.eventCancelled',
  failed: 'pipeline.eventFailed',
  completed: 'pipeline.eventCompleted',
}

export function eventTypeLabel(eventType: string, t: (k: string) => string): string {
  const key = EVENT_TYPE_I18N[eventType]
  return key ? t(key) : eventType
}

export function sortEventsChronological(events: ImportBatchEvent[]): ImportBatchEvent[] {
  return [...events].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  )
}

export function compatibilityReasonLabel(
  reason: string | null,
  t: (k: string) => string,
): string {
  if (!reason) return '—'
  const map: Record<string, string> = {
    macro_region_table_ready: 'pipeline.reasonMacro96Ready',
    macro_region_table_required: 'pipeline.macro96IntermediateRequired',
    file_not_active: 'importPipeline.boundFileInactiveHint',
    not_macro_region_pool_source: 'pipeline.noMacro96PoolSource',
    aal3_ready: 'pipeline.reasonAal3Ready',
    aal3_incompatible: 'pipeline.noAal3XmlLabelFile',
    unknown_parser: 'pipeline.parserUnknown',
  }
  const key = map[reason]
  return key ? t(key) : reason
}

export function getTimelineStepCount(
  stepKey: string,
  overview: ImportBatchPipelineOverview,
  isMacro96: boolean,
): string {
  const snap = buildDataSnapshot(overview, isMacro96)
  switch (stepKey) {
    case 'parsed':
      return snap.rawRowCount != null ? String(snap.rawRowCount) : '—'
    case 'candidate_generated':
      return snap.candidateCount != null ? String(snap.candidateCount) : '—'
    case 'validated':
      if (snap.validationPassed == null) return '—'
      return `${snap.validationPassed}✓ / ${snap.validationFailed ?? 0}✗`
    default:
      return ''
  }
}
