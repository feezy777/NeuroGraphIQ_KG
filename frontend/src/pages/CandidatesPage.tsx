/* Candidate Brain Regions — embedded in Data Center or standalone. */
import { useState, useMemo, useEffect } from 'react'
import { PageHeader } from '../components/PageHeader'
import { DataTable, type Column } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { useData } from '../hooks/useData'
import { fetchCandidates, type CandidateBrainRegion } from '../api/endpoints'
import { useGlobalGranularity } from '../hooks/useGlobalGranularity'

interface Props { embedded?: boolean }

export function CandidatesPage({ embedded }: Props) {
  const { granularity } = useGlobalGranularity()
  const [page, setPage] = useState(0)
  const pageSize = 50
  // useData with granularty as key forces re-fetch on granularty change
  const cacheKey = `candidates-${granularity}`
  const { data, loading, error, reload } = useData(() => fetchCandidates({ limit: 5000, granularity_level: granularity || undefined }), [cacheKey])
  useEffect(() => { setPage(0) }, [granularity])

  const items = data?.items ?? []
  const total = data?.total ?? items.length
  const paged = useMemo(() => items.slice(page * pageSize, (page + 1) * pageSize), [items, page])
  const totalPages = Math.ceil(total / pageSize)

  const columns: Column<CandidateBrainRegion>[] = useMemo(() => [
    { key: 'candidate_status', header: '状态', width: 90, render: r => <StatusBadge status={r.candidate_status} /> },
    { key: 'en_name', header: 'EN Name', width: 180, render: r => r.en_name || r.raw_name || '—' },
    { key: 'cn_name', header: 'CN Name', width: 160, render: r => r.cn_name || '—' },
    { key: 'raw_name', header: 'Raw Name', width: 180, render: r => r.raw_name || '—' },
    { key: 'laterality', header: 'Side', width: 60 },
    { key: 'source_atlas', header: 'Atlas', width: 80 },
    { key: 'granularity_level', header: '粒度', width: 70 },
  ], [])

  const table = (
    <div className="data-center-table-section" style={{ height: '100%' }}>
      <div className="data-center-table-scroll">
        <DataTable
          columns={columns}
          rows={paged}
          loading={loading}
          error={error}
          emptyText="暂无候选脑区数据"
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
      <PageHeader title="候选脑区" description="Candidate brain regions from raw parsing" readonly actions={<button className="btn btn-sm" onClick={reload}>刷新</button>} />
      <div className="data-center-panel" style={{ flex: 1 }}>{table}</div>
    </div>
  )
}
