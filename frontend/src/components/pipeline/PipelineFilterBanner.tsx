import { useI18n } from '../../i18n-context'
import { pipelineReturnUrl } from '../../utils/pipelineNavigation'

export function PipelineFilterBanner({
  batchId,
  onClear,
  extra,
}: {
  batchId?: string
  onClear: () => void
  extra?: string
}) {
  const { t } = useI18n()
  if (!batchId) return null
  return (
    <div className="pipeline-filter-banner">
      <span>{t('pipeline.filteredFromPipeline')}{extra ? ` — ${extra}` : ''}</span>
      <div className="pipeline-filter-banner-actions">
        <button type="button" className="pipeline-return-link" onClick={() => { window.location.hash = pipelineReturnUrl(batchId) }}>
          {t('pipeline.backToPipeline')}
        </button>
        <button type="button" className="pipeline-link-btn" onClick={onClear}>
          {t('pipeline.clearPipelineFilter')}
        </button>
      </div>
    </div>
  )
}
