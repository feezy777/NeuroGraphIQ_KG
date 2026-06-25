import { useState, useCallback, useEffect } from 'react'
import {
  listMirrorCircuits,
  listMirrorCircuitSteps,
  listMirrorConnections,
  listMirrorProjectionFunctions,
  listMirrorCircuitProjectionMemberships,
  listCircuitProjectionCrossValidationRuns,
  listMirrorDualModelVerificationRuns,
} from '../../../../api/endpoints'
import type { MacroPipelineStepProgress, MacroPipelineStepStatus } from './macroClinicalPipelineTypes'

interface ScopeParams {
  batch_id?: string
  resource_id?: string
  source_atlas?: string
  granularity_level?: string
}

interface PipelineCounts {
  circuits: number
  steps: number
  projections: number
  projectionFunctions: number
  memberships: number
  crossValidationRuns: number
  dualModelRuns: number
}

function resolveStatus(inputCount: number, outputCount: number, hasApiError: boolean): MacroPipelineStepStatus {
  if (hasApiError) return 'warning'
  if (inputCount <= 0) return 'not_started'
  if (outputCount <= 0) return 'ready'
  return 'completed'
}

function buildPipelineSteps(c: PipelineCounts, errors: boolean[]): MacroPipelineStepProgress[] {
  return [
    {
      id: 'circuit_to_steps',
      index: 1,
      title: 'Circuit → Steps',
      subtitle: '从已抽取的回路生成有序回路步骤',
      inputLabel: 'mirror_region_circuits',
      outputLabel: 'mirror_circuit_steps',
      status: resolveStatus(c.circuits, c.steps, errors[0] || errors[1]),
      percent: c.circuits > 0 ? (c.steps > 0 ? 100 : 20) : 0,
      inputCount: c.circuits,
      outputCount: c.steps,
      nextAction: c.circuits === 0
        ? '先完成 Mirror Circuits 抽取'
        : c.steps === 0 ? '执行 Circuit → Steps' : '查看结果 / 重新运行',
      resultTarget: 'steps',
    },
    {
      id: 'steps_to_projections',
      index: 2,
      title: 'Steps → Projections + Memberships',
      subtitle: '从回路步骤生成投射及回路-投射包含关系',
      inputLabel: 'mirror_circuit_steps',
      outputLabel: 'mirror_region_connections (projection) + memberships',
      status: resolveStatus(c.steps, c.projections, errors[1] || errors[2]),
      percent: c.steps > 0 ? (c.projections > 0 ? (c.memberships > 0 ? 100 : 60) : 20) : 0,
      inputCount: c.steps,
      outputCount: c.projections,
      nextAction: c.steps === 0
        ? '先完成 Circuit → Steps'
        : c.projections === 0 ? '执行 Steps → Projections' : '查看结果 / 重新运行',
      resultTarget: 'membership',
    },
    {
      id: 'projection_to_functions',
      index: 3,
      title: 'Projection → Functions',
      subtitle: '为投射生成功能候选',
      inputLabel: 'mirror_region_connections (projection)',
      outputLabel: 'mirror_projection_functions',
      status: resolveStatus(c.projections, c.projectionFunctions, errors[2] || errors[3]),
      percent: c.projections > 0 ? (c.projectionFunctions > 0 ? 100 : 20) : 0,
      inputCount: c.projections,
      outputCount: c.projectionFunctions,
      nextAction: c.projections === 0
        ? '先完成 Steps → Projections'
        : c.projectionFunctions === 0 ? '执行 Projection → Functions' : '查看结果 / 重新运行',
      resultTarget: 'projFn',
    },
    {
      id: 'projections_to_circuits',
      index: 4,
      title: 'Projection Graph → Circuits',
      subtitle: '从投射网络反向推断回路候选',
      inputLabel: 'mirror_region_connections (projection graph)',
      outputLabel: 'mirror_region_circuits + steps + memberships',
      status: resolveStatus(c.projections > 1 ? 1 : 0, c.circuits, errors[0] || errors[2]),
      percent: c.projections > 1 ? (c.circuits > 0 ? 100 : 20) : 0,
      inputCount: c.projections,
      outputCount: c.circuits,
      nextAction: c.projections < 2
        ? '先完成 Steps → Projections（至少 2 个投射）'
        : c.circuits === 0 ? '执行 Projection Graph → Circuits' : '查看结果 / 重新运行',
      resultTarget: 'steps',
    },
    {
      id: 'cross_validation',
      index: 5,
      title: 'Circuit-Projection Cross Validation',
      subtitle: '确定性比较正向和反向链路',
      inputLabel: 'circuit_to_projection + projection_to_circuit memberships',
      outputLabel: 'cross_validation_runs/results + membership.verification_status',
      status: resolveStatus(c.memberships, c.crossValidationRuns, errors[4] || errors[5]),
      percent: c.memberships > 0 ? (c.crossValidationRuns > 0 ? 100 : 20) : 0,
      inputCount: c.memberships,
      outputCount: c.crossValidationRuns,
      nextAction: c.memberships === 0
        ? '先完成 Steps → Projections（需要 memberships）'
        : c.crossValidationRuns === 0 ? '执行 Cross Validation' : '查看结果 / 重新运行',
      resultTarget: 'membership',
    },
    {
      id: 'dual_model_verification',
      index: 6,
      title: 'Dual-Model Verification',
      subtitle: 'DeepSeek 与 Kimi 独立验证 Mirror 对象',
      inputLabel: 'circuit / projection / membership / triple',
      outputLabel: 'mirror_dual_model_verification_runs/results',
      status: resolveStatus(c.projections > 0 || c.circuits > 0 ? 1 : 0, c.dualModelRuns, errors[6]),
      percent: (c.projections > 0 || c.circuits > 0) ? (c.dualModelRuns > 0 ? 100 : 20) : 0,
      inputCount: c.projections + c.circuits,
      outputCount: c.dualModelRuns,
      nextAction: c.dualModelRuns === 0 ? '执行 Dual-Model Verification' : '查看结果',
      resultTarget: 'dmRuns',
    },
  ]
}

