import { CopyButton } from '../CopyButton'
import type { StageNavContext } from '../../utils/pipelineNavigation'
import { useI18n } from '../../i18n-context'

export function PipelineStageDataActions({
  ctx,
  viewLabelKey,
  onViewData,
  onPreview,
}: {
  ctx: StageNavContext
  viewLabelKey: string
  onViewData: () => void
  onPreview: () => void
}) {
  const { t } = useI18n()
  const hasData = ctx.currentCount > 0
  const disabled = ctx.deleted || (!hasData && ctx.stage !== 'reviewed' && ctx.stage !== 'promoted')

  return (
    <div className="pipeline-stage-data-actions">
      {ctx.deleted && (
        <span className="pipeline-stage-data-deleted">{t('pipeline.stageDataDeletedByRollback')}</span>
      )}
      {!ctx.deleted && !hasData && (
        <span className="pipeline-stage-data-empty">{t('pipeline.noActiveStageData')}</span>
      )}
      <div className="pipeline-stage-data-buttons">
        <button
          type="button"
          className="pipeline-stage-data-button pipeline-link-btn"
          disabled={disabled}
          onClick={onViewData}
        >
          {t(viewLabelKey)}
        </button>
        <button
          type="button"
          className="pipeline-stage-data-button pipeline-link-btn"
          disabled={disabled}
          onClick={onPreview}
        >
          {t('pipeline.previewStageData')}
        </button>
        {ctx.runId && (
          <span className="pipeline-run-id-cell">
            <code>{ctx.runId.slice(0, 8)}…</code>
            <CopyButton value={ctx.runId} label="" />
          </span>
        )}
      </div>
    </div>
  )
}
