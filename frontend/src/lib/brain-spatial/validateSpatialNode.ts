/**
 * validateSpatialNode.ts — Validate spatial node data integrity.
 */
import { isValidMniPoint, verifyRoundTrip } from './mniSceneTransform'
import type { BrainRegionNode } from './brain3d.types'

export interface ValidationResult {
  valid: boolean
  errors: string[]
}

export function validateBrainRegionNode(node: BrainRegionNode): ValidationResult {
  const errors: string[] = []

  if (!node.region_id) {
    errors.push('Missing region_id')
  }
  if (!isValidMniPoint(node.representative_point_mni)) {
    errors.push(`Invalid or missing representative_point_mni`)
  } else if (!verifyRoundTrip(node.representative_point_mni)) {
    errors.push(`MNI→Scene→MNI round-trip failed`)
  }
  if (node.mapping_status !== 'verified_exact' && node.mapping_status !== 'verified_alias') {
    errors.push(`Mapping status "${node.mapping_status}" is not plottable`)
  }

  return { valid: errors.length === 0, errors }
}

export function validateAllNodes(nodes: BrainRegionNode[]): {
  valid: number
  invalid: number
  uniqueRegionIds: number
  duplicateIds: string[]
  errors: string[]
} {
  const errors: string[] = []
  let valid = 0
  let invalid = 0
  const seen = new Set<string>()
  const duplicateIds: string[] = []

  for (const node of nodes) {
    if (seen.has(node.region_id)) {
      duplicateIds.push(node.region_id)
    }
    seen.add(node.region_id)

    const result = validateBrainRegionNode(node)
    if (result.valid) {
      valid++
    } else {
      invalid++
      errors.push(`${node.name_en || node.region_id}: ${result.errors.join('; ')}`)
    }
  }

  return { valid, invalid, uniqueRegionIds: seen.size, duplicateIds, errors }
}
