import { useCallback, useEffect, useMemo, useState } from 'react'
import { DataTable } from '../../components/DataTable'
import { useI18n } from '../../i18n-context'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { DataCenterPagination } from './DataCenterPagination'
import { useDataCenterPagination } from './useDataCenterPagination'
import { FormalAlignmentCard } from './FormalAlignmentCard'
import { FieldCompletionModal } from './FieldCompletionModal'
import { MultiTargetFieldCompletionModal } from './MultiTargetFieldCompletionModal'
import { resolveCircuitBundleFromCircuitIds } from './circuitBundleUtils'
import type { CircuitBundleFieldCompletionGroup } from './circuitBundleTypes'
import { buildFormalColumns } from './formalColumnBuilders'
import type { FormalFieldMapping } from './formalFieldMappings'
import type { FormalRow, OverlayPatch } from './fieldCompletionUtils'

interface Props {
  mapping: FormalFieldMapping
  items: FormalRow[]
  resetKeys?: unknown[]
  loading?: boolean
  error?: string | null
  emptyText?: string
  pageSize?: number
  onOpenDetail: (row: FormalRow) => void
  onRefresh?: (overlayPatch?: OverlayPatch) => void
  onDeleteSelected?: (ids: string[]) => void
}

export function FormalObjectTableSection({
  mapping,
  items,
  resetKeys = [],
  loading,
  error,
  emptyText,
  pageSize: pageSizeProp,
  onOpenDetail,
  onRefresh,
  onDeleteSelected,
}: Props) {
  const { t } = useI18n()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [selectAllFiltered, setSelectAllFiltered] = useState(false)
  const [completionOpen, setCompletionOpen] = useState(false)
  const [completionTargets, setCompletionTargets] = useState<FormalRow[]>([])
  const [bundleOpen, setBundleOpen] = useState(false)
  const [bundleLoading, setBundleLoading] = useState(false)
  const [circuitBundle, setCircuitBundle] = useState<CircuitBundleFieldCompletionGroup | null>(null)
  const [bundleWarnings, setBundleWarnings] = useState<string[]>([])
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)

  const isCircuitBundle = mapping.targetType === 'circuit'

  const {
    page,
    pageSize,
    total,
    pagedItems,
    setPage,
  } = useDataCenterPagination({ items, pageSize: pageSizeProp, resetKeys })

  useEffect(() => {
    setSelectedIds(new Set())
    setSelectAllFiltered(false)
  }, [mapping.targetType, ...resetKeys])

  const pageIds = useMemo(() => pagedItems.map(r => r.id), [pagedItems])
  const allIds = useMemo(() => items.map(r => r.id), [items])
  const itemById = useMemo(() => new Map(items.map(r => [r.id, r])), [items])

  const effectiveSelected = useMemo(() => {
    if (selectAllFiltered) return new Set(allIds)
    return selectedIds
  }, [selectAllFiltered, selectedIds, allIds])

  const pageAllSelected = pageIds.length > 0 && pageIds.every(id => effectiveSelected.has(id))

  const togglePage = useCallback(() => {
    setSelectAllFiltered(false)
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (pageAllSelected) {
        pageIds.forEach(id => next.delete(id))
      } else {
        pageIds.forEach(id => next.add(id))
      }
      return next
    })
  }, [pageAllSelected, pageIds])

  const toggleRow = useCallback((id: string) => {
    setSelectAllFiltered(false)
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const openCompletionForRows = useCallback((rows: FormalRow[]) => {
    if (isCircuitBundle) {
      const ids = rows.map(r => r.id)
      setCompletionTargets(rows)
      setBundleOpen(true)
      setBundleLoading(true)
      setCircuitBundle(null)
      setBundleWarnings([])
      void resolveCircuitBundleFromCircuitIds(ids, 'data_center')
        .then(({ bundle, warnings }) => {
          setCircuitBundle(bundle)
          setBundleWarnings(warnings)
        })
        .finally(() => setBundleLoading(false))
      return
    }
    setCompletionTargets(rows)
    setCompletionOpen(true)
  }, [isCircuitBundle])

  const openBulkCompletion = useCallback(() => {
    const ids = [...effectiveSelected]
    if (ids.length === 0) return
    const rows = ids.map(id => itemById.get(id)).filter(Boolean) as FormalRow[]
    openCompletionForRows(rows)
  }, [effectiveSelected, itemById, openCompletionForRows])

  const completionIds = useMemo(
    () => completionTargets.map(r => r.id),
    [completionTargets],
  )

  const columns = useMemo(
    () => [
      {
        key: '_select',
        header: '',
        width: 40,
        render: (row: FormalRow) => (
          <input
            type="checkbox"
            className="row-checkbox"
            checked={effectiveSelected.has(row.id)}
            onChange={() => toggleRow(row.id)}
            onClick={e => e.stopPropagation()}
          />
        ),
      },
      ...buildFormalColumns({
        mapping,
        onCompleteRow: row => openCompletionForRows([row]),
        onOpenDetail,
        t,
      }),
    ],
    [mapping, onOpenDetail, t, effectiveSelected, toggleRow, openCompletionForRows],
  )

  const selectedCount = effectiveSelected.size

  return (
    <div className="data-center-formal-table">
      <FormalAlignmentCard mapping={mapping} items={items} />

      <div className="data-center-formal-toolbar">
        <button
          type="button"
          className="btn btn-primary"
          disabled={effectiveSelected.size === 0}
          title={effectiveSelected.size === 0 ? t('dataCenter.selectObjectsFirst') : undefined}
          onClick={openBulkCompletion}
        >
          {isCircuitBundle ? t('dataCenter.circuitBundleCompletion') : t('dataCenter.fieldCompletion')}
        </button>
        <button type="button" className="btn" onClick={togglePage}>
          {t('dataCenter.selectPage')}
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => {
            setSelectAllFiltered(true)
            setSelectedIds(new Set(allIds))
          }}
        >
          {t('dataCenter.selectAllFiltered')}
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => {
            setSelectAllFiltered(false)
            setSelectedIds(new Set())
          }}
        >
          {t('dataCenter.clearSelection')}
        </button>
        <span className="data-center-formal-selection-meta">
          {t('dataCenter.selectedCount', { count: effectiveSelected.size })}
        </span>
      </div>

      <div className="data-center-table-section">
        <div className="data-center-table-scroll">
          <DataTable
            columns={columns}
            rows={pagedItems}
            loading={loading}
            error={error}
            emptyText={emptyText}
            getKey={r => r.id}
            onRowClick={onOpenDetail}
            getRowClassName={r => effectiveSelected.has(r.id) ? 'row-selected' : undefined}
          />
        </div>
        <DataCenterPagination
          page={page}
          pageSize={pageSize}
          total={total}
          onPageChange={setPage}
          disabled={loading}
        />
      </div>

      {selectedCount > 0 && (
        <div className="floating-action-bar">
          <span className="fab-count">{selectedCount} 项已选</span>
          <span className="fab-divider" />
          <button className="fab-btn" onClick={openBulkCompletion}>
            ✨ AI 补全
          </button>
          {onDeleteSelected && (
            <button className="fab-btn fab-btn-danger" onClick={() => setDeleteConfirmOpen(true)}>
              🗑 删除
            </button>
          )}
          <span className="fab-divider" />
          <button className="fab-btn" onClick={() => { setSelectAllFiltered(false); setSelectedIds(new Set()) }}>
            取消选择
          </button>
        </div>
      )}

      <ConfirmDialog
        open={deleteConfirmOpen}
        title="确认删除"
        message={`确定删除选中的 ${selectedCount} 个对象？此操作不可撤销。`}
        onConfirm={() => {
          if (onDeleteSelected) onDeleteSelected([...effectiveSelected])
          setDeleteConfirmOpen(false)
        }}
        onCancel={() => setDeleteConfirmOpen(false)}
        danger
      />

      {!isCircuitBundle && (
        <FieldCompletionModal
          open={completionOpen}
          mapping={mapping}
          selectedObjects={completionTargets}
          selectedIds={completionIds}
          onClose={() => setCompletionOpen(false)}
          onCompleted={onRefresh}
        />
      )}

      {isCircuitBundle && (
        <MultiTargetFieldCompletionModal
          open={bundleOpen}
          bundle={circuitBundle}
          resolveWarnings={bundleWarnings}
          loading={bundleLoading}
          onClose={() => setBundleOpen(false)}
          onCompleted={onRefresh}
        />
      )}
    </div>
  )
}
