import { useI18n } from '../../i18n-context'
import type { FormalFieldMapping } from './formalFieldMappings'

interface Props {
  open: boolean
  mapping: FormalFieldMapping
  selectedCount: number
  onClose: () => void
}

export function FieldCompletionPlaceholderModal({ open, mapping, selectedCount, onClose }: Props) {
  const { t } = useI18n()
  if (!open) return null

  return (
    <div className="data-center-field-completion-placeholder">
      <div className="data-center-field-completion-backdrop" onClick={onClose} />
      <div className="data-center-field-completion-panel">
        <h3>{t('dataCenter.fieldCompletionPlaceholderTitle')}</h3>
        <p>{t('dataCenter.fieldCompletionPlaceholderDesc')}</p>
        <ul className="data-center-field-completion-list">
          <li>
            <strong>{mapping.label}</strong> ({mapping.targetType})
          </li>
          <li>
            {t('dataCenter.fieldCompletionSelectedCount', { count: selectedCount })}
          </li>
          <li>{t('dataCenter.fieldCompletionUsesDeepSeek')}</li>
          <li>{t('dataCenter.fieldCompletionDefaultMissing')}</li>
          <li>{t('dataCenter.fieldCompletionMirrorOnly')}</li>
          <li>{t('dataCenter.fieldCompletionNextStep')}</li>
        </ul>
        <div className="data-center-field-completion-actions">
          <button type="button" className="btn btn-primary" onClick={onClose}>
            {t('dataCenter.fieldCompletionPreviewOk')}
          </button>
        </div>
      </div>
    </div>
  )
}
