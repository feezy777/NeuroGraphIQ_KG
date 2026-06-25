import type { ResourceFile } from '../api/endpoints'
import {
  assessAal3XmlParserCompatibility,
  isAal3XmlCompatibleFile,
  isAal3XmlParserKey,
} from './aal3ParserCompatibility'
import {
  assessMacro96XlsxParserCompatibility,
  isMacro96XlsxCompatibleFile,
  isMacro96XlsxParserKey,
} from './macro96ParserCompatibility'

export interface FileParserCompatibility {
  compatible: boolean
  reason?: string
  warning?: string
}

export function getFileParserCompatibility(
  file: ResourceFile,
  parserKey: string,
  fileRoleInBatch?: string,
): FileParserCompatibility {
  if (isAal3XmlParserKey(parserKey)) {
    const { compatible, reason } = assessAal3XmlParserCompatibility(file, fileRoleInBatch)
    return { compatible, reason: reason ?? undefined }
  }
  if (isMacro96XlsxParserKey(parserKey)) {
    const { compatible, reason, warning } = assessMacro96XlsxParserCompatibility(file)
    return { compatible, reason: reason ?? undefined, warning: warning ?? undefined }
  }
  return { compatible: true }
}

export function isParserCompatibleFile(
  file: ResourceFile,
  parserKey: string,
  fileRoleInBatch?: string,
): boolean {
  if (isAal3XmlParserKey(parserKey)) {
    return isAal3XmlCompatibleFile(file, fileRoleInBatch)
  }
  if (isMacro96XlsxParserKey(parserKey)) {
    return isMacro96XlsxCompatibleFile(file)
  }
  return true
}

export { isAal3XmlParserKey, isMacro96XlsxParserKey }
