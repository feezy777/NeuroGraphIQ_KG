import { useI18n } from '../../i18n-context'
import type { FormalFieldMapping } from './formalFieldMappings'
import { computeCompleteness, computeMissingFields } from './formalFieldMappings'

interface Props {
  mapping: FormalFieldMapping
  items: Record<string, unknown>[]
  /** Total object count from API (not just current page). Falls back to items.length. */
  total?: number
  /** Current granularity level for schema display */
  granularityLevel?: string
}

/** Map granularity_level to the formal DB schema name. */
function granularityToFormalSchema(granularityLevel?: string): string {
  switch (granularityLevel) {
    case 'macro': return 'macro_clinical'
    case 'meso': return 'meso_anatomical'
    case 'micro': return 'sub_connectivity'
    case 'molecular_attr': return 'molecular_attr'
    case 'fine_cyto': return 'fine_cyto'
    case 'term': return 'terminology'
    default: return 'macro_clinical'
  }
}

/** Build a granularity-aware qualified table name (e.g. 'molecular_attr.projection'). */
function granularityQualifiedName(mapping: FormalFieldMapping, granularityLevel?: string): string {
  const schema = granularityToFormalSchema(granularityLevel)
  const table = mapping.finalTable || mapping.targetType
  return `${schema}.${table}`
}

export function FormalAlignmentCard({ mapping, items, total, granularityLevel }: Props) {
  const { t } = useI18n()
  const completeness = computeCompleteness(items, mapping)
  const totalMissing = items.reduce(
    (sum, item) => sum + computeMissingFields(item, mapping).length,
    0,
  )

  const displaySchema = mapping.formalSchema
    ? granularityToFormalSchema(granularityLevel || mapping.formalSchema)
    : '—'
  const displayQualifiedName = mapping.formalQualifiedName
    ? granularityQualifiedName(mapping, granularityLevel)
    : '—'
  const displayTotal = total ?? items.length

  return (
    <div className="data-center-formal-card">
      <div className="data-center-formal-summary">
        <div className="data-center-formal-summary-row">
          <span className="data-center-formal-summary-label">{t('dataCenter.mirrorSourceTable')}</span>
          <code>{mapping.mirrorTable}</code>
        </div>
        <div className="data-center-formal-summary-row">
          <span className="data-center-formal-summary-label">{t('dataCenter.formalDatabase')}</span>
          <code>NeuroGraphIQ_KG_V3</code>
        </div>
        {displaySchema !== '—' && (
          <div className="data-center-formal-summary-row">
            <span className="data-center-formal-summary-label">{t('dataCenter.formalSchema')}</span>
            <code>{displaySchema}</code>
          </div>
        )}
        <div className="data-center-formal-summary-row">
          <span className="data-center-formal-summary-label">{t('dataCenter.formalQualifiedName')}</span>
          <code>{displayQualifiedName}</code>
        </div>
        <div className="data-center-formal-summary-row">
          <span className="data-center-formal-summary-label">{t('dataCenter.objectCount')}</span>
          <strong>{displayTotal}</strong>
        </div>
        <div className="data-center-formal-summary-row">
          <span className="data-center-formal-summary-label">{t('dataCenter.completeness')}</span>
          <strong>{completeness}%</strong>
        </div>
        <div className="data-center-formal-summary-row">
          <span className="data-center-formal-summary-label">{t('dataCenter.missingFormalFields')}</span>
          <strong>{totalMissing}</strong>
        </div>
      </div>
      <p className="data-center-formal-notice">{t('dataCenter.notWrittenToFormalDb')}</p>
    </div>
  )
}
