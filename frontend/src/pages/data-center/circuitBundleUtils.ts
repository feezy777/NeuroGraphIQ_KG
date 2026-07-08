import {
  getFieldCompletionRelatedTargets,
  listMirrorCircuits,
  type FieldCompletionRelatedTargetsResponse,
} from '../../api/endpoints'
import { ApiError } from '../../api/client'
import type { ExtractionResultModalData } from '../llm-extraction/components/ExtractionResultModal'
import type {
  CircuitBundleFieldCompletionGroup,
  CircuitBundleSource,
  CircuitBundleTargetGroup,
} from './circuitBundleTypes'

const BUNDLE_GROUP_DEFS: Array<{
  targetType: 'circuit' | 'circuit_step' | 'circuit_function'
  labelKey: string
}> = [
  { targetType: 'circuit', labelKey: 'dataCenter.bundleGroupCircuit' },
  { targetType: 'circuit_step', labelKey: 'dataCenter.bundleGroupCircuitStep' },
  { targetType: 'circuit_function', labelKey: 'dataCenter.bundleGroupCircuitFunction' },
]

function isCircuitFunctionMigrationWarning(warnings: string[]): boolean {
  return warnings.some(w =>
    w.includes('MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED')
    || w.includes('033_mirror_circuit_functions')
    || w.includes('dataCenter.mirrorCircuitFunctionsNotInitialized'),
  )
}

/** Map backend / legacy warnings to i18n keys or friendly messages. */
export function normalizeBundleWarning(warning: string): string {
  const w = warning.trim()
  if (!w) return w
  if (w.startsWith('dataCenter.')) return w
  if (
    w.includes('MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED')
    || w.includes('033_mirror_circuit_functions')
    || w.toLowerCase().includes('table is not initialized')
  ) {
    return 'dataCenter.mirrorCircuitFunctionsNotInitialized'
  }
  if (
    w.toLowerCase().includes('not implemented yet')
    || w.toLowerCase().includes('is not implemented')
    || w.toLowerCase().includes('circuit_to_functions')
    || w.toLowerCase().includes('no mirror_circuit_functions found')
  ) {
    return 'dataCenter.bundleCircuitFunctionRunExtractionFirst'
  }
  return w
}

export function normalizeBundleWarnings(warnings: string[] | undefined): string[] {
  if (!warnings?.length) return []
  return [...new Set(warnings.map(normalizeBundleWarning).filter(Boolean))]
}

export function translateBundleWarning(warning: string, t: (key: string) => string): string {
  const normalized = normalizeBundleWarning(warning)
  return normalized.startsWith('dataCenter.') ? t(normalized) : normalized
}

export function buildCircuitBundleFromGroups(
  groups: CircuitBundleTargetGroup[],
  source: CircuitBundleSource,
): CircuitBundleFieldCompletionGroup {
  return {
    bundleType: 'circuit_bundle',
    label: 'Circuit Bundle',
    groups,
    source,
  }
}

