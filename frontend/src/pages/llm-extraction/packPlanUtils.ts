/**
 * Pack plan utilities — compute pack counts, sizes, and previews.
 */

import type { TaskPreset } from './taskPresets'

// ── Pool member helpers ────────────────────────────────────────────────────

export interface RegionPoolInput {
  localMembers?: Array<{ candidate_id: string }>
  pool?: { memberships?: Array<{ candidate_id: string }> } | null
  candidateIds?: string[]
}

/** Get all unique, non-empty region pool member IDs in stable order. */
export function getRegionPoolMemberIds(input: RegionPoolInput): string[] {
  const seen = new Set<string>()
  const result: string[] = []

  // Priority: localMembers → pool.memberships → candidateIds
  const sources: string[][] = [
    (input.localMembers ?? []).map(m => m.candidate_id),
    (input.pool?.memberships ?? []).map(m => m.candidate_id),
    input.candidateIds ?? [],
  ]

  for (const ids of sources) {
    for (const id of ids) {
      if (id && !seen.has(id)) {
        seen.add(id)
        result.push(id)
      }
    }
  }

  console.debug('[pool-pack-plan][members]', {
    localMembersLength: input.localMembers?.length ?? 0,
    poolMembershipsLength: input.pool?.memberships?.length ?? 0,
    candidateIdsLength: input.candidateIds?.length ?? 0,
    resultLength: result.length,
  })

  return result
}

// ── Pack plan preview ──────────────────────────────────────────────────────

export interface PackPlanInput {
  preset?: TaskPreset | null
  candidateCount: number
  candidatesPerPack: number
  shuffleRounds: number
  pairsPerPack?: number
}

export interface PackPlanPreview {
  input_count: number
  candidates_per_pack: number
  shuffle_rounds: number
  pack_strategy: string | undefined
  round_count: number
  pack_count: number
  pack_sizes: number[]
  pair_count?: number
  warnings: string[]
}

export function buildPackPlanPreview(input: PackPlanInput): PackPlanPreview {
  const { preset, candidateCount, candidatesPerPack, shuffleRounds } = input
  const warnings: string[] = []
  const strategy = preset?.pack_strategy

  // ── Connection pool: graph-aware connection pack for circuit ──────────────
  if (preset?.input_pool_type === 'connection_pool') {
    const ppk = Math.max(5, candidatesPerPack || 5)
    const packCount = Math.max(1, Math.ceil(candidateCount / ppk))
    const sizes: number[] = []
    for (let i = 0; i < packCount; i++) {
      const start = i * ppk
      sizes.push(Math.min(ppk, candidateCount - start))
    }
    return {
      input_count: candidateCount,
      candidates_per_pack: ppk,
      shuffle_rounds: 1,
      pack_strategy: strategy || 'graph_aware_connection_pack_for_circuit',
      round_count: 1,
      pack_count: packCount,
      pack_sizes: sizes,
      warnings: candidateCount > 200 ? [`连接数较多 (${candidateCount})，建议筛选后再提取`] : [],
    }
  }

  // ── Pair pack from region pool (connection extraction) ───────────────────
  if (strategy === 'pair_pack' || preset?.target === 'connection') {
    const pairCount = candidateCount * (candidateCount - 1) / 2
    const ppk = input.pairsPerPack ?? 30
    const packCount = Math.ceil(pairCount / ppk)
    return {
      input_count: candidateCount,
      candidates_per_pack: candidatesPerPack,
      shuffle_rounds: shuffleRounds,
      pack_strategy: 'pair_pack_from_region_pool',
      round_count: 1,
      pack_count: packCount,
      pack_sizes: Array(packCount).fill(ppk).map((s, i) => i === packCount - 1 ? pairCount - s * (packCount - 1) : s),
      pair_count: pairCount,
      warnings: candidateCount > 50 ? [`候选脑区较多 (${candidateCount})，pair 数量=${pairCount}，建议减少候选`] : [],
    }
  }

  // ── Multi-round region shuffle (circuit extraction) ──────────────────────
  if (strategy === 'multi_round_region_shuffle_for_circuit') {
    const perRound = Math.ceil(candidateCount / candidatesPerPack)
    const totalPacks = perRound * shuffleRounds
    const sizes: number[] = []
    for (let r = 0; r < shuffleRounds; r++) {
      for (let i = 0; i < perRound; i++) {
        const start = i * candidatesPerPack
        sizes.push(Math.min(candidatesPerPack, candidateCount - start))
      }
    }
    return {
      input_count: candidateCount,
      candidates_per_pack: candidatesPerPack,
      shuffle_rounds: shuffleRounds,
      pack_strategy: strategy,
      round_count: shuffleRounds,
      pack_count: totalPacks,
      pack_sizes: sizes,
      warnings: totalPacks > 50 ? [`总包数较多 (${totalPacks})，费用可能较高`] : [],
    }
  }

  // ── Simple region pack (function extraction) ────────────────────────────
  const packCount = Math.ceil(candidateCount / candidatesPerPack)
  const sizes: number[] = []
  for (let i = 0; i < packCount; i++) {
    const start = i * candidatesPerPack
    sizes.push(Math.min(candidatesPerPack, candidateCount - start))
  }
  return {
    input_count: candidateCount,
    candidates_per_pack: candidatesPerPack,
    shuffle_rounds: 1,
    pack_strategy: strategy || 'region_pack',
    round_count: 1,
    pack_count: packCount,
    pack_sizes: sizes,
    warnings: [],
  }
}

// ── Pack config payload (passed to next step) ──────────────────────────────

export interface PackConfigPayload {
  preset_id: string
  pool_type: string
  pool_id?: string | null
  candidate_ids: string[]
  candidates_per_pack: number
  shuffle_rounds: number
  pack_strategy?: string
  estimated_pack_count: number
}

export function buildPackConfigPayload(input: {
  preset: TaskPreset | null
  poolId?: string | null
  candidateIds: string[]
  candidatesPerPack: number
  shuffleRounds: number
  packPlan: PackPlanPreview
}): PackConfigPayload {
  return {
    preset_id: input.preset?.preset_id ?? '',
    pool_type: input.preset?.input_pool_type ?? 'region_pool',
    pool_id: input.poolId ?? null,
    candidate_ids: input.candidateIds,
    candidates_per_pack: input.candidatesPerPack,
    shuffle_rounds: input.shuffleRounds,
    pack_strategy: input.packPlan.pack_strategy,
    estimated_pack_count: input.packPlan.pack_count,
  }
}

export function logPackPlanNext(payload: PackConfigPayload) {
  console.log('[pool-pack-plan][next]', {
    preset_id: payload.preset_id,
    input_pool_type: payload.pool_type,
    candidate_count: payload.candidate_ids.length,
    candidates_per_pack: payload.candidates_per_pack,
    shuffle_rounds: payload.shuffle_rounds,
    pack_strategy: payload.pack_strategy,
    estimated_pack_count: payload.estimated_pack_count,
    candidate_ids_preview: payload.candidate_ids.slice(0, 3).map(id => id.slice(0, 8)),
  })
}
