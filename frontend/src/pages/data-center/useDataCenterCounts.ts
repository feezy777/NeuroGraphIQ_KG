import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchRawAal3Labels,
  listRawMacro96Rows,
  fetchCandidates,
  fetchCandidateStatusSummary,
  listMirrorConnections,
  listMirrorFunctions,
  listMirrorCircuits,
  listMirrorTriples,
  listMirrorCircuitSteps,
  listMirrorProjectionFunctions,
  listMirrorCircuitProjectionMemberships,
  listCircuitProjectionCrossValidationResults,
  listMirrorDualModelVerificationResults,
  listFinalMacroClinicalObjects,
  listFinalKgExports,
} from '../../api/endpoints'
import type { DataCenterCounts } from './dataCenterTypes'

const FETCH_TIMEOUT_MS = 10_000

/** Wrap a promise with a timeout — rejects if it takes too long. */
async function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error('timeout')), ms)
  })
  try {
    return await Promise.race([promise, timeout])
  } finally {
    if (timer) clearTimeout(timer)
  }
}

/** Fetch a paginated endpoint and return [total, hadError]. */
async function safeCount<T>(
  promise: Promise<{ items?: T[]; total?: number }>,
): Promise<[number, boolean]> {
  try {
    const res = await withTimeout(promise, FETCH_TIMEOUT_MS)
    return [res?.total ?? res?.items?.length ?? 0, false]
  } catch {
    return [0, true]
  }
}

const EMPTY: DataCenterCounts = {
  rawAal3Count: 0,
  rawMacro96Count: 0,
  candidateCount: 0,
  candidateRulePassed: 0,
  candidatePending: 0,
  mirrorConnections: 0,
  mirrorFunctions: 0,
  mirrorCircuits: 0,
  mirrorTriples: 0,
  macroCircuitSteps: 0,
  macroProjectionFunctions: 0,
  macroMemberships: 0,
  macroCrossResults: 0,
  macroDualResults: 0,
  finalCircuits: 0,
  finalProjections: 0,
  finalSteps: 0,
  finalFunctions: 0,
  finalTriples: 0,
  exportCount: 0,
  latestExportId: null,
  hasApiError: false,
  warnings: [],
}

