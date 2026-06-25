import { useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import { useI18n } from '../../i18n-context'
import {
  fetchCircuitFunctionPromotionPreview,
  type CircuitFunctionPromotionPreview,
} from '../../api/endpoints'

interface Props {
  sourceId: string
}

function isMigrationMissingError(err: unknown): boolean {
  if (!(err instanceof ApiError)) return false
  const body = err.meta?.responseBody as { detail?: { code?: string } } | undefined
  return body?.detail?.code === 'MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED'
    || String(err.message).includes('MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED')
}

export function CircuitFunctionPromotionPreviewSection({ sourceId }: Props) {
  const { t } = useI18n()
  const [loading, setLoading] = useState(true)
  const [preview, setPreview] = useState<CircuitFunctionPromotionPreview | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchCircuitFunctionPromotionPreview(sourceId)
      .then(data => {
        if (!cancelled) setPreview(data)
      })
      .catch(err => {
        if (cancelled) return
        if (isMigrationMissingError(err)) {
          setError(t('dataCenter.mirrorCircuitFunctionsNotInitialized'))
        } else {
          setError(String((err as Error)?.message ?? err))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [sourceId, t])

  return (
    <div className="data-center-promotion-preview">
      <h4 className="data-center-detail-section-title">{t('dataCenter.promotionCandidatePreview')}</h4>
      <p className="data-center-detail-notice">{t('dataCenter.promotionPreviewOnly')}</p>

      {loading && <p className="data-center-promotion-muted">{t('common.loading')}</p>}
      {error && <div className="data-center-bundle-warning">{error}</div>}

      {preview && (
        <>
          <div className="data-center-object-card">
            <div className="data-center-object-row">
              <span className="data-center-object-label">{t('dataCenter.mirrorSourceTable')}</span>
              <span className="data-center-object-value"><code>{preview.source_table}</code></span>
            </div>
            <div className="data-center-object-row">
              <span className="data-center-object-label">{t('dataCenter.formalQualifiedName')}</span>
              <span className="data-center-object-value"><code>{preview.formal_table}</code></span>
            </div>
            <div className="data-center-object-row">
              <span className="data-center-object-label">{t('dataCenter.promotionReadiness')}</span>
              <span className={`data-center-promotion-readiness readiness-${preview.readiness}`}>
                {preview.readiness}
              </span>
            </div>
            {preview.review_status === 'pending' && (
              <div className="data-center-bundle-warning">{t('dataCenter.promotionReviewRequired')}</div>
            )}
            {preview.blocking_reasons.length > 0 && (
              <div className="data-center-object-row">
                <span className="data-center-object-label">{t('dataCenter.promotionBlockingReasons')}</span>
                <ul className="data-center-missing-list">
                  {preview.blocking_reasons.map(r => <li key={r}>{r}</li>)}
                </ul>
              </div>
            )}
            {preview.warnings.length > 0 && (
              <div className="data-center-object-row">
                <span className="data-center-object-label">{t('dataCenter.promotionWarnings')}</span>
                <ul className="data-center-missing-list">
                  {preview.warnings.map(w => <li key={w}>{w}</li>)}
                </ul>
              </div>
            )}
          </div>

          <h4 className="data-center-detail-section-title">{t('dataCenter.promotionFormalPayloadPreview')}</h4>
          <pre className="data-center-json-pre">{JSON.stringify(preview.formal_payload_preview, null, 2)}</pre>

          <button type="button" className="btn" disabled title={t('dataCenter.promotionActualNotAllowed')}>
            {t('dataCenter.promotionConfirmDisabled')}
          </button>
        </>
      )}
    </div>
  )
}
