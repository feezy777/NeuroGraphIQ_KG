import { useEffect } from 'react'
import { useI18n } from '../../i18n-context'

interface Props {
  target: string
}

/** Redirect legacy routes to Data Center on mount. */
export function LegacyDataCenterRedirect({ target }: Props) {
  const { t } = useI18n()

  useEffect(() => {
    window.location.hash = target.startsWith('#') ? target : `#${target}`
  }, [target])

  return (
    <div className="data-center-route-notice">
      <p>{t('dataCenter.legacyRouteNotice')}</p>
      <a className="btn" href={target.startsWith('#') ? target : `#${target}`}>
        {t('dataCenter.goToDataCenter')}
      </a>
    </div>
  )
}
