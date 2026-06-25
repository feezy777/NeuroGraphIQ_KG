import type { FormalObjectType } from './formalFieldMappings'

export type CircuitBundleSource = 'data_center' | 'extraction_result'

export type BundleGroupStatus =
  | 'pending'
  | 'running'
  | 'dry_run_done'
  | 'executed'
  | 'skipped'
  | 'no_data'
  | 'failed'
  | 'unavailable'

export interface CircuitBundleTargetGroup {
  targetType: FormalObjectType
  label: string
  targetIds: string[]
  formalObjectType: FormalObjectType
  status?: BundleGroupStatus
  unavailableReason?: string
  warnings?: string[]
}

export interface CircuitBundleFieldCompletionGroup {
  bundleType: 'circuit_bundle'
  label: string
  groups: CircuitBundleTargetGroup[]
  source: CircuitBundleSource
}
