export type GovernanceGateId = 'validation' | 'review' | 'promotion_readiness'

export type GovernanceGateStatus =
  | 'not_started'
  | 'ready'
  | 'blocked'
  | 'warning'
  | 'completed'

export interface GovernanceGateProgress {
  id: GovernanceGateId
  index: number
  title: string
  subtitle: string
  status: GovernanceGateStatus
  percent: number
  completedChecks: number
  totalChecks: number
  blockerCount?: number
  errorCount?: number
  warningCount?: number
  infoCount?: number
  pendingReviewCount?: number
  approvedCount?: number
  rejectedCount?: number
  nextAction: string
}

export interface GovernanceSummary {
  validationRunCount: number
  validationResultCount: number
  blockerCount: number
  errorCount: number
  warningCount: number
  infoCount: number
  reviewQueueCount: number
  pendingReviewCount: number
  needsRevisionCount: number
  approvedCount: number
  rejectedCount: number
  humanApprovedCount: number
  promotionReadyCount: number
  blockedFromPromotionCount: number
  hasApiError: boolean
  warnings: string[]
}
