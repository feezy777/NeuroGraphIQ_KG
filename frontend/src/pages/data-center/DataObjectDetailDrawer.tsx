import { CopyButton } from '../../components/CopyButton'
import { useI18n } from '../../i18n-context'

interface Props {
  open: boolean
  title: string
  subtitle?: string
  fields: Array<{ label: string; value: string | number | null | undefined }>
  onClose: () => void
  actions?: React.ReactNode
}

export function DataObjectDetailDrawer({ open, title, subtitle, fields, onClose, actions }: Props) {
  const { t } = useI18n()
  if (!open) return null

  return (
    <div className="data-center-detail-drawer">
      <div className="data-center-detail-backdrop" onClick={onClose} />
      <div className="data-center-detail-panel">
        <div className="data-center-panel-header">
          <div>
            <h3>{title}</h3>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button type="button" className="btn" onClick={onClose}>{t('llm.workflow.closeCandidateDetail')}</button>
        </div>
        <div className="data-center-object-card">
          {fields.map(f => (
            <div key={f.label} className="data-center-object-row">
              <span className="data-center-object-label">{f.label}</span>
              <span className="data-center-object-value">
                {f.value ?? '—'}
                {typeof f.value === 'string' && f.value.length > 8 && (
                  <CopyButton value={String(f.value)} label={t('dataCenter.copyId')} />
                )}
              </span>
            </div>
          ))}
        </div>
        {actions && <div className="data-center-quick-actions">{actions}</div>}
      </div>
    </div>
  )
}
