/* Raw Macro96 rows — embedded in Data Center or standalone. */
import { useState, useMemo } from 'react'
import { PageHeader } from '../components/PageHeader'
import { DataTable, type Column } from '../components/DataTable'
import { useData } from '../hooks/useData'
import { listRawMacro96Rows, type RawMacro96Row } from '../api/endpoints'

interface Props { embedded?: boolean }

export function RawMacro96Page({ embedded }: Props) {
  const { data, loading, error, reload } = useData(() => listRawMacro96Rows({ limit: 200 }), [])
  const [page, setPage] = useState(0)
  const pageSize = 50

  const items = data?.items ?? []
  const total = data?.total ?? items.length
  const paged = useMemo(() => items.slice(page * pageSize, (page + 1) * pageSize), [items, page])
  const totalPages = Math.ceil(total / pageSize)

  const columns: Column<RawMacro96Row>[] = useMemo(() => [
    { key: 'row_index', header: '#', width: 40, render: r => r.row_index },
    { key: 'region_index', header: 'Pool Idx', width: 60, render: r => r.region_index },
    { key: 'en_name', header: 'EN Name', width: 240 },
    { key: 'cn_name', header: 'CN Name', render: r => r.cn_name || '—' },
    { key: 'source_sheet', header: 'Sheet', width: 80, render: r => r.source_sheet || '—' },
  ], [])

  const table = (
    <div className="data-center-table-section" style={{ height: '100%' }}>
      <div className="data-center-table-scroll">
        <DataTable
          columns={columns}
          rows={paged}
          loading={loading}
          error={error}
          emptyText="暂无 Raw Macro96 数据"
          getKey={r => r.id}
        />
      </div>
      <div className="data-center-pagination">
        <span>共 {total} 条</span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button className="btn btn-sm" disabled={page <= 0} onClick={() => setPage(p => Math.max(0, p - 1))}>上一页</button>
          <span className="text-muted">{page + 1}/{totalPages || 1}</span>
          <button className="btn btn-sm" disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}>下一页</button>
        </div>
      </div>
    </div>
  )

  if (embedded) return table
  return (
    <div className="page">
      <PageHeader title="Raw Macro96 Rows" description="Macro96 standard pool after Excel parsing" readonly actions={<button className="btn btn-sm" onClick={reload}>刷新</button>} />
      <div className="data-center-panel" style={{ flex: 1 }}>{table}</div>
    </div>
  )
}
