export type LlmDataTabId =
  | 'candidates'
  | 'mirror'
  | 'runs'
  | 'items'
  | 'macroClinical'
  | 'finalLinks'
  | 'fieldCompletions'

export type MirrorSubTabId = 'connections' | 'functions' | 'circuits' | 'triples'

export type BulkCandidateTask =
  | 'region_field_completion'
  | 'same_granularity_connection_completion'
  | 'same_granularity_function_completion'
  | 'same_granularity_circuit_completion'

/** Composite task IDs that orchestrate multiple substeps */
export type CompositeTaskId =
  | 'composite_connection_with_function'
  | 'composite_circuit_with_function_and_steps'
  | 'composite_triple_generation'

export const COMPOSITE_TASKS: CompositeTaskId[] = [
  'composite_connection_with_function',
  'composite_circuit_with_function_and_steps',
  'composite_triple_generation',
]

export function isCompositeTask(task: string): task is CompositeTaskId {
  return (COMPOSITE_TASKS as string[]).includes(task)
}

/** All tasks that operate on candidates (bulk row selection needed) */
export const CANDIDATE_REQUIRED_TASKS: string[] = [
  'region_field_completion',
  'same_granularity_connection_completion',
  'same_granularity_function_completion',
  'same_granularity_circuit_completion',
  'composite_connection_with_function',
  'composite_circuit_with_function_and_steps',
]

export interface TaskGroup {
  id: string
  tasks: Array<{
    taskType: string
    implemented: boolean
    planned?: boolean
  }>
}

export const CANDIDATE_BULK_TASKS: BulkCandidateTask[] = [
  'region_field_completion',
  'same_granularity_connection_completion',
  'same_granularity_function_completion',
  'same_granularity_circuit_completion',
]

export const MACRO_CLINICAL_TASKS = [
  'circuit_to_steps',
  'circuit_steps_to_projections',
  'projection_to_functions',
  'projections_to_circuits',
  'dual_model_verification',
]

export const PLANNED_TASKS = [
  'translation',
  'evidence_explanation',
  'uncertainty_flagging',
  'region_to_functions',
  'circuit_to_functions',
  'macro_clinical_triple_generation',
  'evidence_uncertainty_review',
]

export function isCandidateBulkTask(task: string): task is BulkCandidateTask {
  return (CANDIDATE_BULK_TASKS as string[]).includes(task)
}

export function parseLlmDataTab(raw: string | null): LlmDataTabId {
  const map: Record<string, LlmDataTabId> = {
    candidates: 'candidates',
    region: 'candidates',
    runs: 'runs',
    items: 'items',
    mirror: 'mirror',
    connections: 'mirror',
    functions: 'mirror',
    circuits: 'mirror',
    triples: 'mirror',
    macroClinical: 'macroClinical',
    finalLinks: 'finalLinks',
    finalBrowser: 'finalLinks',
    finalExport: 'finalLinks',
    finalPromotion: 'finalLinks',
    validation: 'finalLinks',
    review: 'finalLinks',
    fieldCompletions: 'fieldCompletions',
  }
  return map[raw ?? ''] ?? 'candidates'
}

export function parseMirrorSubTab(raw: string | null): MirrorSubTabId {
  const map: Record<string, MirrorSubTabId> = {
    connections: 'connections',
    functions: 'functions',
    circuits: 'circuits',
    triples: 'triples',
  }
  return map[raw ?? ''] ?? 'connections'
}
