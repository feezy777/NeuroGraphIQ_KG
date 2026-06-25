import type { ResourceFile } from '../api/endpoints'

function fileExt(f: ResourceFile): string {
  const name = f.original_filename.toLowerCase()
  if (name.endsWith('.nii.gz')) return '.nii.gz'
  const ext = (f.file_ext ?? '').toLowerCase()
  if (ext === '.nii.gz' || name.endsWith('.nii.gz')) return '.nii.gz'
  if (ext) return ext.startsWith('.') ? ext : `.${ext}`
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot) : ''
}

const INCOMPATIBLE_EXT = new Set([
  '.xlsx', '.xls', '.pdf', '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.nii', '.nii.gz',
])

const INCOMPATIBLE_TYPES = new Set(['spreadsheet', 'pdf', 'binary_metadata', 'image'])

const INCOMPATIBLE_INTERMEDIATE = new Set([
  'macro_region_table', 'spreadsheet_workbook', 'pdf_metadata', 'tabular_data',
  'text_document', 'image_metadata', 'nifti_metadata', 'binary_metadata',
])

export function assessAal3XmlParserCompatibility(
  f: ResourceFile,
  fileRoleInBatch = 'label_dictionary',
): { compatible: boolean; reason: string | null } {
  const ext = fileExt(f)

  if (INCOMPATIBLE_EXT.has(ext)) {
    if (ext === '.xlsx' || ext === '.xls') {
      return { compatible: false, reason: 'xlsx file cannot be parsed by aal3_xml parser' }
    }
    if (ext === '.pdf') {
      return { compatible: false, reason: 'pdf file cannot be parsed by aal3_xml parser' }
    }
    return { compatible: false, reason: `${ext} file cannot be parsed by aal3_xml parser` }
  }

  if (INCOMPATIBLE_TYPES.has(f.file_type)) {
    if (f.file_type === 'spreadsheet') {
      return { compatible: false, reason: 'spreadsheet file cannot be parsed by aal3_xml parser' }
    }
    if (f.file_type === 'pdf') {
      return { compatible: false, reason: 'pdf file cannot be parsed by aal3_xml parser' }
    }
    return { compatible: false, reason: `file_type=${f.file_type} is not compatible with aal3_xml parser` }
  }

  const kind = f.latest_intermediate_kind
  if (kind && INCOMPATIBLE_INTERMEDIATE.has(kind)) {
    return {
      compatible: false,
      reason: `intermediate artifact_kind=${kind} is not compatible with aal3_xml parser`,
    }
  }

  if (kind === 'label_table' && f.intermediate_status === 'ready') {
    return { compatible: true, reason: null }
  }

  if (ext === '.xml') {
    if (
      f.file_type === 'label_table'
      || fileRoleInBatch === 'label_dictionary'
      || f.file_role === 'label_dictionary'
    ) {
      return { compatible: true, reason: null }
    }
    return { compatible: false, reason: 'xml file is not configured as label_table / label_dictionary' }
  }

  if (['.txt', '.csv', '.tsv'].includes(ext)) {
    return {
      compatible: false,
      reason: `${ext} file cannot be parsed by aal3_xml parser; use AAL3 XML label dictionary`,
    }
  }

  return { compatible: false, reason: 'no AAL3 XML label dictionary source found for this file' }
}

export function isAal3XmlCompatibleFile(f: ResourceFile, fileRoleInBatch?: string): boolean {
  return assessAal3XmlParserCompatibility(f, fileRoleInBatch).compatible
}

export function isAal3XmlParserKey(parserKey: string | undefined | null): boolean {
  return (parserKey ?? '').trim() === 'aal3_xml'
}