function computeNextStep(c: PipelineCounts): string {
  if (c.circuits === 0) return '先完成 Mirror Circuits 抽取，再进入 Circuit → Steps'
  if (c.steps === 0) return '下一步：执行 Circuit → Steps'
  if (c.projections === 0) return '下一步：执行 Steps → Projections'
  if (c.projectionFunctions === 0) return '下一步：执行 Projection → Functions'
  if (c.memberships === 0) return '下一步：执行 Projection Graph → Circuits'
  if (c.crossValidationRuns === 0) return '下一步：执行 Cross Validation'
  if (c.dualModelRuns === 0) return '下一步：执行 Dual-Model Verification'
  return '下一步：进入 Mirror 治理 → Rule Validation / Human Review'
}

export function useMacroClinicalPipelineProgress(scope?: ScopeParams) {
  const [counts, setCounts] = useState<PipelineCounts>({
    circuits: 0, steps: 0, projections: 0,
    projectionFunctions: 0, memberships: 0,
    crossValidationRuns: 0, dualModelRuns: 0,
  })
  const [apiErrors, setApiErrors] = useState<boolean[]>(Array(7).fill(false))
  const [tick, setTick] = useState(0)
  const refresh = useCallback(() => setTick(x => x + 1), [])

  useEffect(() => {
    let cancelled = false
    const base = {
      source_atlas: scope?.source_atlas || undefined,
      granularity_level: scope?.granularity_level || undefined,
      batch_id: scope?.batch_id || undefined,
      resource_id: scope?.resource_id || undefined,
      limit: 1 as const,
    }

    const safeCount = async <T>(promise: Promise<{ items: T[]; total?: number }>): Promise<[number, boolean]> => {
      try {
        const res = await promise
        return [res.total ?? res.items.length, false]
      } catch {
        return [0, true]
      }
    }

    async function load() {
      const results = await Promise.all([
        safeCount(listMirrorCircuits(base)),
        safeCount(listMirrorCircuitSteps(base)),
        safeCount(listMirrorConnections(base)),
        safeCount(listMirrorProjectionFunctions(base)),
        safeCount(listMirrorCircuitProjectionMemberships(base)),
        safeCount(listCircuitProjectionCrossValidationRuns({ limit: 1 })),
        safeCount(listMirrorDualModelVerificationRuns(base)),
      ])
      if (cancelled) return
      const counts = results.map(([c]) => c)
      const errs = results.map(([, e]) => e)
      setCounts({
        circuits: counts[0],
        steps: counts[1],
        projections: counts[2],
        projectionFunctions: counts[3],
        memberships: counts[4],
        crossValidationRuns: counts[5],
        dualModelRuns: counts[6],
      })
      setApiErrors(errs)
    }

    load()
    return () => { cancelled = true }
  }, [tick, scope?.batch_id, scope?.resource_id, scope?.source_atlas, scope?.granularity_level])

  const steps = buildPipelineSteps(counts, apiErrors)
  const nextStep = computeNextStep(counts)
  const hasError = apiErrors.some(Boolean)

  return { steps, nextStep, hasError, refresh }
}
