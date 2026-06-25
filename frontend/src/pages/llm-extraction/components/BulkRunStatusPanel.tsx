import { useI18n } from '../../../i18n-context'
import type { BulkRunStatus } from '../hooks/useBulkExtraction'

interface Props {
  status: BulkRunStatus | null
  onRefresh?: () => void
  onDismiss?: () => void
}

export function BulkRunStatusPanel({ status, onRefresh, onDismiss }: Props) {
  const { t } = useI18n()
  if (!status) return null

  const pct = status.total === 0
    ? 0
    : Math.round(((status.completed + status.failed) / status.total) * 100)

  return (
    <div className="llm-bulk-status-panel">
      <div className="llm-bulk-status-header">
        <span className="llm-bulk-status-title">{t('llm.dataFirst.bulkProgress')}</span>
        <span className="llm-bulk-status-task">{status.taskType}</span>
        {status.finished && onDismiss && (
          <button type="button" className="llm-btn llm-btn-ghost" onClick={onDismiss}>✕</button>
        )}
      </div>
      <div className="llm-bulk-status-progress">
        <div className="llm-bulk-status-progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="llm-bulk-status-stats">
        <span>{t('llm.dataFirst.bulkCompleted')}: {status.completed}</span>
        <span>{t('llm.dataFirst.bulkFailed')}: {status.failed}</span>
        <span>{t('llm.dataFirst.bulkRunning')}: {status.running}</span>
        <span>{status.completed + status.failed}/{status.total}</span>
      </div>
      {status.errors.length > 0 && (
        <div className="llm-bulk-status-errors">
          <div className="llm-bulk-status-errors-title">{t('llm.dataFirst.bulkErrors')}</div>
          <ul>
            {status.errors.slice(0, 5).map((e, i) => (
              <li key={`${e.id}-${i}`}>
                <code>{e.id.slice(0, 10)}</code>: {e.error}
              </li>
            ))}
            {status.errors.length > 5 && <li>…+{status.errors.length - 5}</li>}
          </ul>
        </div>
      )}
      {status.finished && onRefresh && (
        <button type="button" className="llm-btn" onClick={onRefresh}>
          {t('llm.runs')} / {t('llm.items')}
        </button>
      )}
    </div>
  )
}
