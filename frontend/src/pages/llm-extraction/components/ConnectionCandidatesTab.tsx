import { useMemo, useState, useCallback, useEffect, useRef } from 'react'
import { DataTable, type Column } from '../../../components/DataTable'
import { StatusBadge } from '../../../components/StatusBadge'
import { listMirrorConnections, type MirrorRegionConnection } from '../../../api/endpoints'

const PAGE_SIZE_OPTIONS = [50, 100, 200]
const DEFAULT_PAGE_SIZE = 50

interface Props {
  sourceAtlas?: string
  granularityLevel?: string
  pooledIds: Set<string>
  onSelectionChange: (ids: string[]) => void
  onSelectionIdsChange?: (ids: string[]) => void
}

export function ConnectionCandidatesTab({
  sourceAtlas,
  granularityLevel,
  pooledIds,
  onSelectionChange,
  onSelectionIdsChange,
}: Props) {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [total, setTotal] = useState(0)
  const [items, setItems] = useState<MirrorRegionConnection[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [allFilteredSelected, setAllFilteredSelected] = useState(false)
  const fetchRef = useRef(0)
  const allSelectedRef = useRef(false)

  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  // Fetch connections with pagination
  useEffect(() => {
    const gen = ++fetchRef.current
    let cancelled = false
    setLoading(true)
    const params: Record<string, any> = {
      limit: pageSize,
      offset: (page - 1) * pageSize,
    }
    // Only apply scope filters if explicitly set and non-empty
    if (sourceAtlas) params.source_atlas = sourceAtlas
    if (granularityLevel) params.granularity_level = granularityLevel

    listMirrorConnections(params).then(res => {
      if (cancelled || gen !== fetchRef.current) return
      setItems(res.items)
      setTotal(res.total)
      setLoading(false)
      if (page > Math.max(1, Math.ceil(res.total / pageSize))) setPage(1)
    }).catch(() => {
      if (!cancelled) setLoading(false)
    })
    return () => { cancelled = true }
  }, [page, pageSize, sourceAtlas, granularityLevel])

  // Sync selection with parent
  useEffect(() => {
    onSelectionChange([...selectedIds])
    onSelectionIdsChange?.([...selectedIds])
  }, [selectedIds]) // eslint-disable-line react-hooks/exhaustive-deps

  const allPageSelected = items.length > 0 && items.every(r => selectedIds.has(r.id))
  const somePageSelected = items.some(r => selectedIds.has(r.id))

  // ── Selection handlers ──────────────────────────────────────────────────
  const handleSelectOne = useCallback((id: string) => {
    setAllFilteredSelected(false)
    allSelectedRef.current = false
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const togglePage = useCallback(() => {
    setAllFilteredSelected(false)
    allSelectedRef.current = false
    if (allPageSelected) {
      setSelectedIds(prev => {
        const next = new Set(prev)
        items.forEach(r => next.delete(r.id))
        return next
      })
    } else {
      setSelectedIds(prev => {
        const next = new Set(prev)
        items.forEach(r => next.add(r.id))
        return next
      })
    }
  }, [allPageSelected, items])

  const selectAllFiltered = useCallback(() => {
    setAllFilteredSelected(true)
    allSelectedRef.current = true
    // Load all filtered results to select everything
    setLoading(true)
    const params: Record<string, any> = { limit: 10000 }
    if (sourceAtlas) params.source_atlas = sourceAtlas
    if (granularityLevel) params.granularity_level = granularityLevel
    listMirrorConnections(params).then(res => {
      setSelectedIds(new Set(res.items.map(r => r.id)))
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [sourceAtlas, granularityLevel])

  const clearSelection = useCallback(() => {
    setAllFilteredSelected(false)
    allSelectedRef.current = false
    setSelectedIds(new Set())
  }, [])

  // ── Columns ─────────────────────────────────────────────────────────────
  const columns: Column<MirrorRegionConnection>[] = useMemo(() => [
    {
      key: '_sel', header: '', width: 34,
      render: r => (
        <input type="checkbox"
          checked={allFilteredSelected || selectedIds.has(r.id)}
          onChange={() => handleSelectOne(r.id)}
        />
      ),
    },
    {
      key: '_marker', header: '', width: 22,
      render: r => pooledIds.has(r.id)
        ? <span title="已入连接池" style={{ fontSize: 12, opacity: 0.6 }}>🔗</span>
        : null,
    },
    {
      key: 'name_cn', header: '中文名', width: 120,
      render: r => {
        const attrs = (r.attributes || {}) as Record<string, unknown>
        const overlay = (r.normalized_payload_json as any)?.formal_field_overlay || {}
        return String(overlay.name_cn || attrs.name_cn || attrs.region_name_cn || '—')
      },
    },
    {
      key: 'name_en', header: '英文名', width: 120,
      render: r => {
        const attrs = (r.attributes || {}) as Record<string, unknown>
        const overlay = (r.normalized_payload_json as any)?.formal_field_overlay || {}
        return String(overlay.name_en || attrs.name_en || attrs.region_name_en || '—')
      },
    },
    {
      key: 'connection_type', header: '连接类型', width: 100,
      render: r => r.connection_type || '—',
    },
    { key: 'source_atlas', header: 'Atlas', width: 80 },
    {
      key: 'mirror_status', header: '状态', width: 100,
      render: r => <StatusBadge status={r.mirror_status} />,
    },
    {
      key: 'id', header: 'ID', width: 140,
      render: r => <code style={{ fontSize: 10 }}>{r.id.slice(0, 14)}…</code>,
    },
  ], [selectedIds, allFilteredSelected, pooledIds, handleSelectOne])

  const startIndex = total > 0 ? (page - 1) * pageSize + 1 : 0
  const endIndex = Math.min(page * pageSize, total)

  return (
    <div className="conn-candidates-tab" style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      {/* ── Selection bar ────────────────────────────────────────────────── */}
      <div className="llm-candidate-selection-bar llm-bulk-action-bar" style={{ flexShrink: 0 }}>
        <div className="llm-bulk-selection-summary">
          <span className="llm-selection-chip">已选 <strong>{selectedIds.size}</strong> 条</span>
          <span className="llm-selection-chip">当前页 {items.filter(r => selectedIds.has(r.id)).length} 条</span>
          <span className="llm-selection-chip">池内 <strong style={{ color: '#059669' }}>{pooledIds.size}</strong> 条</span>
        </div>
        <div className="llm-bulk-action-buttons">
          <button type="button" className="llm-btn" onClick={togglePage}>
            {allPageSelected ? '− ' : '+ '}选择当前页
          </button>
          <button type="button" className="llm-btn" onClick={selectAllFiltered}>
            选择全部 ({total})
          </button>
          <button type="button" className="llm-btn llm-btn-ghost" onClick={clearSelection}
            disabled={selectedIds.size === 0}>
            清空选择
          </button>
        </div>
      </div>

      {/* ── Table (scrollable) ─────────────────────────────────────────────── */}
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        <DataTable
          columns={columns}
          rows={items}
          getKey={r => r.id}
          emptyText={loading ? '加载中…' : '暂无连接数据'}
        />
      </div>

      {/* ── Pagination (sticky bottom) ─────────────────────────────────────── */}
      {total > 0 && (
        <div className="llm-candidate-pagination llm-table-pagination" style={{ flexShrink: 0 }}>
          <span className="llm-pagination-range">{startIndex}–{endIndex} / {total}</span>
          <label className="llm-pagination-pagesize">
            每页
            <select className="llm-select llm-select-sm" value={pageSize}
              onChange={e => { setPageSize(Number(e.target.value)); setPage(1) }}>
              {PAGE_SIZE_OPTIONS.map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <button type="button" className="llm-btn" disabled={page <= 1}
            onClick={() => setPage(p => p - 1)}>
            上一页
          </button>
          <span className="llm-page-indicator">{page} / {totalPages}</span>
          <button type="button" className="llm-btn" disabled={page >= totalPages}
            onClick={() => setPage(p => p + 1)}>
            下一页
          </button>
        </div>
      )}
    </div>
  )
}
