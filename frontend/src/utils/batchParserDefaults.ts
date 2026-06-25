import type { AtlasResource } from '../api/endpoints'

export interface BatchParserDefaults {
  batchType: string
  parserKey: string
  fileRoleInBatch: string
  parserLabel: string
  parserDescription: string
}

export function isAal3Resource(resource: AtlasResource | null | undefined): boolean {
  if (!resource) return false
  const atlas = resource.source_atlas?.toUpperCase() ?? ''
  const code = resource.resource_code?.toLowerCase() ?? ''
  return atlas === 'AAL3' || code.includes('aal3')
}

export function isMacro96Resource(resource: AtlasResource | null | undefined): boolean {
  if (!resource) return false
  const atlas = resource.source_atlas?.toUpperCase() ?? ''
  const code = resource.resource_code?.toLowerCase() ?? ''
  const en = (resource.en_name ?? '').toLowerCase()
  const cn = resource.cn_name ?? ''
  return (
    atlas === 'MACRO96'
    || code.includes('macro96')
    || en.includes('macro 96')
    || cn.includes('96脑区')
  )
}

export function inferBatchDefaultsFromResource(
  resource: AtlasResource | null | undefined,
): BatchParserDefaults {
  if (isAal3Resource(resource)) {
    return {
      batchType: 'atlas_import',
      parserKey: 'aal3_xml',
      fileRoleInBatch: 'label_dictionary',
      parserLabel: 'AAL3 XML',
      parserDescription: 'Parse AAL3 XML label dictionary files.',
    }
  }

  if (isMacro96Resource(resource)) {
    return {
      batchType: 'atlas_import',
      parserKey: 'macro96_xlsx',
      fileRoleInBatch: 'macro_region_pool_source',
      parserLabel: 'Macro96 Excel',
      parserDescription: 'Parse Brain volume list.xlsx Macro96 standard pool files.',
    }
  }

  return {
    batchType: 'atlas_import',
    parserKey: '',
    fileRoleInBatch: 'unknown',
    parserLabel: 'Unconfigured',
    parserDescription: 'Select a resource and compatible file, then configure parser.',
  }
}
