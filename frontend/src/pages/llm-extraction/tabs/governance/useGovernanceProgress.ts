import { useCallback, useEffect, useRef, useState } from 'react'
import {
  listMirrorValidationRuns,
  listMirrorValidationResults,
  listMirrorReviewQueue,
} from '../../../../api/endpoints'
import type { GovernanceSummary, GovernanceGateProgress, GovernanceGateId } from './governanceTypes'

async function safeTotal<T>(
  promise: Promise<{ items?: T[]; total?: number }>,
): Promise<[number, boolean]> {
  try {
    const res = await promise
    const total = res?.total ?? res?.items?.length ?? 0
    return [total, false]
  } catch {
    return [0, true]
  }
}

const EMPTY_SUMMARY: GovernanceSummary = {
  validationRunCount: 0,
  validationResultCount: 0,
  blockerCount: 0,
  errorCount: 0,
  warningCount: 0,
  infoCount: 0,
  reviewQueueCount: 0,
  pendingReviewCount: 0,
  needsRevisionCount: 0,
  approvedCount: 0,
  rejectedCount: 0,
  humanApprovedCount: 0,
  promotionReadyCount: 0,
  blockedFromPromotionCount: 0,
  hasApiError: false,
  warnings: [],
}

function buildGates(s: GovernanceSummary): GovernanceGateProgress[] {
  const gate1: GovernanceGateProgress = {
    id: 'validation' as GovernanceGateId,
    index: 0,
    title: 'Rule Validation',
    subtitle: 'Run structure & reference checks',
    status: 'not_started',
    percent: 0,
    completedChecks: 0,
    totalChecks: 3,
    blockerCount: s.blockerCount,
    errorCount: s.errorCount,
    warningCount: s.warningCount,
    infoCount: s.infoCount,
    nextAction: 'Run Validation',
  }
  if (s.hasApiError) {
    gate1.status = 'warning'
    gate1.percent = 30
  } else if (s.validationRunCount === 0) {
    gate1.status = 'not_started'
    gate1.percent = 0
    gate1.completedChecks = 0
  } else if (s.blockerCount > 0 || s.errorCount > 0) {
    gate1.status = 'warning'
    gate1.percent = 50
    gate1.completedChecks = 1
    gate1.nextAction = 'Fix blockers / errors'
  } else {
    gate1.status = 'completed'
    gate1.percent = 100
    gate1.completedChecks = 3
    gate1.nextAction = 'Proceed to Human Review'
  }

  const gate2: GovernanceGateProgress = {
    id: 'review' as GovernanceGateId,
    index: 1,
    title: 'Human Review',
    subtitle: 'Review pending mirror objects',
    status: 'not_started',
    percent: 0,
    completedChecks: 0,
    totalChecks: 3,
    pendingReviewCount: s.pendingReviewCount,
    approvedCount: s.approvedCount,
    rejectedCount: s.rejectedCount,
    nextAction: 'Open Review Queue',
  }
  if (s.validationRunCount === 0) {
    gate2.status = 'not_started'
  } else if (s.blockerCount > 0 || s.errorCount > 0) {
    gate2.status = 'blocked'
    gate2.nextAction = 'Fix validation blockers first'
  } else if (s.humanApprovedCount > 0 && s.pendingReviewCount === 0) {
    gate2.status = 'completed'
    gate2.percent = 100
    gate2.completedChecks = 3
    gate2.nextAction = 'Check Promotion Readiness'
  } else if (s.reviewQueueCount > 0) {
    gate2.status = s.needsRevisionCount > 0 ? 'warning' : 'ready'
    const reviewed = s.approvedCount + s.rejectedCount
    gate2.percent = s.reviewQueueCount > 0 ? Math.round((reviewed / (s.reviewQueueCount + reviewed)) * 80) : 0
    gate2.completedChecks = 1
    gate2.nextAction = 'Continue Review'
  } else {
    gate2.status = 'not_started'
    gate2.nextAction = 'Waiting for Validation'
  }

  const gate3: GovernanceGateProgress = {
    id: 'promotion_readiness' as GovernanceGateId,
    index: 2,
    title: 'Promotion Readiness',
    subtitle: 'Estimate ready objects for Final Promotion',
    status: 'not_started',
    percent: 0,
    completedChecks: 0,
    totalChecks: 3,
    nextAction: 'Jump to Final Promotion',
  }
  if (s.humanApprovedCount === 0) {
    gate3.status = 'not_started'
  } else if (s.blockerCount > 0 || s.errorCount > 0) {
    gate3.status = 'blocked'
    gate3.nextAction = 'Fix blockers before promoting'
  } else {
    gate3.status = 'ready'
    gate3.percent = 70
    gate3.completedChecks = 2
    gate3.nextAction = 'Run Final Promotion dry_run'
  }

  return [gate1, gate2, gate3]
}