export function buildCircuitBundleFromRelatedResponse(
  circuitIds: string[],
  response: FieldCompletionRelatedTargetsResponse,
  source: CircuitBundleSource,
): { bundle: CircuitBundleFieldCompletionGroup; warnings: string[] } {
  const warnings = normalizeBundleWarnings(response.warnings ?? [])
  const groupByType = new Map(response.groups.map(g => [g.target_type, g]))
  const circuitGroup = groupByType.get('circuit')
  const resolvedCircuitIds = circuitGroup?.target_ids?.length
    ? circuitGroup.target_ids
    : circuitIds

  const groups: CircuitBundleTargetGroup[] = BUNDLE_GROUP_DEFS.map(def => {
    const related = groupByType.get(def.targetType)
    const targetIds =
      def.targetType === 'circuit'
        ? resolvedCircuitIds
        : (related?.target_ids ?? [])
    const groupWarnings = normalizeBundleWarnings(related?.warnings)

    if (def.targetType === 'circuit_function') {
      if (isCircuitFunctionMigrationWarning(groupWarnings)) {
        return {
          targetType: def.targetType,
          label: def.targetType,
          targetIds: [],
          formalObjectType: def.targetType,
          status: 'unavailable',
          unavailableReason: 'dataCenter.mirrorCircuitFunctionsNotInitialized',
          warnings: groupWarnings,
        }
      }
      if (targetIds.length === 0) {
        return {
          targetType: def.targetType,
          label: def.targetType,
          targetIds: [],
          formalObjectType: def.targetType,
          status: circuitIds.length > 0 ? 'no_data' : 'skipped',
          unavailableReason: circuitIds.length > 0
            ? 'dataCenter.bundleCircuitFunctionRunExtractionFirst'
            : undefined,
          warnings: groupWarnings.length
            ? groupWarnings
            : (circuitIds.length > 0 ? ['dataCenter.bundleCircuitFunctionRunExtractionFirst'] : undefined),
        }
      }
      return {
        targetType: def.targetType,
        label: def.targetType,
        targetIds,
        formalObjectType: def.targetType,
        status: 'pending',
        warnings: groupWarnings.length ? groupWarnings : undefined,
      }
    }

    if (
      def.targetType !== 'circuit'
      && targetIds.length === 0
      && circuitIds.length > 0
    ) {
      warnings.push('dataCenter.relatedTargetsMissing')
    }

    return {
      targetType: def.targetType,
      label: def.targetType,
      targetIds,
      formalObjectType: def.targetType,
      status: targetIds.length === 0 ? 'skipped' : 'pending',
      warnings: groupWarnings.length ? groupWarnings : undefined,
    }
  })

  return {
    bundle: buildCircuitBundleFromGroups(groups, source),
    warnings: [...new Set(warnings)],
  }
}

export async function resolveCircuitBundleFromCircuitIds(
  circuitIds: string[],
  source: CircuitBundleSource,
): Promise<{ bundle: CircuitBundleFieldCompletionGroup; warnings: string[] }> {
  // Limit to prevent HTTP 431 (URL too long with 450+ UUIDs)
  const limitedIds = circuitIds.slice(0, 100)
  if (limitedIds.length === 0) {
    return {
      bundle: buildCircuitBundleFromGroups(
        BUNDLE_GROUP_DEFS.map(def => ({
          targetType: def.targetType,
          label: def.targetType,
          targetIds: [],
          formalObjectType: def.targetType,
          status: 'skipped',
        })),
        source,
      ),
      warnings: [],
    }
  }

  try {
    const response = await getFieldCompletionRelatedTargets({
      target_type: 'circuit',
      target_ids: limitedIds,
      include: ['circuit_step', 'circuit_function'],
    })
    return buildCircuitBundleFromRelatedResponse(limitedIds, response, source)
  } catch (err) {
    const msg = String(err instanceof Error ? err.message : err)
    const detail = err instanceof ApiError ? err.meta?.responseBody : undefined
    const detailStr = typeof detail === 'object' && detail !== null
      ? JSON.stringify(detail)
      : String(detail ?? '')
    const combined = `${msg} ${detailStr}`
    const migration = combined.includes('MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED')
      || combined.includes('033_mirror_circuit_functions')
      || combined.includes('mirror_circuit_functions table is not initialized')
    const warnings = migration
      ? ['dataCenter.mirrorCircuitFunctionsNotInitialized']
      : ['dataCenter.relatedTargetsMissing']
    return {
      bundle: buildCircuitBundleFromGroups(
        BUNDLE_GROUP_DEFS.map(def => ({
          targetType: def.targetType,
          label: def.targetType,
          targetIds: def.targetType === 'circuit' ? circuitIds : [],
          formalObjectType: def.targetType,
          status: def.targetType === 'circuit_function' && migration
            ? 'unavailable'
            : def.targetType === 'circuit_function' && circuitIds.length > 0
              ? 'no_data'
              : def.targetType === 'circuit'
                ? 'pending'
                : 'skipped',
          unavailableReason: def.targetType === 'circuit_function' && migration
            ? 'dataCenter.mirrorCircuitFunctionsNotInitialized'
            : def.targetType === 'circuit_function' && circuitIds.length > 0 && !migration
              ? 'dataCenter.bundleCircuitFunctionRunExtractionFirst'
              : undefined,
          warnings: def.targetType !== 'circuit' ? warnings : undefined,
        })),
        source,
      ),
      warnings,
    }
  }
}

