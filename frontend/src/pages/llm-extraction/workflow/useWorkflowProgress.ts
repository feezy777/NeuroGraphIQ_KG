import { useState, useCallback, useEffect } from 'react'
import {
  listLlmExtractionRuns,
  listLlmExtractionItems,
  fetchCandidates,
  listMirrorConnections,
  listMirrorFunctions,
  listMirrorCircuits,
  listMirrorTriples,
  listMirrorCircuitSteps,
  listMirrorProjectionFunctions,
  listMirrorCircuitProjectionMemberships,
  listMirrorValidationRuns,
  listMirrorValidationResults,
  listMirrorReviewQueue,
  listFinalMacroClinicalPromotionRuns,
  listFinalMacroClinicalObjects,
  listFinalKgExports,
  listDualModelVerificationExecutionRuns,
  listCircuitProjectionCrossValidationRuns,
} from '../../../api/endpoints'
import type { WorkflowStageProgress, WorkflowProgress, StageId, StageStatus } from './workflowTypes'

interface ProgressCounts {
  candidates: number
  llmRuns: number
  llmItems: number
  connections: number
  functions: number
  circuits: number
  triples: number
  circuitSteps: number
  projectionFunctions: number
  memberships: number
  crossValidations: number
  dualModelRuns: number
  validationRuns: number
  validationErrors: number
  reviewQueue: number
  reviewApproved: number
  promotionRuns: number
  finalObjects: number
  exports: number
}

function deriveStatus(percent: number, warnings: number): StageStatus {
  if (warnings > 0 && percent < 100) return 'warning'
  if (percent === 0) return 'not_started'
  if (percent === 100) return 'completed'
  if (percent >= 50) return 'running'
  return 'ready'
}

function buildStages(c: ProgressCounts): WorkflowStageProgress[] {
  // Stage 1: Candidate & Runs
  const s1Checks = [
    { id: 'has_candidates', label: '已有候选脑区', done: c.candidates > 0 },
    { id: 'has_runs', label: '已有 LLM run', done: c.llmRuns > 0 },
    { id: 'has_items', label: '已有 LLM item', done: c.llmItems > 0 },
  ]
  const s1Done = s1Checks.filter(x => x.done).length
  const s1Total = s1Checks.length
  const s1Pct = Math.round((s1Done / s1Total) * 100)

  // Stage 2: Mirror Extraction
  const s2Checks = [
    { id: 'has_conns', label: 'Mirror connections 已生成', done: c.connections > 0 },
    { id: 'has_fns', label: 'Mirror functions 已生成', done: c.functions > 0 },
    { id: 'has_circs', label: 'Mirror circuits 已生成', done: c.circuits > 0 },
    { id: 'has_triples', label: 'Mirror triples 已生成', done: c.triples > 0 },
    { id: 'has_steps', label: 'Circuit steps 已生成', done: c.circuitSteps > 0 },
    { id: 'has_proj_fns', label: 'Projection functions 已生成', done: c.projectionFunctions > 0 },
    { id: 'has_membs', label: 'Memberships 已生成', done: c.memberships > 0 },
    { id: 'has_cross', label: 'Cross validation 已运行', done: c.crossValidations > 0 },
    { id: 'has_dual', label: 'Dual-model verification 已运行', done: c.dualModelRuns > 0 },
  ]
  const s2Done = s2Checks.filter(x => x.done).length
  const s2Total = s2Checks.length
  const s2Pct = Math.round((s2Done / s2Total) * 100)

  // Stage 3: Governance
  const s3Checks = [
    { id: 'has_val_runs', label: 'Rule validation 已运行', done: c.validationRuns > 0 },
    { id: 'val_errors_visible', label: 'blocker/error 数量可见', done: c.validationRuns > 0 },
    { id: 'has_review', label: 'Human review queue 可见', done: c.reviewQueue > 0 },
    { id: 'has_approved', label: '有 human_approved 对象', done: c.reviewApproved > 0 },
  ]
  const s3Done = s3Checks.filter(x => x.done).length
  const s3Total = s3Checks.length
  const s3Pct = Math.round((s3Done / s3Total) * 100)
  const s3Warnings = c.validationErrors

  // Stage 4: Final Promotion
  const s4Checks = [
    { id: 'has_eligible', label: '有 eligible human_approved 对象', done: c.reviewApproved > 0 },
    { id: 'has_prom_runs', label: 'Final Promotion 已执行', done: c.promotionRuns > 0 },
    { id: 'has_final_objs', label: 'final_* 有数据', done: c.finalObjects > 0 },
  ]
  const s4Done = s4Checks.filter(x => x.done).length
  const s4Total = s4Checks.length
  const s4Pct = Math.round((s4Done / s4Total) * 100)

  // Stage 5: Final Knowledge
  const s5Checks = [
    { id: 'has_final_objs', label: 'Final Browser 可搜索 (有 final 对象)', done: c.finalObjects > 0 },
    { id: 'has_exports', label: 'Export 文件已生成', done: c.exports > 0 },
  ]
  const s5Done = s5Checks.filter(x => x.done).length
  const s5Total = s5Checks.length
  const s5Pct = Math.round((s5Done / s5Total) * 100)

  return [
    {
      id: 'candidate',
      label: '运行与候选',
      description: '候选脑区、字段补全、LLM runs/items',
      status: deriveStatus(s1Pct, 0),
      percent: s1Pct,
      completedChecks: s1Done,
      totalChecks: s1Total,
      warnings: 0,
      checks: s1Checks,
    },
    {
      id: 'mirror',
      label: 'Mirror 抽取',
      description: '连接、功能、回路、三元组与 macro_clinical 扩展抽取',
      status: deriveStatus(s2Pct, 0),
      percent: s2Pct,
      completedChecks: s2Done,
      totalChecks: s2Total,
      warnings: 0,
      checks: s2Checks,
    },
    {
      id: 'governance',
      label: 'Mirror 治理',
      description: '规则校验与人工审核',
      status: deriveStatus(s3Pct, s3Warnings),
      percent: s3Pct,
      completedChecks: s3Done,
      totalChecks: s3Total,
      warnings: s3Warnings,
      checks: s3Checks,
    },
    {
      id: 'finalPromotion',
      label: 'Final 晋升',
      description: '将 human_approved 的 Mirror 对象晋升到内部 final_* 正式层',
      status: deriveStatus(s4Pct, 0),
      percent: s4Pct,
      completedChecks: s4Done,
      totalChecks: s4Total,
      warnings: 0,
      checks: s4Checks,
    },
    {
      id: 'knowledge',
      label: 'Final 知识层',
      description: '只读浏览与本地导出',
      status: deriveStatus(s5Pct, 0),
      percent: s5Pct,
      completedChecks: s5Done,
      totalChecks: s5Total,
      warnings: 0,
      checks: s5Checks,
    },
  ]
}

