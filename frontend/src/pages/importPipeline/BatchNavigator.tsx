import { useEffect, useMemo, useState } from 'react'
import { ActionButton } from '../../components/ActionButton'
import { StatusBadge } from '../../components/StatusBadge'
import {
  fetchImportBatches,
  filterWorkbenchBatches,
  WORKBENCH_BATCH_STATUS_FILTER_OPTIONS,
  type ImportBatch,
} from '../../api/endpoints'
import { useData } from '../../hooks/useData'
import { useI18n } from '../../i18n-context'
import { isMacro96Batch, parserBadgeClass, resourceShortLabel } from '../../utils/importPipelineHelpers'

const PARSER_FILTER_OPTIONS = ['', 'aal3_xml', 'macro96_xlsx'] as const

export function BatchNavigator({
  selectedId,
  onSelect,
  refreshTick,
}: {
  selectedId: string | null
  onSelect: (id: string | null) => void
  refreshTick: number
}) {
  const { t } = useI18n()
  const [statusFilter, setStatusFilter] = useState('')
  const [parserFilter, setParserFilter] = useState('')
  const [resourceFilter, setResourceFilter] = useState('')
  const [codeFilter, setCodeFilter] = useState('')
  const [innerTick, setInnerTick] = useState(0)

  const { data, loading } = useData(
    () => fetchImportBatches({
      status: statusFilter || undefined,
      resource_id: resourceFilter.trim() || undefined,
      parser_key: parserFilter || undefined,
      limit: 100,
    }),
    [statusFilter, resourceFilter, parserFilter, refreshTick, innerTick],
  )

  const batches = useMemo(() => {
    let items = data?.items ?? []
    if (!statusFilter) {
      items = filterWorkbenchBatches(items)
    }
    if (codeFilter.trim()) {
      const q = codeFilter.trim().toLowerCase()
      items = items.filter(b => b.batch_code.toLowerCase().includes(q))
    }
    return items
  }, [data, codeFilter, statusFilter])

  useEffect(() => {
    if (loading || !data) return
    if (selectedId && !batches.some(b => b.id === selectedId)) {
      onSelect(null)
    }
  }, [loading, data, batches, selectedId, onSelect])

  return (
    <aside className="pipeline-sidebar">
      <div className="pipeline-batch-list-header">
        <span className="pipeline-sidebar-title">{t('pipeline.batchNavigator')}</span>
        <ActionButton label={t('common.refresh')} variant="default" onClick={() => setInnerTick(x => x + 1)} />
      </div>
      <div className="pipeline-batch-list-filters">
        <select className="filter-select" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
          <option value="">{t('importPipeline.filterStatus')}: {t('common.all')}</option>
          {WORKBENCH_BATCH_STATUS_FILTER_OPTIONS.map(s => (
            <option key={s} value={s}>{s}</option>
          ))}
          <option value="cancelled">cancelled</option>
        </select>
        <select className="filter-select" value={parserFilter} onChange={e => setParserFilter(e.target.value)}>
          <option value="">{t('pipeline.filterParser')}: {t('common.all')}</option>
          {PARSER_FILTER_OPTIONS.filter(Boolean).map(p => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
        <input
          className="form-input"
          placeholder={t('pipeline.filterBatchCode')}
          value={codeFilter}
          onChange={e => setCodeFilter(e.target.value)}
        />
        <input
          className="form-input"
          placeholder={`${t('importPipeline.filterResource')}…`}
          value={resourceFilter}
          onChange={e => setResourceFilter(e.target.value)}
        />
      </div>
      <div className="pipeline-batch-list-body">
        {loading && <div className="pipeline-sidebar-empty">{t('common.loading')}</div>}
        {!loading && batches.length === 0 && (
          <div className="pipeline-sidebar-empty">{t('common.empty')}</div>
        )}
        {batches.map((b: ImportBatch) => (
          <div
            key={b.id}
            className={`pipeline-batch-card${selectedId === b.id ? ' pipeline-batch-card-active' : ''}`}
            onClick={() => onSelect(b.id)}
          >
            <div className="pipeline-batch-card-code" title={b.batch_code}>{b.batch_code}</div>
            <div className="pipeline-batch-card-badges">
              <StatusBadge status={b.status} />
              <span className={parserBadgeClass(b.parser_key)}>{b.parser_key ?? '—'}</span>
              <span className="pipeline-count-badge">{resourceShortLabel(b)}</span>
            </div>
            <div className="pipeline-batch-card-progress">
              <span>{t('pipeline.progressRaw')}: —</span>
              <span>{t('pipeline.progressCand')}: —</span>
            </div>
            <div className="pipeline-batch-card-date">{b.created_at?.slice(0, 10) ?? '—'}</div>
          </div>
        ))}
      </div>
    </aside>
  )
}
