import { useCallback, useEffect, useMemo, useState } from 'react'
import type { Column } from '../../../components/DataTable'
import { StatusBadge } from '../../../components/StatusBadge'
import { CopyButton } from '../../../components/CopyButton'
import { ConfirmDialog } from '../../../components/ConfirmDialog'
import { Notice, type NoticeState } from '../../../components/Notice'
import { useData } from '../../../hooks/useData'
import { useI18n } from '../../../i18n-context'
import { readSessionIds } from '../../../hooks/useSessionIds'
import {
  fetchCandidates,
  fetchImportBatches,
  filterWorkbenchBatches,
} from '../../../api/endpoints'
import type { CandidateBrainRegion } from '../../../api/endpoints'
import { useBulkSelection } from '../hooks/useBulkSelection'
import { useBulkExtraction, type BulkExtractionTask } from '../hooks/useBulkExtraction'
import { isCandidateBulkTask } from '../llmDataFirstTypes'
import { BulkRunStatusPanel } from './BulkRunStatusPanel'
import { API_MAX_LIMIT, clampApiLimit, isLimitExceededError } from '../llmTableLimits'
import {
  formatImportBatchLabel,
  formatUnknownBatchLabel,
  shortBatchId,
} from '../utils/batchLabels'

const STATUS_OPTIONS = [
  'candidate_created', 'rule_validating', 'rule_passed', 'rule_failed',
  'llm_not_required', 'llm_validating', 'llm_passed', 'llm_conflict',
  'manual_review_pending', 'manual_approved',
]

const DEFAULT_PAGE_SIZE = 100
const PAGE_SIZE_OPTIONS = [50, 100, 200]

interface BatchOption {
  batchId: string
  label: string
  title: string
}

interface Props {
  onSelectCandidate: (c: CandidateBrainRegion) => void
  onRunCreated: (runId: string) => void
  selectedTask: string
  provider: string
  modelName: string
  dryRun: boolean
  confirmTrigger?: number
  scopeBatchId?: string
  onScopeBatchChange?: (batchId: string) => void
  onBatchStart?: () => void
  onBatchEnd?: () => void
  onSelectionChange?: (count: number) => void
  onSelectionIdsChange?: (ids: string[]) => void
}