export function useDataCenterCounts(granularity: string, refreshKey = 0) {
  const [counts, setCounts] = useState<DataCenterCounts>(EMPTY)
  const [loading, setLoading] = useState(false)
  const [tick, setTick] = useState(0)
  const abortRef = useRef(false)

  const refresh = useCallback(() => setTick(t => t + 1), [])

  useEffect(() => {
    abortRef.current = false
    setLoading(true)

    async function load() {
      const warnings: string[] = []
      let hasApiError = false

      // Fire ALL independent calls in parallel for maximum speed
      const [
        rawResult, macroResult, candResult,
        mcResult, mfResult, mciResult, mtResult,
        csResult, pfResult, memResult, cvResult, dmResult,
        fcResult, fpResult, fsResult, ffResult, ftResult,
        summaryResult, exportResult,
      ] = await Promise.allSettled([
        // ── Raw counts ──────────────────────────────────────────────
        safeCount(fetchRawAal3Labels({ limit: 1, granularity_level: granularity || undefined })),
        safeCount(listRawMacro96Rows({ limit: 1, granularity_level: granularity || undefined })),
        safeCount(fetchCandidates({ limit: 1, granularity_level: granularity || undefined })),
        // ── Mirror KG core ──────────────────────────────────────────
        safeCount(listMirrorConnections({ limit: 1, granularity_level: granularity || undefined })),
        safeCount(listMirrorFunctions({ limit: 1, granularity_level: granularity || undefined })),
        safeCount(listMirrorCircuits({ limit: 1, granularity_level: granularity || undefined })),
        safeCount(listMirrorTriples({ limit: 1, granularity_level: granularity || undefined })),
        // ── Mirror KG macro clinical ────────────────────────────────
        safeCount(listMirrorCircuitSteps({ limit: 1, granularity_level: granularity || undefined })),
        safeCount(listMirrorProjectionFunctions({ limit: 1, granularity_level: granularity || undefined })),
        safeCount(listMirrorCircuitProjectionMemberships({ limit: 1 })),
        safeCount(listCircuitProjectionCrossValidationResults({ limit: 1 })),
        safeCount(listMirrorDualModelVerificationResults({ limit: 1 })),
        // ── Final KG ────────────────────────────────────────────────
        safeCount(listFinalMacroClinicalObjects('circuit', { limit: 1 })),
        safeCount(listFinalMacroClinicalObjects('projection', { limit: 1 })),
        safeCount(listFinalMacroClinicalObjects('circuit_step', { limit: 1 })),
        safeCount(listFinalMacroClinicalObjects('projection_function', { limit: 1 })),
        safeCount(listFinalMacroClinicalObjects('triple', { limit: 1 })),
        // ── Candidate summary ───────────────────────────────────────
        (async (): Promise<[number, number, boolean]> => {
          try {
            const summary = await withTimeout(fetchCandidateStatusSummary({}), FETCH_TIMEOUT_MS)
            const rulePassed = summary.by_status.find(s => s.candidate_status === 'rule_passed')?.count ?? 0
            const pending = summary.by_status.find(s => s.candidate_status === 'candidate_created')?.count ?? 0
            return [rulePassed, pending, false]
          } catch {
            return [0, 0, true]
          }
        })(),
        // ── Export count ────────────────────────────────────────────
        (async (): Promise<[number, string | null, boolean]> => {
          try {
            const exports = await withTimeout(listFinalKgExports(), FETCH_TIMEOUT_MS)
            const total = exports.total ?? exports.items?.length ?? 0
            const latest = exports.items?.[0]?.export_id ?? null
            return [total, latest, false]
          } catch {
            return [0, null, true]
          }
        })(),
      ])

      // ── Unpack raw counts ───────────────────────────────────────────
      const [rawAal3Count, aal3Err] = unwrapSettled(rawResult, [0, true])
      const [rawMacro96Count, macro96Err] = unwrapSettled(macroResult, [0, true])
      const [candidateCount, candErr] = unwrapSettled(candResult, [0, true])
      if (aal3Err || macro96Err || candErr) {
        hasApiError = true
        warnings.push('raw/candidate count partial failure')
      }

      // ── Candidate summary ───────────────────────────────────────────
      const [candidateRulePassed, candidatePending, summaryErr] = unwrapSettled(summaryResult, [0, 0, true])
      if (summaryErr) warnings.push('candidate summary unavailable')

      // ── Mirror KG core ─────────────────────────────────────────────
      const [mirrorConnections, mcErr] = unwrapSettled(mcResult, [0, true])
      const [mirrorFunctions, mfErr] = unwrapSettled(mfResult, [0, true])
      const [mirrorCircuits, mciErr] = unwrapSettled(mciResult, [0, true])
      const [mirrorTriples, mtErr] = unwrapSettled(mtResult, [0, true])
      if (mcErr || mfErr || mciErr || mtErr) {
        hasApiError = true
        warnings.push('mirror KG count partial failure')
      }

      // ── Mirror KG macro clinical ──────────────────────────────────
      const [macroCircuitSteps, csErr] = unwrapSettled(csResult, [0, true])
      const [macroProjectionFunctions, pfErr] = unwrapSettled(pfResult, [0, true])
      const [macroMemberships, memErr] = unwrapSettled(memResult, [0, true])
      const [macroCrossResults, cvErr] = unwrapSettled(cvResult, [0, true])
      const [macroDualResults, dmErr] = unwrapSettled(dmResult, [0, true])
      if (csErr || pfErr || memErr || cvErr || dmErr) {
        hasApiError = true
        warnings.push('macro clinical count partial failure')
      }

      // ── Final KG ──────────────────────────────────────────────────
      const [finalCircuits, fcErr] = unwrapSettled(fcResult, [0, true])
      const [finalProjections, fpErr] = unwrapSettled(fpResult, [0, true])
      const [finalSteps, fsErr] = unwrapSettled(fsResult, [0, true])
      const [finalFunctions, ffErr] = unwrapSettled(ffResult, [0, true])
      const [finalTriples, ftErr] = unwrapSettled(ftResult, [0, true])
      if (fcErr || fpErr || fsErr || ffErr || ftErr) {
        hasApiError = true
        warnings.push('final KG count partial failure')
      }

      // ── Export count ──────────────────────────────────────────────
      const [exportCount, latestExportId, exportErr] = unwrapSettled(exportResult, [0, null, true])
      if (exportErr) {
        hasApiError = true
        warnings.push('export list unavailable')
      }

      if (abortRef.current) return

      setCounts({
        rawAal3Count,
        rawMacro96Count,
        candidateCount,
        candidateRulePassed,
        candidatePending,
        mirrorConnections,
        mirrorFunctions,
        mirrorCircuits,
        mirrorTriples,
        macroCircuitSteps,
        macroProjectionFunctions,
        macroMemberships,
        macroCrossResults,
        macroDualResults,
        finalCircuits,
        finalProjections,
        finalSteps,
        finalFunctions,
        finalTriples,
        exportCount,
        latestExportId,
        hasApiError,
        warnings,
      })
      setLoading(false)
    }

    load().catch(() => {
      if (!abortRef.current) setLoading(false)
    })

    return () => { abortRef.current = true }
  }, [tick, refreshKey, granularity])

  return { counts, loading, refresh }
}

/** Extract value from PromiseSettledResult, falling back to default on rejection. */
function unwrapSettled<T>(result: PromiseSettledResult<T>, fallback: T): T {
  if (result.status === 'fulfilled') return result.value
  return fallback
}
