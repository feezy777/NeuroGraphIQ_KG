import type { AtlasResource, ResourceOptions } from '../api/endpoints'

export type ResourceGranularityKey =
  | 'macro'
  | 'meso'
  | 'micro'
  | 'molecular'
  | 'term'

export const GRANULARITY_STORAGE_KEY = 'neurographiq.resources.activeGranularity'

export const GRANULARITY_KEYS: ResourceGranularityKey[] = [
  'macro',
  'meso',
  'micro',
  'molecular',
  'term',
]

export interface GranularityConfig {
  key: ResourceGranularityKey
  labelKey: string
  subtitleKey: string
  titleKey: string
  descriptionKey: string
  granularity_level: string
  recommended_families: string[]
  recommended_atlases: string[]
  default_resource_code: string
  default_source_atlas: string
  default_source_version: string
  default_resource_type: string
  default_species: string
  default_granularity_family: string
  default_template_space: string
  default_cn_name: string
  default_en_name: string
}

export const RESOURCE_GRANULARITY_CONFIG: Record<ResourceGranularityKey, GranularityConfig> = {
  macro: {
    key: 'macro',
    labelKey: 'resources.granularityTabs.macro',
    subtitleKey: 'resources.granularityTabs.macroSubtitle',
    titleKey: 'resources.granularityInfo.macroTitle',
    descriptionKey: 'resources.granularityInfo.macroDescription',
    granularity_level: 'macro',
    recommended_families: ['macro_clinical'],
    recommended_atlases: ['AAL3', 'Macro96'],
    default_resource_code: 'aal3_v1_macro',
    default_source_atlas: 'AAL3',
    default_source_version: 'v1',
    default_resource_type: 'atlas',
    default_species: 'human',
    default_granularity_family: 'macro_clinical',
    default_template_space: 'MNI152',
    default_cn_name: 'AAL3 宏观脑区图谱 V1',
    default_en_name: 'AAL3 Macro Atlas V1',
  },
  meso: {
    key: 'meso',
    labelKey: 'resources.granularityTabs.meso',
    subtitleKey: 'resources.granularityTabs.mesoSubtitle',
    titleKey: 'resources.granularityInfo.mesoTitle',
    descriptionKey: 'resources.granularityInfo.mesoDescription',
    granularity_level: 'meso',
    recommended_families: ['meso_anatomical'],
    recommended_atlases: ['HCP-MMP', 'Desikan', 'Destrieux'],
    default_resource_code: 'hcp_mmp_v1_meso',
    default_source_atlas: 'HCP-MMP',
    default_source_version: 'v1',
    default_resource_type: 'atlas',
    default_species: 'human',
    default_granularity_family: 'meso_anatomical',
    default_template_space: 'fsaverage',
    default_cn_name: 'HCP-MMP 中观解剖图谱 V1',
    default_en_name: 'HCP-MMP Meso Anatomical Atlas V1',
  },
  micro: {
    key: 'micro',
    labelKey: 'resources.granularityTabs.micro',
    subtitleKey: 'resources.granularityTabs.microSubtitle',
    titleKey: 'resources.granularityInfo.microTitle',
    descriptionKey: 'resources.granularityInfo.microDescription',
    granularity_level: 'micro',
    recommended_families: ['subregion_connectivity', 'cytoarchitectonic', 'histological'],
    recommended_atlases: ['Brainnetome', 'Julich-Brain', 'BigBrain'],
    default_resource_code: 'brainnetome_v1_micro',
    default_source_atlas: 'Brainnetome',
    default_source_version: 'v1',
    default_resource_type: 'atlas',
    default_species: 'human',
    default_granularity_family: 'subregion_connectivity',
    default_template_space: 'MNI152',
    default_cn_name: 'Brainnetome 微观亚区图谱 V1',
    default_en_name: 'Brainnetome Micro Subregion Atlas V1',
  },
  molecular: {
    key: 'molecular',
    labelKey: 'resources.granularityTabs.molecular',
    subtitleKey: 'resources.granularityTabs.molecularSubtitle',
    titleKey: 'resources.granularityInfo.molecularTitle',
    descriptionKey: 'resources.granularityInfo.molecularDescription',
    granularity_level: 'molecular',
    recommended_families: ['molecular'],
    recommended_atlases: ['Allen Human Brain Atlas'],
    default_resource_code: 'allen_human_brain_atlas_molecular',
    default_source_atlas: 'Allen Human Brain Atlas',
    default_source_version: 'unknown',
    default_resource_type: 'atlas',
    default_species: 'human',
    default_granularity_family: 'molecular',
    default_template_space: 'unknown',
    default_cn_name: 'Allen 人脑分子图谱',
    default_en_name: 'Allen Human Brain Atlas Molecular',
  },
  term: {
    key: 'term',
    labelKey: 'resources.granularityTabs.term',
    subtitleKey: 'resources.granularityTabs.termSubtitle',
    titleKey: 'resources.granularityInfo.termTitle',
    descriptionKey: 'resources.granularityInfo.termDescription',
    granularity_level: 'term',
    recommended_families: ['terminology'],
    recommended_atlases: ['InterLex', 'BrainInfo', 'UBERON', 'FMA'],
    default_resource_code: 'interlex_terms',
    default_source_atlas: 'InterLex',
    default_source_version: 'unknown',
    default_resource_type: 'ontology',
    default_species: 'human',
    default_granularity_family: 'terminology',
    default_template_space: 'not_applicable',
    default_cn_name: 'InterLex 术语本体',
    default_en_name: 'InterLex Terminology',
  },
}

