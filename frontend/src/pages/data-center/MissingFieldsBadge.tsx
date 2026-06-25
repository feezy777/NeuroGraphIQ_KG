import { useI18n } from '../../i18n-context'

interface Props {
  missingFields: string[]
}

export function MissingFieldsBadge({ missingFields }: Props) {
  const { t } = useI18n()
  const count = missingFields.length

  if (count === 0) {
    return (
      <span
        className="data-center-missing-badge data-center-missing-complete"
        title={t('dataCenter.complete')}
      >
        {t('dataCenter.complete')}
      </span>
    )
  }

  const variant = count >= 3 ? 'danger' : 'warning'
  const title = `${t('dataCenter.missingFields')}: ${missingFields.join(', ')}`

  return (
    <span
      className={`data-center-missing-badge data-center-missing-${variant}`}
      title={title}
    >
      {t('dataCenter.missing')} {count}
    </span>
  )
}
