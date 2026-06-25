import React from 'react'
import { LoadingState, ErrorState, EmptyState } from './States'
import { useI18n } from '../i18n-context'

export interface Column<T> {
  key: string
  header: string
  width?: string | number
  render?: (row: T) => React.ReactNode
}

interface DataTableProps<T> {
  columns: Column<T>[]
  rows: T[]
  loading?: boolean
  error?: string | null
  emptyText?: string
  total?: number
  getKey: (row: T) => string
  onRowClick?: (row: T) => void
  getRowClassName?: (row: T) => string | undefined
}

export function DataTable<T>({
  columns,
  rows,
  loading,
  error,
  emptyText,
  total,
  getKey,
  onRowClick,
  getRowClassName,
}: DataTableProps<T>) {
  const { t } = useI18n()

  if (loading) return <LoadingState />
  if (error) return <ErrorState error={error} />
  if (rows.length === 0) return <EmptyState text={emptyText} />

  return (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {columns.map(col => (
                <th key={col.key} style={col.width ? { width: col.width } : undefined}>
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr
                key={getKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={[onRowClick ? 'clickable-row' : undefined, getRowClassName?.(row)]
                  .filter(Boolean)
                  .join(' ')}
              >
                {columns.map(col => (
                  <td key={col.key}>
                    {col.render
                      ? col.render(row)
                      : String((row as Record<string, unknown>)[col.key] ?? '—')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {total !== undefined && (
        <div className="table-footer">{t('common.totalRecords', { total })}</div>
      )}
    </>
  )
}
