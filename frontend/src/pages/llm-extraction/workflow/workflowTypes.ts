export type StageId = 'candidate' | 'mirror' | 'governance' | 'finalPromotion' | 'knowledge'

export type StageStatus = 'not_started' | 'ready' | 'running' | 'warning' | 'completed'

export interface StageCheckItem {
  id: string
  label: string
  done: boolean
}

export interface WorkflowStageProgress {
  id: StageId
  label: string
  description: string
  status: StageStatus
  percent: number
  completedChecks: number
  totalChecks: number
  warnings: number
  nextAction?: string
  checks: StageCheckItem[]
}

export interface WorkflowProgress {
  stages: WorkflowStageProgress[]
  globalPercent: number
  nextStep: string
}