function computeNextStep(c: ProgressCounts): string {
  if (c.llmRuns === 0) return '先在"运行与候选"中执行 Region 字段补全或 Mirror 抽取'
  if (c.connections > 0 && c.circuitSteps === 0) return '进入 Mirror 抽取 → Macro Clinical，执行 Circuit-to-Steps'
  if (c.circuitSteps > 0 && c.projectionFunctions === 0) return '执行 Circuit-Steps-to-Projections'
  if (c.memberships > 0 && c.crossValidations === 0) return '进入 Mirror 抽取 → Cross Validation'
  if (c.crossValidations > 0 && c.dualModelRuns === 0) return '执行 Dual-Model Verification'
  if (c.connections > 0 && c.validationRuns === 0) return '进入 Mirror 治理 → Rule Validation'
  if (c.validationErrors > 0) return '进入 Human Review，处理 blocker/error'
  if (c.reviewApproved > 0 && c.promotionRuns === 0) return '进入 Final 晋升 → Preview Promotion'
  if (c.finalObjects > 0 && c.exports === 0) return '进入 Final 知识层 → Export'
  if (c.exports > 0) return '准备 External Sync dry-run validator（本页面不直接同步外部库）'
  return '按流程推进当前阶段'
}

export function useWorkflowProgress() {
  const [counts, setCounts] = useState<ProgressCounts>({
    candidates: 0, llmRuns: 0, llmItems: 0,
    connections: 0, functions: 0, circuits: 0, triples: 0,
    circuitSteps: 0, projectionFunctions: 0, memberships: 0,
    crossValidations: 0, dualModelRuns: 0,
    validationRuns: 0, validationErrors: 0,
    reviewQueue: 0, reviewApproved: 0,
    promotionRuns: 0, finalObjects: 0, exports: 0,
  })
  const [loading, setLoading] = useState(false)
  const [hasError, setHasError] = useState(false)
  const [tick, setTick] = useState(0)

  const refreshProgress = useCallback(() => setTick(x => x + 1), [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)

    const safeCount = async <T>(promise: Promise<{ items: T[]; total?: number }>): Promise<number> => {
      try {
        const res = await promise
        return res.total ?? res.items.length
      } catch {
        return -1
      }
    }

    const safeItems = async <T>(promise: Promise<{ items: T[] }>): Promise<T[]> => {
      try {
        const res = await promise
        return res.items
      } catch {
        return []
      }
    }

    async function load() {
      const [
        candidateCount, llmRunCount, llmItemCount,
        connCount, fnCount, circCount, tripleCount,
        stepCount, projFnCount, membCount,
        crossCount, dualCount,
        valRunCount,
        reviewItems,
        promRunCount, finalObjCount,
        exports,
      ] = await Promise.all([
        safeCount(fetchCandidates({ limit: 1 })),
        safeCount(listLlmExtractionRuns({ limit: 1 })),
        safeCount(listLlmExtractionItems({ limit: 1 })),
        safeCount(listMirrorConnections({ limit: 1 })),
        safeCount(listMirrorFunctions({ limit: 1 })),
        safeCount(listMirrorCircuits({ limit: 1 })),
        safeCount(listMirrorTriples({ limit: 1 })),
        safeCount(listMirrorCircuitSteps({ limit: 1 })),
        safeCount(listMirrorProjectionFunctions({ limit: 1 })),
        safeCount(listMirrorCircuitProjectionMemberships({ limit: 1 })),
        safeCount(listCircuitProjectionCrossValidationRuns({ limit: 1 })),
        safeCount(listDualModelVerificationExecutionRuns({ limit: 1 })),
        safeCount(listMirrorValidationRuns({ limit: 1 })),
        safeItems(listMirrorReviewQueue({ limit: 50 })),
        safeCount(listFinalMacroClinicalPromotionRuns({ limit: 1 })),
        safeCount(listFinalMacroClinicalObjects('circuit', { limit: 1 })),
        safeItems(listFinalKgExports()),
      ])

      if (cancelled) return

      const reviewApprovedCount = reviewItems.filter(
        (item: { review_status?: string }) => item.review_status === 'human_approved'
      ).length

      // Check validation errors by fetching first run's results
      let validationErrors = 0
      if (valRunCount > 0) {
        try {
          const valRuns = await listMirrorValidationRuns({ limit: 1 })
          if (valRuns.items.length > 0) {
            const results = await listMirrorValidationResults({ run_id: valRuns.items[0].id, limit: 20 })
            validationErrors = results.items.filter(
              (r: { severity?: string }) => r.severity === 'error' || r.severity === 'blocker'
            ).length
          }
        } catch {
          // ignore
        }
      }

      if (cancelled) return

      const exportsCount = Array.isArray(exports) ? exports.length : 0

      const anyNegative = [
        candidateCount, llmRunCount, llmItemCount, connCount, fnCount, circCount, tripleCount,
        stepCount, projFnCount, membCount, crossCount, dualCount, valRunCount,
        promRunCount, finalObjCount,
      ].some(x => x < 0)

      setHasError(anyNegative)
      setCounts({
        candidates: Math.max(0, candidateCount),
        llmRuns: Math.max(0, llmRunCount),
        llmItems: Math.max(0, llmItemCount),
        connections: Math.max(0, connCount),
        functions: Math.max(0, fnCount),
        circuits: Math.max(0, circCount),
        triples: Math.max(0, tripleCount),
        circuitSteps: Math.max(0, stepCount),
        projectionFunctions: Math.max(0, projFnCount),
        memberships: Math.max(0, membCount),
        crossValidations: Math.max(0, crossCount),
        dualModelRuns: Math.max(0, dualCount),
        validationRuns: Math.max(0, valRunCount),
        validationErrors,
        reviewQueue: reviewItems.length,
        reviewApproved: reviewApprovedCount,
        promotionRuns: Math.max(0, promRunCount),
        finalObjects: Math.max(0, finalObjCount),
        exports: exportsCount,
      })
      setLoading(false)
    }

    load()
    return () => { cancelled = true }
  }, [tick])

  const stages = buildStages(counts)
  const globalPercent = Math.round(
    stages.reduce((sum, s) => sum + s.percent, 0) / stages.length
  )
  const nextStep = computeNextStep(counts)

  const progress: WorkflowProgress = { stages, globalPercent, nextStep }

  return { progress, loading, hasError, refreshProgress }
}
