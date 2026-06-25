import { useI18n } from '../../i18n-context'
import type { FormalFieldMapping } from './formalFieldMappings'
import { computeCompleteness, computeMissingFields } from './formalFieldMappings'

interface Props {
  mapping: FormalFieldMapping
  items: Record<string, unknown>[]
}

export function FormalAlignmentCard({ mapping, items }: Props) {
  const { t } = useI18n()
  const completeness = computeCompleteness(items, mapping)
  const totalMissing = items.reduce(
    (sum, item) => sum + computeMissingFields(item, mapping).length,
    0,
  )

  const qualifiedName = mapping.formalQualifiedName || mapping.finalTable || '—'
  const schemaLabel = mapping.formalSchema || '—'

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
        {schemaLabel !== '—' && (
          <div className="data-center-formal-summary-row">
            <span className="data-center-formal-summary-label">{t('dataCenter.formalSchema')}</span>
            <code>{schemaLabel}</code>
          </div>
        )}
        <div className="data-center-formal-summary-row">
          <span className="data-center-formal-summary-label">{t('dataCenter.formalQualifiedName')}</span>
          <code>{qualifiedName}</code>
        </div>
        <div className="data-center-formal-summary-row">
          <span className="data-center-formal-summary-label">{t('dataCenter.objectCount')}</span>
          <strong>{items.length}</strong>
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
