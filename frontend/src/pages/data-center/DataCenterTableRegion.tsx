import { DataTable, type Column } from '../../components/DataTable'
import { DataCenterPagination } from './DataCenterPagination'
import { useDataCenterPagination } from './useDataCenterPagination'

interface Props<T> {
  items: T[]
  resetKeys?: unknown[]
  loading?: boolean
  error?: string | null
  emptyText?: string
  columns: Column<T>[]
  getKey: (row: T) => string
  onRowClick?: (row: T) => void
  getRowClassName?: (row: T) => string | undefined
}

export function DataCenterTableRegion<T>({
  items,
  resetKeys = [],
  loading,
  error,
  emptyText,
  columns,
  getKey,
  onRowClick,
  getRowClassName,
}: Props<T>) {
  const {
    page,
    pageSize,
    total,
    pagedItems,
    setPage,
  } = useDataCenterPagination({ items, resetKeys })

  return (
    <div className="data-center-table-section">
      <div className="data-center-table-scroll">
        <DataTable
          columns={columns}
          rows={pagedItems}
          loading={loading}
          error={error}
          emptyText={emptyText}
          getKey={getKey}
          onRowClick={onRowClick}
          getRowClassName={getRowClassName}
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
  )
}
