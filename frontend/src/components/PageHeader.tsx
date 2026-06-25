import React from 'react'
import { Lock } from 'lucide-react'
import { useI18n } from '../i18n-context'

interface PageHeaderProps {
  title: string
  description?: string
  actions?: React.ReactNode
  readonly?: boolean
}

export function PageHeader({ title, description, actions, readonly: ro = true }: PageHeaderProps) {
  const { t } = useI18n()

  return (
    <div className="page-header">
      <div>
        <h1 className="page-title">{title}</h1>
        {description && <p className="page-desc">{description}</p>}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {ro && (
          <span className="readonly-notice">
            <Lock size={10} />
            {t('common.readonly')}
          </span>
        )}
        {actions}
      </div>
    </div>
  )
}
