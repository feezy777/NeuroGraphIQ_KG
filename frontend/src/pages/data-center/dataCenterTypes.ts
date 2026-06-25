export type DataCenterTabId =
  | 'overview'
  | 'raw'
  | 'candidates'
  | 'mirror'
  | 'macro'
  | 'final'
  | 'exports'

export type RawDataSubTab = 'aal3' | 'macro96'
export type MirrorKgSubTab = 'connections' | 'functions' | 'circuits' | 'triples' | 'evidence'
export type MacroClinicalSubTab =
  | 'circuit_steps'
  | 'projection_functions'
  | 'memberships'
  | 'circuit_functions'
  | 'cross_validation'
  | 'dual_model'
export type FinalKgSubTab =
  | 'circuit'
  | 'circuit_step'
  | 'projection'
  | 'projection_function'
  | 'membership'
  | 'region_function'
  | 'circuit_function'
  | 'triple'
  | 'evidence'

export interface DataCenterCounts {
  rawAal3Count: number
  rawMacro96Count: number
  candidateCount: number
  candidateRulePassed: number
  candidatePending: number
  mirrorConnections: number
  mirrorFunctions: number
  mirrorCircuits: number
  mirrorTriples: number
  macroCircuitSteps: number
  macroProjectionFunctions: number
  macroMemberships: number
  macroCrossResults: number
  macroDualResults: number
  finalCircuits: number
  finalProjections: number
  finalSteps: number
  finalFunctions: number
  finalTriples: number
  exportCount: number
  latestExportId: string | null
  hasApiError: boolean
  warnings: string[]
}

export interface DataCenterNavState {
  tab: DataCenterTabId
  rawTab: RawDataSubTab
  mirrorTab: MirrorKgSubTab
  macroTab: MacroClinicalSubTab
  finalTab: FinalKgSubTab
  batchId: string
  resourceId: string
  sourceAtlas: string
  granularityLevel: string
}

export const DATA_CENTER_TABS: DataCenterTabId[] = [
  'overview',
  'raw',
  'candidates',
  'mirror',
  'macro',
  'final',
  'exports',
]

export const DEFAULT_NAV: DataCenterNavState = {
  tab: 'overview',
  rawTab: 'aal3',
  mirrorTab: 'connections',
  macroTab: 'circuit_steps',
  finalTab: 'circuit',
  batchId: '',
  resourceId: '',
  sourceAtlas: '',
  granularityLevel: '',
}