export function hasCircuitBundleCreation(data: ExtractionResultModalData): boolean {
  const counts = data.createdCounts ?? {}
  if ((counts.circuits ?? 0) > 0) return true
  if ((counts.circuit_steps ?? 0) > 0) return true
  if ((counts.circuit_functions ?? 0) > 0) return true
  return (data.substeps ?? []).some(
    s =>
      ['circuit', 'circuit_steps', 'circuit_functions'].includes(s.id)
      && (s.createdCount ?? 0) > 0,
  )
}

export async function resolveCircuitBundleForExtraction(
  data: ExtractionResultModalData,
): Promise<{ bundle: CircuitBundleFieldCompletionGroup; warnings: string[] }> {
  const circuitStep = data.substeps?.find(s => s.id === 'circuit')
  const stepsStep = data.substeps?.find(s => s.id === 'circuit_steps')
  const functionsStep = data.substeps?.find(s => s.id === 'circuit_functions')

  let circuitIds = circuitStep?.createdIds ?? []
  let stepIds = stepsStep?.createdIds ?? []
  const functionIds = functionsStep?.createdIds ?? []

  if (circuitIds.length === 0 && circuitStep?.runId) {
    try {
      const res = await listMirrorCircuits({ llm_run_id: circuitStep.runId, limit: 500 })
      circuitIds = (res.items ?? []).map(item => item.id)
    } catch {
      // keep empty — bundle modal will show skipped groups
    }
  }

  if (circuitIds.length > 0) {
    const resolved = await resolveCircuitBundleFromCircuitIds(circuitIds, 'extraction_result')
    if (stepIds.length > 0) {
      const stepGroup = resolved.bundle.groups.find(g => g.targetType === 'circuit_step')
      if (stepGroup) {
        stepGroup.targetIds = stepIds
        stepGroup.status = 'pending'
      }
    }
    if (functionIds.length > 0) {
      const fnGroup = resolved.bundle.groups.find(g => g.targetType === 'circuit_function')
      if (fnGroup && fnGroup.status !== 'unavailable') {
        fnGroup.targetIds = functionIds
        fnGroup.status = 'pending'
      }
    }
    return resolved
  }

  const warnings: string[] = []
  const groups: CircuitBundleTargetGroup[] = BUNDLE_GROUP_DEFS.map(def => {
    const count = data.createdCounts?.[
      def.targetType === 'circuit'
        ? 'circuits'
        : def.targetType === 'circuit_step'
          ? 'circuit_steps'
          : 'circuit_functions'
    ] ?? 0
    return {
      targetType: def.targetType,
      label: def.targetType,
      targetIds: [],
      formalObjectType: def.targetType,
      status: count > 0 ? 'pending' : (def.targetType === 'circuit_function' ? 'no_data' : 'skipped'),
      unavailableReason: count === 0 && def.targetType === 'circuit_function'
        ? 'dataCenter.bundleCircuitFunctionRunExtractionFirst'
        : undefined,
      warnings: count > 0 && !circuitIds.length ? ['dataCenter.relatedTargetsMissing'] : undefined,
    }
  })
  if ((data.createdCounts?.circuits ?? 0) > 0) {
    warnings.push('dataCenter.relatedTargetsMissing')
  }
  return {
    bundle: buildCircuitBundleFromGroups(groups, 'extraction_result'),
    warnings,
  }
}
