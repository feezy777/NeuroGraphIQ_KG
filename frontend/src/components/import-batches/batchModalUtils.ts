import type { AtlasResource, ResourceFile } from '../../api/endpoints'
import { inferBatchDefaultsFromResource } from '../../utils/batchParserDefaults'
export function formatBytes(value: number | null | undefined): string {
  const size = value ?? 0
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}

export function formatResourceLabel(r: AtlasResource): string {
  return `${r.source_atlas} | ${r.resource_code} | ${r.source_version} | ${r.granularity_level} | ${r.status}`
}

export function formatFileOptionLabel(f: ResourceFile): string {
  const intSt = f.intermediate_status ?? 'unknown'
  const kind = f.latest_intermediate_kind ? ` | ${f.latest_intermediate_kind}` : ''
  return `${f.original_filename} | ${f.file_type} | ${f.file_role} | ${f.status} | ${intSt}${kind} | ${formatBytes(f.file_size)}`
}

export function isSpreadsheetFile(f: ResourceFile): boolean {
  const ext = (f.file_ext ?? '').toLowerCase()
  return ext === '.xlsx' || ext === '.xls' || f.file_type === 'spreadsheet'
}

export function isPdfFile(f: ResourceFile): boolean {
  const ext = (f.file_ext ?? '').toLowerCase()
  return ext === '.pdf' || f.file_type === 'pdf'
}

export function isAal3XmlFile(f: ResourceFile): boolean {
  const name = f.original_filename.toLowerCase()
  return f.file_type === 'label_table' && (f.file_ext?.toLowerCase() === '.xml' || name.endsWith('.xml'))
}

function isMacro96Resource(file: ResourceFile, resource: AtlasResource | undefined): boolean {
  if (file.file_role === 'macro_region_pool_source') return true
  if (file.latest_intermediate_kind === 'macro_region_table') return true
  return inferBatchDefaultsFromResource(resource ?? null).parserKey === 'macro96_xlsx'
}

export function deriveBatchDefaultsFromFile(resource: AtlasResource | undefined, file: ResourceFile | undefined) {
  const resourceDefaults = inferBatchDefaultsFromResource(resource ?? null)
  if (!file) return resourceDefaults

  if (isSpreadsheetFile(file) && isMacro96Resource(file, resource)) {
    return {
      batchType: resourceDefaults.batchType,
      parserKey: 'macro96_xlsx',
      fileRoleInBatch: 'macro_region_pool_source',
    }
  }

  if (isAal3XmlFile(file)) {
    return {
      batchType: 'atlas_import',
      parserKey: 'aal3_xml',
      fileRoleInBatch: 'label_dictionary',
    }
  }

  if (isSpreadsheetFile(file) || isPdfFile(file)) {
    return {
      batchType: resourceDefaults.batchType,
      parserKey: resourceDefaults.parserKey,
      fileRoleInBatch: file.file_role || resourceDefaults.fileRoleInBatch,
    }
  }

  return {
    batchType: resourceDefaults.batchType,
    parserKey: resourceDefaults.parserKey,
    fileRoleInBatch: resourceDefaults.fileRoleInBatch,
  }
}

export function formatFileRoleInBatchLabel(role: string, t: (key: string) => string): string {
  if (role === 'macro_region_pool_source') {
    return `${role} — ${t('batches.fileRoleMacroRegionPoolSource')}`
  }
  return role
}

export interface FileBindingRow {
  file_id: string
  file_role_in_batch: string
  sort_order: number
}

export function emptyBinding(): FileBindingRow {
  return { file_id: '', file_role_in_batch: 'label_dictionary', sort_order: 0 }
}
