import { CopyButton } from '../CopyButton'
import { ActionButton } from '../ActionButton'
import { LoadingState } from '../States'
import { useI18n } from '../../i18n-context'

export interface PreviewColumn {
  key: string
  header: string
}

export interface StageDataPreviewDrawerProps {
  open: boolean
  title: string
  loading: boolean
  error: string | null
  total: number
  columns: PreviewColumn[]
  rows: Record<string, unknown>[]
  deleted: boolean
  apiNotImplemented: boolean
  fullViewUrl: string | null
  runId?: string
  onClose: () => void
  onOpenFullView: () => void
}

export function StageDataPreviewDrawer({
  open,
  title,
  loading,
  error,
  total,
  columns,
  rows,
  deleted,
  apiNotImplemented,
  fullViewUrl,
  runId,
  onClose,
  onOpenFullView,
}: StageDataPreviewDrawerProps) {
  const { t } = useI18n()
  if (!open) return null

  return (
    <div className="dialog-overlay pipeline-stage-preview-overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="pipeline-stage-preview-drawer dialog-box">
        <div className="pipeline-stage-preview-header dialog-title">{title}</div>

        {deleted && (
          <div className="pipeline-stage-data-deleted">{t('pipeline.stageDataDeletedByRollback')}</div>
        )}
        {apiNotImplemented && (
          <div className="pipeline-stage-data-empty">{t('pipeline.stageDataApiNotImplemented')}</div>
        )}
        {!deleted && !apiNotImplemented && (
          <>
            <p className="pipeline-stage-preview-meta">
              {t('pipeline.stageDataPreview')} — {total} total
              {runId && (
                <span className="pipeline-run-id-cell" style={{ marginLeft: 8 }}>
                  run: <code>{runId.slice(0, 10)}…</code>
                  <CopyButton value={runId} label="" />
                </span>
              )}
            </p>
            {loading && <LoadingState />}
            {error && <p className="batch-create-warning">{error}</p>}
            {!loading && !error && rows.length === 0 && (
              <p className="pipeline-stage-data-empty">{t('pipeline.noActiveStageData')}</p>
            )}
            {!loading && rows.length > 0 && (
              <div className="pipeline-stage-preview-table-wrap">
                <table className="pipeline-stage-preview-table">
                  <thead>
                    <tr>
                      {columns.map(c => <th key={c.key}>{c.header}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, i) => (
                      <tr key={i}>
                        {columns.map(c => (
                          <td key={c.key}>{String(row[c.key] ?? '—')}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        <div className="pipeline-stage-preview-footer dialog-footer">
          <ActionButton label={t('common.close')} variant="default" onClick={onClose} />
          {fullViewUrl && !deleted && !apiNotImplemented && (
            <ActionButton label={t('pipeline.openFullDataPage')} variant="primary" onClick={onOpenFullView} />
          )}
        </div>
      </div>
    </div>
  )
}