export function DataFirstCandidatesTab({
  onSelectCandidate,
  onRunCreated,
  selectedTask,
  provider,
  modelName,
  dryRun,
  confirmTrigger = 0,
  scopeBatchId,
  onScopeBatchChange,
  onBatchStart,
  onBatchEnd,
  onSelectionChange,
  onSelectionIdsChange,
}: Props) {
  const { t } = useI18n()
  const sess = readSessionIds()
  const initialBatchId = scopeBatchId ?? sess.batch_id ?? ''

  const [statusFilter, setStatusFilter] = useState('')
  const [selectedBatchId, setSelectedBatchId] = useState(initialBatchId)
  const [appliedBatchId, setAppliedBatchId] = useState(initialBatchId)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [tick, setTick] = useState(0)
  const [batchTick, setBatchTick] = useState(0)
  const [showConfirm, setShowConfirm] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const onCloseNotice = useCallback(() => setNotice(null), [])

  const { status: bulkStatus, running: bulkRunning, runBulk, clearStatus } = useBulkExtraction()

  useEffect(() => {
    if (scopeBatchId !== undefined) {
      setSelectedBatchId(scopeBatchId)
      setAppliedBatchId(scopeBatchId)
    }
  }, [scopeBatchId])

  const { data: batchesData, loading: batchesLoading } = useData(
    () => fetchImportBatches({ limit: clampApiLimit(API_MAX_LIMIT) }),
    [batchTick],
  )

  const filters = useMemo(() => ({
    candidate_status: statusFilter || undefined,
    batch_id: appliedBatchId || undefined,
    limit: clampApiLimit(API_MAX_LIMIT),
  }), [statusFilter, appliedBatchId])

  const { data, loading, error } = useData(
    () => fetchCandidates(filters),
    [JSON.stringify(filters), tick],
  )

  const { data: countProbeData } = useData(
    () => fetchCandidates({ limit: clampApiLimit(API_MAX_LIMIT) }),
    [batchTick, tick],
  )

  const batchCountMap = useMemo(() => {
    const map = new Map<string, number>()
    for (const item of countProbeData?.items ?? []) {
      if (!item.batch_id) continue
      map.set(item.batch_id, (map.get(item.batch_id) ?? 0) + 1)
    }
    return map
  }, [countProbeData?.items])

  const filteredItems = data?.items ?? []
  const totalFiltered = data?.total ?? filteredItems.length
  const totalPages = Math.max(1, Math.ceil(totalFiltered / pageSize))

  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages])

  const pageItems = useMemo(
    () => filteredItems.slice((page - 1) * pageSize, page * pageSize),
    [filteredItems, page, pageSize],
  )

  const getId = useCallback((item: CandidateBrainRegion) => item.id, [])

  const selection = useBulkSelection({
    getId,
    filteredItems,
    pageItems,
  })

  const batchOptions: BatchOption[] = useMemo(() => {
    const batches = filterWorkbenchBatches(batchesData?.items ?? [])
    const byId = new Map<string, BatchOption>()

    for (const batch of batches) {
      const count = batchCountMap.get(batch.id)
      const label = formatImportBatchLabel(batch, count)
      byId.set(batch.id, { batchId: batch.id, label, title: label })
    }

    if (appliedBatchId && !byId.has(appliedBatchId)) {
      const label = formatUnknownBatchLabel(appliedBatchId, batchCountMap.get(appliedBatchId) ?? totalFiltered)
      byId.set(appliedBatchId, { batchId: appliedBatchId, label, title: `${label} · ${shortBatchId(appliedBatchId)}` })
    }

    if (selectedBatchId && selectedBatchId !== appliedBatchId && !byId.has(selectedBatchId)) {
      const label = formatUnknownBatchLabel(selectedBatchId, batchCountMap.get(selectedBatchId))
      byId.set(selectedBatchId, { batchId: selectedBatchId, label, title: `${label} · ${shortBatchId(selectedBatchId)}` })
    }

    return Array.from(byId.values()).sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
  }, [batchesData?.items, batchCountMap, appliedBatchId, selectedBatchId, totalFiltered])

  const selectedBatchTitle = useMemo(() => {
    if (!selectedBatchId) return t('llmExtraction.allBatches')
    return batchOptions.find(o => o.batchId === selectedBatchId)?.title
      ?? formatUnknownBatchLabel(selectedBatchId, batchCountMap.get(selectedBatchId))
  }, [selectedBatchId, batchOptions, batchCountMap, t])

  useEffect(() => {
    setPage(1)
  }, [statusFilter, appliedBatchId])

  useEffect(() => {
    if (!loading && !error) {
      selection.keepOnlyFiltered()
    }
  }, [appliedBatchId, statusFilter, loading, error, filteredItems.length]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    onSelectionChange?.(selection.selectedCount)
    onSelectionIdsChange?.([...selection.selectedIds])
  }, [selection.selectedCount, selection.selectedIds, onSelectionChange, onSelectionIdsChange])

  useEffect(() => {
    if (confirmTrigger > 0) {
      if (selection.selectedCount === 0) {
        setNotice({ type: 'error', message: t('llm.dataFirst.noSelection') })
      } else if (isCandidateBulkTask(selectedTask)) {
        setShowConfirm(true)
      }
    }
  }, [confirmTrigger, selection.selectedCount, selectedTask, t])

  const applyFilters = useCallback(() => {
    const nextBatchId = selectedBatchId.trim()
    setAppliedBatchId(nextBatchId)
    onScopeBatchChange?.(nextBatchId)
    setPage(1)
  }, [selectedBatchId, onScopeBatchChange])

  const cols: Column<CandidateBrainRegion>[] = useMemo(() => [
    {
      key: 'cn_name',
      header: t('common.cnName'),
      render: r => (
        <button
          type="button"
          className="llm-candidate-name-btn"
          onClick={e => { e.stopPropagation(); onSelectCandidate(r) }}
        >
          <strong>{r.cn_name ?? r.en_name ?? r.raw_name}</strong>
        </button>
      ),
    },
    { key: 'en_name', header: t('common.enName'), render: r => r.en_name ?? '—' },
    { key: 'laterality', header: t('common.laterality'), render: r => <StatusBadge status={r.laterality} /> },
    { key: 'source_atlas', header: t('dataCenter.atlas'), render: r => r.source_atlas ?? '—' },
    { key: 'candidate_status', header: t('llmExtraction.candidateStatus'), render: r => <StatusBadge status={r.candidate_status} /> },
    {
      key: 'id',
      header: t('common.id'),
      render: r => (
        <span className="llm-id-cell">
          <code className="text-mono">{r.id.slice(0, 10)}…</code>
          <CopyButton value={r.id} label="" />
        </span>
      ),
    },
    {
      key: 'actions',
      header: t('dataCenter.openDetail'),
      width: 104,
      render: r => (
        <button
          type="button"
          className="llm-btn llm-btn-secondary"
          onClick={e => { e.stopPropagation(); onSelectCandidate(r) }}
        >
          {t('dataCenter.openDetail')}
        </button>
      ),
    },
  ], [t, onSelectCandidate])

  const executeBulk = async () => {
    setShowConfirm(false)
    if (!isCandidateBulkTask(selectedTask)) return
    onBatchStart?.()
    const ids = [...selection.selectedIds]
    const result = await runBulk({
      taskType: selectedTask as BulkExtractionTask,
      candidateIds: ids,
      provider,
      modelName,
      dryRun,
      batchId: appliedBatchId || undefined,
    })
    onBatchEnd?.()
    if (result?.runId) onRunCreated(result.runId)
    setTick(x => x + 1)
    if (result) {
      setNotice({
        type: result.failed === 0 ? 'success' : 'error',
        message: `${t('llm.dataFirst.bulkCompleted')}: ${result.completed}, ${t('llm.dataFirst.bulkFailed')}: ${result.failed}`,
      })
    }
  }

  const startIndex = totalFiltered === 0 ? 0 : (page - 1) * pageSize + 1
  const endIndex = Math.min(page * pageSize, totalFiltered)

  const emptyMessage = appliedBatchId
    ? t('llm.dataFirst.emptyBatch')
    : t('llmExtraction.emptyList')

  return (
    <div className="llm-candidate-tab">
      <Notice notice={notice} onClose={onCloseNotice} />
      <BulkRunStatusPanel
        status={bulkStatus}
        onRefresh={() => setTick(x => x + 1)}
        onDismiss={clearStatus}
      />

      <div className="llm-candidate-filter-bar llm-data-filter-bar card">
        <select className="llm-select" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
          <option value="">{t('llmExtraction.allStatus')}</option>
          {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select
          className="llm-select llm-batch-select"
          value={selectedBatchId}
          title={selectedBatchTitle}
          onChange={e => setSelectedBatchId(e.target.value)}
          disabled={batchesLoading && batchOptions.length === 0}
        >
          <option value="">{t('llmExtraction.allBatches')}</option>
          {batchOptions.map(opt => (
            <option key={opt.batchId} value={opt.batchId} title={opt.title}>
              {opt.label}
            </option>
          ))}
        </select>
        {selectedBatchId && (
          <span className="llm-batch-id-hint" title={selectedBatchId}>
            {shortBatchId(selectedBatchId)}
          </span>
        )}
        <button type="button" className="llm-btn" onClick={applyFilters}>
          {t('common.apply')}
        </button>
        <button
          type="button"
          className="llm-btn llm-btn-ghost"
          onClick={() => { setBatchTick(x => x + 1); setTick(x => x + 1) }}
        >
          {t('dataCenter.refresh')}
        </button>
        <span className="llm-filter-count-chip">{totalFiltered}</span>
      </div>

      <div className="llm-candidate-selection-bar llm-bulk-action-bar">
        <div className="llm-bulk-selection-summary">
          <span className="llm-selection-chip">{t('llm.dataFirst.selectedCount', { count: selection.selectedCount })}</span>
          <span className="llm-selection-chip">{t('llm.dataFirst.pageSelectedCount', { count: selection.pageSelectedCount })}</span>
          {selection.outsideFilterCount > 0 && (
            <span className="llm-outside-filter-hint">
              ({selection.outsideFilterCount} outside filter)
            </span>
          )}
        </div>
        <div className="llm-bulk-action-buttons">
          <button type="button" className="llm-btn" onClick={selection.togglePage}>
            {selection.allPageSelected ? '− ' : '+ '}{t('llm.dataFirst.selectCurrentPage')}
          </button>
          <button type="button" className="llm-btn" onClick={selection.selectAllFiltered}>
            {t('llm.dataFirst.selectAllFiltered')} ({totalFiltered})
          </button>
          <button type="button" className="llm-btn llm-btn-ghost" onClick={selection.clearSelection}>
            {t('llm.dataFirst.clearSelection')}
          </button>
          {selection.outsideFilterCount > 0 && (
            <button type="button" className="llm-btn llm-btn-ghost" onClick={selection.keepOnlyFiltered}>
              {t('llm.dataFirst.keepOnlyFiltered')}
            </button>
          )}
        </div>
      </div>

      <div className="llm-candidate-table-shell llm-table-shell">
        <div className="llm-candidate-table-scroll llm-table-scroll">
          <table className="llm-dense-table llm-candidate-table">
            <colgroup>
              <col style={{ width: 36 }} />
              <col style={{ width: 180 }} />
              <col style={{ width: 260 }} />
              <col style={{ width: 100 }} />
              <col style={{ width: 100 }} />
              <col style={{ width: 140 }} />
              <col style={{ width: 150 }} />
              <col style={{ width: 104 }} />
            </colgroup>
            <thead className="llm-sticky-table-header">
              <tr>
                <th className="llm-table-check-cell">
                  <input
                    type="checkbox"
                    checked={selection.allPageSelected}
                    ref={el => {
                      if (el) el.indeterminate = selection.somePageSelected
                    }}
                    onChange={selection.togglePage}
                  />
                </th>
                {cols.map(col => (
                  <th
                    key={col.key}
                    className={col.key === 'actions' ? 'llm-table-action-cell' : undefined}
                  >
                    {col.header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={cols.length + 1}>{t('common.loading')}</td></tr>
              )}
              {!loading && error && (
                <tr><td colSpan={cols.length + 1}>
                  <div className="llm-table-error">
                    <span className="llm-inline-error">
                      {isLimitExceededError(error) ? t('llm.dataFirst.limitExceededError') : error}
                    </span>
                    {!isLimitExceededError(error) && (
                      <details className="llm-error-detail">
                        <summary>{t('llm.dataFirst.errorDetail')}</summary>
                        <pre>{error}</pre>
                      </details>
                    )}
                  </div>
                </td></tr>
              )}
              {!loading && !error && pageItems.length === 0 && (
                <tr><td colSpan={cols.length + 1}>{emptyMessage}</td></tr>
              )}
              {!loading && !error && pageItems.map(row => (
                <tr key={row.id} className="llm-table-row">
                  <td className="llm-table-check-cell">
                    <input
                      type="checkbox"
                      checked={selection.isSelected(row.id)}
                      onChange={() => selection.toggleOne(row.id)}
                    />
                  </td>
                  {cols.map(col => (
                    <td
                      key={col.key}
                      className={col.key === 'actions' ? 'llm-table-action-cell' : undefined}
                    >
                      {col.render
                        ? col.render(row)
                        : String((row as unknown as Record<string, unknown>)[col.key] ?? '—')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="llm-candidate-pagination llm-table-pagination">
          <span className="llm-pagination-range">{startIndex}–{endIndex} / {totalFiltered}</span>
          <label className="llm-pagination-pagesize">
            {t('llm.dataFirst.pageSize')}
            <select className="llm-select llm-select-sm" value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setPage(1) }}>
              {PAGE_SIZE_OPTIONS.map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <button type="button" className="llm-btn" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>
            {t('dataCenter.pagination.prev')}
          </button>
          <span className="llm-pagination-page">{page} / {totalPages}</span>
          <button type="button" className="llm-btn" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
            {t('dataCenter.pagination.next')}
          </button>
        </div>
      </div>

      <ConfirmDialog
        open={showConfirm}
        title={t('llm.dataFirst.bulkConfirmTitle')}
        message={
          `${t('llm.dataFirst.bulkConfirmMessage')}\n\n`
          + `${t('llm.dataFirst.taskType')}: ${selectedTask}\n`
          + `Provider: ${provider} / ${modelName || 'default'}\n`
          + `${t('llm.dataFirst.bulkDryRun')}: ${dryRun ? 'yes' : 'no'}\n`
          + `${t('llm.dataFirst.selectedCount', { count: selection.selectedCount })}\n\n`
          + `${t('llm.dataFirst.bulkBoundary')}\n`
          + `${t('llm.dataFirst.bulkMayCallModel')}`
        }
        confirmLabel={t('llm.dataFirst.batchExtract')}
        onConfirm={executeBulk}
        onCancel={() => setShowConfirm(false)}
        loading={bulkRunning}
      />
    </div>
  )
}
