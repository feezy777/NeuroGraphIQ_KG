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
  '.xml', '.pdf', '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.nii', '.nii.gz',
])

const INCOMPATIBLE_TYPES = new Set(['label_table', 'pdf', 'binary_metadata', 'image', 'nifti'])

const INCOMPATIBLE_INTERMEDIATE = new Set([
  'label_table', 'pdf_metadata', 'text_document', 'image_metadata', 'nifti_metadata', 'binary_metadata',
])

export function assessMacro96XlsxParserCompatibility(
  f: ResourceFile,
): { compatible: boolean; reason: string | null; warning: string | null } {
  const ext = fileExt(f)
  const name = f.original_filename.toLowerCase()

  if (INCOMPATIBLE_EXT.has(ext)) {
    if (ext === '.xml') {
      return {
        compatible: false,
        reason: 'AAL3 XML label dictionary cannot use macro96_xlsx parser',
        warning: null,
      }
    }
    return {
      compatible: false,
      reason: `${ext} file is not a Macro96 Excel standard pool source`,
      warning: null,
    }
  }

  if (INCOMPATIBLE_TYPES.has(f.file_type)) {
    if (f.file_type === 'label_table') {
      return {
        compatible: false,
        reason: 'AAL3 XML label dictionary cannot use macro96_xlsx parser',
        warning: null,
      }
    }
    return {
      compatible: false,
      reason: `file_type=${f.file_type} is not compatible with macro96_xlsx parser`,
      warning: null,
    }
  }

  const kind = f.latest_intermediate_kind
  if (kind && INCOMPATIBLE_INTERMEDIATE.has(kind)) {
    return {
      compatible: false,
      reason: `intermediate artifact_kind=${kind} is not compatible with macro96_xlsx parser`,
      warning: null,
    }
  }

  if (kind === 'macro_region_table' && f.intermediate_status === 'ready') {
    return { compatible: true, reason: null, warning: null }
  }

  if (ext === '.xlsx' || ext === '.xls' || f.file_type === 'spreadsheet') {
    if (f.file_role === 'macro_region_pool_source' || name.includes('brain volume')) {
      const warning =
        f.intermediate_status !== 'ready' || kind !== 'macro_region_table'
          ? 'macro_region_table intermediate not ready; normalize in Files first if possible'
          : null
      return { compatible: true, reason: null, warning }
    }
    return {
      compatible: true,
      reason: null,
      warning:
        f.intermediate_status !== 'ready' || kind !== 'macro_region_table'
          ? 'macro_region_table intermediate not ready; normalize in Files first if possible'
          : null,
    }
  }

  return {
    compatible: false,
    reason: 'no Macro96 Excel standard pool source found for this file',
    warning: null,
  }
}

export function isMacro96XlsxCompatibleFile(f: ResourceFile): boolean {
  return assessMacro96XlsxParserCompatibility(f).compatible
}

export function isMacro96XlsxParserKey(parserKey: string | undefined | null): boolean {
  return (parserKey ?? '').trim() === 'macro96_xlsx'
}
