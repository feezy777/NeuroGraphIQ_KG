/* Raw AAL3 labels — embedded in Data Center or standalone. */
import { useState, useMemo } from 'react'
import { PageHeader } from '../components/PageHeader'
import { DataTable, type Column } from '../components/DataTable'
import { useData } from '../hooks/useData'
import { fetchRawAal3Labels, type RawAal3Label } from '../api/endpoints'

interface Props { embedded?: boolean }

export function RawAal3Page({ embedded }: Props) {
  const { data, loading, error, reload } = useData(() => fetchRawAal3Labels({ limit: 500 }), [])
  const [page, setPage] = useState(0)
  const pageSize = 50

  const total = data?.total ?? 0
  const paged = useMemo(() => (data?.items ?? []).slice(page * pageSize, (page + 1) * pageSize), [data, page])
  const totalPages = Math.ceil(total / pageSize)

  const columns: Column<RawAal3Label>[] = useMemo(() => [
    { key: 'label_index', header: 'Index', width: 50, render: r => r.label_index ?? '—' },
    { key: 'raw_name', header: 'Raw Name', width: 180 },
    { key: 'en_name', header: 'EN Name', render: r => r.en_name || '—' },
    { key: 'cn_name', header: 'CN Name', render: r => r.cn_name || '—' },
    { key: 'laterality', header: 'Side', width: 60 },
    { key: 'region_base_name', header: 'Base Name', render: r => r.region_base_name || '—' },
    { key: 'label_value', header: 'Value', width: 50, render: r => r.label_value ?? '—' },
  ], [])

  const table = (
    <div className="data-center-table-section" style={{ height: '100%' }}>
      <div className="data-center-table-scroll">
        <DataTable
          columns={columns}
          rows={paged}
          loading={loading}
          error={error}
          emptyText="暂无 Raw AAL3 标签数据"
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
      <PageHeader title="Raw AAL3 Labels" description="AAL3 atlas label dictionary after parsing" readonly actions={<button className="btn btn-sm" onClick={reload}>刷新</button>} />
      <div className="data-center-panel" style={{ flex: 1 }}>{table}</div>
    </div>
  )
}