export function normalizeGranularityKey(value: unknown): ResourceGranularityKey {
  if (typeof value === 'string' && value in RESOURCE_GRANULARITY_CONFIG) {
    return value as ResourceGranularityKey
  }
  return 'macro'
}

export function getStoredGranularityKey(): ResourceGranularityKey {
  if (typeof window === 'undefined') return 'macro'
  return normalizeGranularityKey(window.localStorage.getItem(GRANULARITY_STORAGE_KEY))
}

export function saveGranularityKey(key: ResourceGranularityKey): void {
  window.localStorage.setItem(GRANULARITY_STORAGE_KEY, key)
}

function pickAllowed(preferred: string, allowed: string[], fallback?: string): string {
  if (allowed.includes(preferred)) return preferred
  if (fallback && allowed.includes(fallback)) return fallback
  return allowed[0] ?? preferred
}

export function filterFamiliesForGranularity(
  config: GranularityConfig,
  options: ResourceOptions,
  showAll: boolean,
): string[] {
  if (showAll) return options.granularity_family
  const recommended = config.recommended_families.filter(f => options.granularity_family.includes(f))
  return recommended.length > 0 ? recommended : options.granularity_family
}

export interface ResourceFormDefaults {
  resource_code: string
  source_atlas: string
  source_version: string
  resource_type: string
  species: string
  granularity_level: string
  granularity_family: string
  template_space: string
  cn_name: string
  en_name: string
  description: string
  remark: string
  status: string
}

export function buildDefaultForm(
  key: ResourceGranularityKey,
  options: ResourceOptions,
): ResourceFormDefaults {
  const config = RESOURCE_GRANULARITY_CONFIG[key]
  return {
    resource_code: config.default_resource_code,
    source_atlas: config.default_source_atlas,
    source_version: config.default_source_version,
    resource_type: pickAllowed(config.default_resource_type, options.resource_type, 'atlas'),
    species: pickAllowed(config.default_species, options.species, 'human'),
    granularity_level: pickAllowed(config.granularity_level, options.granularity_level, config.granularity_level),
    granularity_family: pickAllowed(
      config.default_granularity_family,
      options.granularity_family,
      config.recommended_families[0],
    ),
    template_space: pickAllowed(config.default_template_space, options.template_space, 'unknown'),
    cn_name: config.default_cn_name,
    en_name: config.default_en_name,
    description: '',
    remark: '',
    status: pickAllowed('active', options.status, 'active'),
  }
}

// ── Macro tab resource presets (AAL3 vs Macro96 standard pool) ─────────────────

export type MacroResourcePresetKey = 'aal3' | 'macro96'

export interface MacroPresetFallbackFlags {
  standardPool?: boolean
  templateSpace?: boolean
}

export interface MacroPresetFormResult {
  form: ResourceFormDefaults
  fallbacks: MacroPresetFallbackFlags
}

const MACRO_PRESET_RAW: Record<
  MacroResourcePresetKey,
  Omit<ResourceFormDefaults, 'status'>
