import { useState, useCallback, useMemo } from 'react'
import { useData } from '../../../hooks/useData'
import { useI18n } from '../../../i18n-context'
import { TaskFilterBar, type TaskFilterValue } from './TaskFilterBar'
import { ResultRow } from './ResultRow'
import type { ExtractionTypeConfig, ResultAction } from '../types/extractionConfig'

interface Props {
  config: ExtractionTypeConfig
  /** Additional fixed query params for fetchFn (e.g., resource_id, batch_id) */
  baseParams?: Record<string, unknown>
  /** Called when user triggers an action on a result item */
  onAction?: (action: ResultAction, item: Record<string, unknown>) => void
}

const DEFAULT_FILTER: TaskFilterValue = { taskType: '', runId: '', search: '' }

export function ExtractionResultPanel({ config, baseParams, onAction }: Props) {
  const { t } = useI18n()
  const [filter, setFilter] = useState<TaskFilterValue>(DEFAULT_FILTER)
  const [page, setPage] = useState(0)
  const pageSize = 50

  // Build query params
  const queryParams = useMemo(() => {
    const p: Record<string, unknown> = { limit: pageSize, offset: page * pageSize, ...baseParams }
    if (filter.runId) p.llm_run_id = filter.runId
    return p
  }, [baseParams, filter.runId, page])

  // Fetch data
  const { data, loading, error } = useData(
    () => config.fetchFn(queryParams),
    [config, JSON.stringify(queryParams)],
  )

  const items = data?.items ?? []
  const total = data?.total ?? 0

  // Client-side search filter
  const filteredItems = useMemo(() => {
    if (!filter.search.trim()) return items
    const q = filter.search.toLowerCase()
    return items.filter(item => {
      // Search across label, sublabel, evidence_text
      const searchable = [
        item[config.labelField],
        config.sublabelField ? item[config.sublabelField] : null,
        item['evidence_text'],
        item['connection_type'],
        item['function_term'],
        item['circuit_name'],
        item['step_name'],
        item['function_term_en'],
        item['predicate'],
        item['subject_label'],
        item['object_label'],
        item['display_label'],
      ].filter(Boolean).join(' ').toLowerCase()
      return searchable.includes(q)
    })
  }, [items, filter.search, config])

  const handleFilterChange = useCallback((v: TaskFilterValue) => {
    setFilter(v)
    setPage(0)
  }, [])

  const handleAction = useCallback((action: ResultAction, item: Record<string, unknown>) => {
    onAction?.(action, item)
  }, [onAction])

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      {/* Filter bar */}
      <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)' }}>
        <TaskFilterBar
          fetchRuns={config.fetchRunsFn}
          value={filter}
          onChange={handleFilterChange}
        />
      </div>

      {/* Result list */}
      <div>
        {loading && (
          <div style={{ padding: 16 }}>
            {[1, 2, 3].map(i => (
              <div
                key={i}
                style={{
                  height: 40,
                  marginBottom: 4,
                  borderRadius: 4,
                  background: '#f0f0f0',
                  animation: 'pulse 1.5s infinite',
                }}
              />
            ))}
          </div>
        )}

        {error && (
          <div style={{ padding: 24, textAlign: 'center', color: '#cf1322', fontSize: 13 }}>
            {t('common.error')}: {error}
          </div>
        )}

        {!loading && !error && filteredItems.length === 0 && (
          <div style={{ padding: 32, textAlign: 'center', color: '#888', fontSize: 13 }}>
            {t(config.emptyKey)}
          </div>
        )}

        {!loading && !error && filteredItems.map((item, i) => (
          <ResultRow
            key={String((item as any).id ?? i)}
            item={item as Record<string, unknown>}
            config={config}
            onAction={handleAction}
          />
        ))}
      </div>

      {/* Pagination */}
      {total > pageSize && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 12,
          padding: '8px 12px',
          borderTop: '1px solid var(--border)',
          fontSize: 12,
        }}>
          <button className="btn" disabled={page === 0} onClick={() => setPage(p => p - 1)}>
            ← {t('common.prev')}
          </button>
          <span style={{ color: '#888' }}>
            {page * pageSize + 1}-{Math.min((page + 1) * pageSize, total)} / {total}
          </span>
          <button className="btn" disabled={(page + 1) * pageSize >= total} onClick={() => setPage(p => p + 1)}>
            {t('common.next')} →
          </button>
        </div>
      )}
    </div>
  )
}