function buildNextStep(s: GovernanceSummary): string {
  if (s.validationRunCount === 0) return 'noValidationNext'
  if (s.blockerCount > 0) return 'blockerNext'
  if (s.errorCount > 0) return 'errorNext'
  if (s.warningCount > 0 && s.reviewQueueCount > 0) return 'warningReviewNext'
  if (s.reviewQueueCount > 0) return 'reviewQueueNext'
  if (s.humanApprovedCount > 0) return 'promotionNext'
  return 'noObjectsNext'
}

export interface GovernanceProgressResult {
  summary: GovernanceSummary
  gates: GovernanceGateProgress[]
  recommendedNextStep: string
  loading: boolean
  error: string | null
  refresh: () => void
}

export function useGovernanceProgress(refreshKey: number): GovernanceProgressResult {
  const [summary, setSummary] = useState<GovernanceSummary>(EMPTY_SUMMARY)
  const [gates, setGates] = useState<GovernanceGateProgress[]>([])
  const [recommendedNextStep, setRecommendedNextStep] = useState('noObjectsNext')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  const abortRef = useRef(false)

  const refresh = useCallback(() => setTick(t => t + 1), [])

  useEffect(() => {
    abortRef.current = false
    setLoading(true)
    setError(null)

    async function load() {
      const warnings: string[] = []
      let hasApiError = false

      const [valRunCount, valRunErr] = await safeTotal(listMirrorValidationRuns({ limit: 1 }))
      if (valRunErr) { hasApiError = true; warnings.push('validation runs API unavailable') }

      const [blockerCount, blockerErr] = await safeTotal(listMirrorValidationResults({ severity: 'blocker', limit: 1 }))
      const [errorCount, errorErr] = await safeTotal(listMirrorValidationResults({ severity: 'error', limit: 1 }))
      const [warningCount, warnErr] = await safeTotal(listMirrorValidationResults({ severity: 'warning', limit: 1 }))
      const [infoCount, infoErr] = await safeTotal(listMirrorValidationResults({ severity: 'info', limit: 1 }))
      if (blockerErr || errorErr || warnErr || infoErr) {
        hasApiError = true
        warnings.push('validation results API partial failure')
      }

      const [queueTotal, queueErr] = await safeTotal(listMirrorReviewQueue({ limit: 1 }))
      if (queueErr) { hasApiError = true; warnings.push('review queue API unavailable') }

      const [approvedCount, approvedErr] = await safeTotal(
        listMirrorReviewQueue({ review_status: ['human_approved'], limit: 1 }),
      )
      if (approvedErr) { hasApiError = true; warnings.push('human_approved count unavailable') }

      const [needsRevisionCount, nrErr] = await safeTotal(
        listMirrorReviewQueue({ review_status: ['needs_revision'], limit: 1 }),
      )
      if (nrErr) warnings.push('needs_revision count unavailable')

      const [rejectedCount, rejErr] = await safeTotal(
        listMirrorReviewQueue({ review_status: ['rejected'], limit: 1 }),
      )
      if (rejErr) warnings.push('rejected count unavailable')

      const pendingReviewCount = Math.max(0, queueTotal - approvedCount - needsRevisionCount - rejectedCount)

      if (abortRef.current) return

      const s: GovernanceSummary = {
        validationRunCount: valRunCount,
        validationResultCount: blockerCount + errorCount + warningCount + infoCount,
        blockerCount,
        errorCount,
        warningCount,
        infoCount,
        reviewQueueCount: queueTotal,
        pendingReviewCount,
        needsRevisionCount,
        approvedCount,
        rejectedCount,
        humanApprovedCount: approvedCount,
        promotionReadyCount: approvedCount,
        blockedFromPromotionCount: blockerCount > 0 || errorCount > 0 ? approvedCount : 0,
        hasApiError,
        warnings,
      }

      setSummary(s)
      setGates(buildGates(s))
      setRecommendedNextStep(buildNextStep(s))
      setLoading(false)
    }

    load().catch(e => {
      if (!abortRef.current) {
        setError(String(e))
        setLoading(false)
      }
    })

    return () => { abortRef.current = true }
  }, [tick, refreshKey])

  return { summary, gates, recommendedNextStep, loading, error, refresh }
}