> = {
  aal3: {
    resource_code: 'aal3_v1_macro',
    source_atlas: 'AAL3',
    source_version: 'v1',
    resource_type: 'atlas',
    species: 'human',
    granularity_level: 'macro',
    granularity_family: 'macro_clinical',
    template_space: 'MNI152',
    cn_name: 'AAL3 宏观脑区图谱 V1',
    en_name: 'AAL3 Macro Atlas V1',
    description:
      'AAL3 宏观脑区图谱资源，用于导入 AAL3 XML label dictionary。AAL3 166 ROI 不等于 Macro 96 标准池，后续通过显式 mapping 与 Macro 96 关联。',
    remark: 'parser_key 建议使用 aal3_xml。',
  },
  macro96: {
    resource_code: 'macro96_standard_pool_v1',
    source_atlas: 'Macro96',
    source_version: 'v1',
    resource_type: 'standard_pool',
    species: 'human',
    granularity_level: 'macro',
    granularity_family: 'macro_clinical',
    template_space: 'not_applicable',
    cn_name: '宏观96脑区标准池 V1',
    en_name: 'Macro 96 Region Standard Pool V1',
    description:
      '导师整理的 96 脑区标准池，用于宏观临床层脑区名称标准化；不等同于 AAL3 166 ROI。后续应通过 explicit mapping 与 AAL3 建立 exact_match、close_match、part_of、overlaps 等关系。',
    remark:
      '文件来源建议上传 Brain volume list.xlsx；后续 parser_key 建议使用 macro96_xlsx。本资源是标准池资源，不应使用 aal3_xml parser。',
  },
}

export const MACRO_RESOURCE_PRESET_KEYS: MacroResourcePresetKey[] = ['aal3', 'macro96']

export const EMPTY_MACRO_PRESET_EXISTING: Partial<Record<MacroResourcePresetKey, AtlasResource>> = {}

export function normalizeMacroPresetKey(value: unknown): MacroResourcePresetKey {
  return value === 'macro96' ? 'macro96' : 'aal3'
}

export function buildMacroPresetExisting(
  items: AtlasResource[],
): Partial<Record<MacroResourcePresetKey, AtlasResource>> {
  const byCode = (code: string) => items.find(r => r.resource_code === code)
  return {
    aal3: byCode('aal3_v1_macro'),
    macro96: byCode('macro96_standard_pool_v1'),
  }
}

export function buildMacroPresetForm(
  presetKey: MacroResourcePresetKey,
  options: ResourceOptions,
): MacroPresetFormResult {
  const safeKey = normalizeMacroPresetKey(presetKey)
  const raw = MACRO_PRESET_RAW[safeKey]
  const fallbacks: MacroPresetFallbackFlags = {}

  let resource_type = raw.resource_type
  if (!options.resource_type.includes(resource_type)) {
    resource_type = options.resource_type.includes('atlas') ? 'atlas' : (options.resource_type[0] ?? 'atlas')
    if (safeKey === 'macro96') fallbacks.standardPool = true
  }

  let template_space = raw.template_space
  if (!options.template_space.includes(template_space)) {
    template_space = options.template_space.includes('unknown')
      ? 'unknown'
      : (options.template_space[0] ?? 'unknown')
    if (safeKey === 'macro96') fallbacks.templateSpace = true
  }

  return {
    form: {
      ...raw,
      resource_type,
      template_space,
      species: pickAllowed(raw.species, options.species, 'human'),
      granularity_level: pickAllowed(raw.granularity_level, options.granularity_level, 'macro'),
      granularity_family: pickAllowed(
        raw.granularity_family,
        options.granularity_family,
        'macro_clinical',
      ),
      status: pickAllowed('active', options.status, 'active'),
    },
    fallbacks,
  }
}

export function isMacro96Resource(row: { source_atlas: string; resource_code: string }): boolean {
  const atlas = row.source_atlas.trim().toLowerCase()
  const code = row.resource_code.trim().toLowerCase()
  return atlas.includes('macro96') || atlas.includes('macro 96') || code.includes('macro96')
}

export function isAal3AtlasResource(row: { source_atlas: string }): boolean {
  return row.source_atlas.trim().toUpperCase() === 'AAL3'
}
