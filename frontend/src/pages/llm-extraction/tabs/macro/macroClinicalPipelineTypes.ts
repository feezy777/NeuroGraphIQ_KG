export type MacroPipelineStepId =
  | 'circuit_to_steps'
  | 'steps_to_projections'
  | 'projection_to_functions'
  | 'projections_to_circuits'
  | 'cross_validation'
  | 'dual_model_verification'

export type MacroPipelineStepStatus =
  | 'not_started'
  | 'ready'
  | 'running'
  | 'warning'
  | 'completed'

export interface MacroPipelineStepProgress {
  id: MacroPipelineStepId
  index: number
  title: string
  subtitle: string
  inputLabel: string
  outputLabel: string
  status: MacroPipelineStepStatus
  percent: number
  inputCount?: number
  outputCount?: number
  runCount?: number
  warningCount?: number
  lastRunId?: string | null
  lastRunStatus?: string | null
  nextAction: string
  resultTarget?: string
}
