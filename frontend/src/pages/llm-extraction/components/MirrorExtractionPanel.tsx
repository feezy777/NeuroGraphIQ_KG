import { useCallback, useEffect, useMemo, useState } from 'react'
import { StatusBadge } from '../../../components/StatusBadge'
import { CopyButton } from '../../../components/CopyButton'
import { useData } from '../../../hooks/useData'
import { useI18n } from '../../../i18n-context'
import {
  listMirrorConnections,
  listMirrorFunctions,
  listMirrorCircuits,
  listMirrorTriples,
  type MirrorRegionConnection,
  type MirrorRegionFunction,
  type MirrorRegionCircuit,
  type MirrorKgTriple,
} from '../../../api/endpoints'
import { useBulkSelection } from '../hooks/useBulkSelection'
import type { MirrorSubTabId } from '../llmDataFirstTypes'
import {
  API_MAX_LIMIT,
  LLM_TABLE_DEFAULT_PAGE_SIZE,
  LLM_TABLE_PAGE_SIZE_OPTIONS,
  isLimitExceededError,
} from '../llmTableLimits'

// ── helpers ──────────────────────────────────────────────────────────────────

const DEFAULT_PAGE_SIZE = LLM_TABLE_DEFAULT_PAGE_SIZE
const PAGE_SIZE_OPTIONS = [...LLM_TABLE_PAGE_SIZE_OPTIONS]

function ConfidenceCell({ value }: { value: number | null }) {
  if (value == null) return <>—</>
  return <span>{(value * 100).toFixed(0)}%</span>
}

function StatusCell({ status }: { status: string }) {
  return <StatusBadge status={status} />
}

function MirrorTableError({ error }: { error: string }) {
  const { t } = useI18n()
  const friendly = isLimitExceededError(error)
    ? t('llm.dataFirst.limitExceededError')
    : error
  if (isLimitExceededError(error)) {
    console.error('[MirrorExtraction] limit exceeded:', error)
  }
  return (
    <div className="llm-table-error">
      <span className="llm-inline-error">{friendly}</span>
      {!isLimitExceededError(error) && (
        <details className="llm-error-detail">
          <summary>{t('llm.dataFirst.errorDetail')}</summary>
          <pre>{error}</pre>
        </details>
      )}
    </div>
  )
}

// ── JSON Drawer ───────────────────────────────────────────────────────────────

interface DrawerItem {
  id: string
  type: string
  data: Record<string, unknown>
}

function MirrorDetailDrawer({ item, onClose }: { item: DrawerItem | null; onClose: () => void }) {
  const { t } = useI18n()
  if (!item) return null
  const entries = Object.entries(item.data).filter(([, v]) => v !== null && v !== undefined)
  return (
    <>
      <div className="candidate-detail-drawer-backdrop" onClick={onClose} />
      <div className="candidate-detail-drawer-panel">
        <div className="candidate-detail-drawer-close-row">
          <span style={{ fontWeight: 700 }}>{t('llm.dataFirst.mirrorDetail')} · {item.type}</span>
          <button type="button" className="llm-btn llm-btn-ghost" onClick={onClose}>✕ 关闭</button>
        </div>
        <div className="candidate-detail-drawer-body" style={{ padding: '12px 16px' }}>
          <div style={{ marginBottom: 10 }}>
            <code style={{ fontSize: 12 }}>{item.id}</code>
            <CopyButton value={item.id} label="Copy ID" />
          </div>
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
            <tbody>
              {entries.map(([k, v]) => (
                <tr key={k} style={{ borderBottom: '1px solid #eef1f5' }}>
                  <td style={{ padding: '5px 8px', fontWeight: 600, color: '#4b5563', whiteSpace: 'nowrap', width: 180 }}>{k}</td>
                  <td style={{ padding: '5px 8px', wordBreak: 'break-all' }}>
                    {typeof v === 'object' ? <pre style={{ margin: 0, fontSize: 11 }}>{JSON.stringify(v, null, 2)}</pre> : String(v)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}

// ── Generic selectable + paginated Mirror table ───────────────────────────────

interface ColDef<T> {
  key: string
  label: string
  width?: number | string
  render: (item: T) => React.ReactNode
}

interface MirrorTableProps<T extends { id: string }> {
  items: T[]
  loading: boolean
  error?: string | null
  columns: ColDef<T>[]
  minWidth?: number
  emptyText: string
  onOpenDetail: (item: T) => void
  filterKey: string  // used as resetKey for pagination on filter change
}

function MirrorSelectableTable<T extends { id: string }>({
  items,
  loading,
  error,
  columns,
  minWidth = 1100,
  emptyText,
  onOpenDetail,
  filterKey,
}: MirrorTableProps<T>) {
  const { t } = useI18n()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)

  const totalFiltered = items.length
  const totalPages = Math.max(1, Math.ceil(totalFiltered / pageSize))

  useEffect(() => {
    setPage(1)
  }, [filterKey])

  useEffect(() => {
    if (page > totalPages) setPage(Math.max(1, totalPages))
  }, [page, totalPages])

  const pageItems = useMemo(
    () => items.slice((page - 1) * pageSize, page * pageSize),
    [items, page, pageSize],
  )

  const getId = useCallback((item: T) => item.id, [])

  const sel = useBulkSelection({ getId, filteredItems: items, pageItems })

  const startIndex = totalFiltered === 0 ? 0 : (page - 1) * pageSize + 1
  const endIndex = Math.min(page * pageSize, totalFiltered)

  return (
    <div className="llm-mirror-extraction-panel">
      <div className="llm-mirror-batch-bar">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <span className="llm-selection-chip">{t('llm.dataFirst.selectedCount', { count: sel.selectedCount })}</span>
          <span className="llm-selection-chip">{t('llm.dataFirst.pageSelectedCount', { count: sel.pageSelectedCount })}</span>
          {sel.outsideFilterCount > 0 && (
            <span style={{ fontSize: 12, color: '#92400e' }}>({sel.outsideFilterCount} outside filter)</span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <button type="button" className="llm-btn" onClick={sel.togglePage}>
            {sel.allPageSelected ? '− ' : '+ '}{t('llm.dataFirst.selectCurrentPage')}
          </button>
          <button type="button" className="llm-btn" onClick={sel.selectAllFiltered}>
            {t('llm.dataFirst.selectAllFiltered')} ({totalFiltered})
          </button>
          {sel.outsideFilterCount > 0 && (
            <button type="button" className="llm-btn llm-btn-ghost" onClick={sel.keepOnlyFiltered}>
              {t('llm.dataFirst.keepOnlyFiltered')}
            </button>
          )}
          <button type="button" className="llm-btn llm-btn-ghost" onClick={sel.clearSelection}>
            {t('llm.dataFirst.clearSelection')}
          </button>
          <a className="llm-btn" href="#/rule-validation">{t('llm.dataFirst.jumpValidation')}</a>
          <a className="llm-btn" href="#/human-review">{t('llm.dataFirst.jumpReview')}</a>
        </div>
      </div>

      <div className="llm-table-shell">
        <div className="llm-table-scroll">
          <table className="llm-dense-table" style={{ minWidth }}>
            <thead className="llm-sticky-table-header">
              <tr>
                <th className="llm-table-check-cell">
                  <input
                    type="checkbox"
                    checked={sel.allPageSelected}
                    ref={el => { if (el) el.indeterminate = sel.somePageSelected }}
                    onChange={sel.togglePage}
                  />
                </th>
                {columns.map(col => (
                  <th key={col.key} style={col.width ? { width: col.width } : undefined}>{col.label}</th>
                ))}
                <th className="llm-table-action-cell">{t('llm.dataFirst.openMirrorDetail')}</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={columns.length + 2}>{t('common.loading')}</td></tr>
              )}
              {!loading && error && (
                <tr><td colSpan={columns.length + 2}><MirrorTableError error={error} /></td></tr>
              )}
              {!loading && !error && pageItems.length === 0 && (
                <tr><td colSpan={columns.length + 2} style={{ textAlign: 'center', color: '#9ca3af' }}>{emptyText}</td></tr>
              )}
              {!loading && !error && pageItems.map(row => (
                <tr key={row.id} className="llm-table-row">
                  <td className="llm-table-check-cell">
                    <input
                      type="checkbox"
                      checked={sel.isSelected(row.id)}
                      onChange={() => sel.toggleOne(row.id)}
                    />
                  </td>
                  {columns.map(col => (
                    <td key={col.key}>{col.render(row)}</td>
                  ))}
                  <td className="llm-table-action-cell">
                    <button
                      type="button"
                      className="llm-btn llm-btn-secondary"
                      onClick={e => { e.stopPropagation(); onOpenDetail(row) }}
                    >
                      {t('llm.dataFirst.openMirrorDetail')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="llm-table-pagination">
          <span className="llm-pagination-range">{startIndex}–{endIndex} / {totalFiltered}</span>
          <label className="llm-pagination-pagesize">
            {t('llm.dataFirst.pageSize')}
            <select
              className="llm-select llm-select-sm"
              value={pageSize}
              onChange={e => { setPageSize(Number(e.target.value)); setPage(1) }}
            >
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
    </div>
  )
}

// ── Sub-tab filter bar ────────────────────────────────────────────────────────

interface FilterState {
  sourceAtlas: string
  granularity: string
  mirrorStatus: string
  reviewStatus: string
}

function MirrorFilterBar({
  filters,
  onChange,
  onApply,
  tick,
  onRefresh,
  loadedCount,
  apiTotal,
}: {
  filters: FilterState
  onChange: (patch: Partial<FilterState>) => void
  onApply: () => void
  tick: number
  onRefresh: () => void
  loadedCount: number
  apiTotal?: number
}) {
  const { t } = useI18n()
  const showTruncatedHint = apiTotal != null && apiTotal > loadedCount
  return (
    <div className="llm-data-filter-bar card" style={{ marginBottom: 8 }}>
      <input
        className="llm-input"
        placeholder="source_atlas"
        value={filters.sourceAtlas}
        onChange={e => onChange({ sourceAtlas: e.target.value })}
        onKeyDown={e => e.key === 'Enter' && onApply()}
      />
      <input
        className="llm-input"
        placeholder="granularity"
        value={filters.granularity}
        onChange={e => onChange({ granularity: e.target.value })}
        onKeyDown={e => e.key === 'Enter' && onApply()}
      />
      <input
        className="llm-input"
        placeholder={t('mirror.filterByStatus')}
        value={filters.mirrorStatus}
        onChange={e => onChange({ mirrorStatus: e.target.value })}
        onKeyDown={e => e.key === 'Enter' && onApply()}
      />
      <input
        className="llm-input"
        placeholder={t('mirror.reviewStatus')}
        value={filters.reviewStatus}
        onChange={e => onChange({ reviewStatus: e.target.value })}
        onKeyDown={e => e.key === 'Enter' && onApply()}
      />
      <button type="button" className="llm-btn" onClick={onApply}>{t('common.apply')}</button>
      <button type="button" className="llm-btn llm-btn-ghost" onClick={onRefresh}>{t('dataCenter.refresh')}</button>
      <span className="llm-filter-count-chip">
        {showTruncatedHint
          ? t('llm.dataFirst.loadedCountHint', { loaded: loadedCount, total: apiTotal })
          : loadedCount}
      </span>
    </div>
  )
}

// ── Connections sub-panel ─────────────────────────────────────────────────────

function ConnectionsPanel({ onOpenDetail }: { onOpenDetail: (item: DrawerItem) => void }) {
  const { t } = useI18n()
  const [filters, setFilters] = useState<FilterState>({ sourceAtlas: '', granularity: '', mirrorStatus: '', reviewStatus: '' })
  const [applied, setApplied] = useState<FilterState>(filters)
  const [tick, setTick] = useState(0)

  const params = useMemo(() => ({
    source_atlas: applied.sourceAtlas || undefined,
    granularity_level: applied.granularity || undefined,
    mirror_status: applied.mirrorStatus || undefined,
    review_status: applied.reviewStatus || undefined,
    limit: API_MAX_LIMIT,
  }), [applied])

  const { data, loading, error } = useData(() => listMirrorConnections(params), [JSON.stringify(params), tick])
  const items = data?.items ?? []

  const columns: ColDef<MirrorRegionConnection>[] = useMemo(() => [
    { key: 'id', label: 'ID', width: 120, render: r => <span className="llm-id-cell"><code className="text-mono">{r.id.slice(0, 10)}…</code><CopyButton value={r.id} label="" /></span> },
    { key: 'source', label: t('mirror.sourceRegion'), render: r => <code style={{ fontSize: 11 }}>{r.source_region_candidate_id?.slice(0, 8) ?? '—'}</code> },
    { key: 'target', label: t('mirror.targetRegion'), render: r => <code style={{ fontSize: 11 }}>{r.target_region_candidate_id?.slice(0, 8) ?? '—'}</code> },
    { key: 'connection_type', label: t('mirror.connectionType'), render: r => r.connection_type },
    { key: 'directionality', label: t('mirror.directionality'), width: 100, render: r => r.directionality },
    { key: 'confidence', label: t('mirror.confidence'), width: 90, render: r => <ConfidenceCell value={r.confidence} /> },
    { key: 'mirror_status', label: t('mirror.mirrorStatus'), render: r => <StatusCell status={r.mirror_status} /> },
    { key: 'review_status', label: t('mirror.reviewStatus'), render: r => <StatusCell status={r.review_status} /> },
    { key: 'promotion_status', label: t('mirror.promotionStatus'), render: r => <StatusCell status={r.promotion_status} /> },
    { key: 'created_at', label: t('mirror.createdAt'), render: r => r.created_at.slice(0, 10) },
  ], [t])

  const filterKey = JSON.stringify(applied)

  return (
    <>
      <MirrorFilterBar
        filters={filters}
        onChange={p => setFilters(prev => ({ ...prev, ...p }))}
        onApply={() => setApplied(filters)}
        tick={tick}
        onRefresh={() => setTick(x => x + 1)}
        loadedCount={items.length}
        apiTotal={data?.total}
      />
      <MirrorSelectableTable
        items={items}
        loading={loading}
        error={error}
        columns={columns}
        emptyText={t('llm.dataFirst.noMirrorObjects')}
        onOpenDetail={item => onOpenDetail({ id: item.id, type: 'connection', data: item as unknown as Record<string, unknown> })}
        filterKey={filterKey}
      />
    </>
  )
}

// ── Functions sub-panel ───────────────────────────────────────────────────────

function FunctionsPanel({ onOpenDetail }: { onOpenDetail: (item: DrawerItem) => void }) {
  const { t } = useI18n()
  const [filters, setFilters] = useState<FilterState>({ sourceAtlas: '', granularity: '', mirrorStatus: '', reviewStatus: '' })
  const [applied, setApplied] = useState<FilterState>(filters)
  const [tick, setTick] = useState(0)

  const params = useMemo(() => ({
    source_atlas: applied.sourceAtlas || undefined,
    granularity_level: applied.granularity || undefined,
    mirror_status: applied.mirrorStatus || undefined,
    review_status: applied.reviewStatus || undefined,
    limit: API_MAX_LIMIT,
  }), [applied])

  const { data, loading, error } = useData(() => listMirrorFunctions(params), [JSON.stringify(params), tick])
  const items = data?.items ?? []

  const columns: ColDef<MirrorRegionFunction>[] = useMemo(() => [
    { key: 'id', label: 'ID', width: 120, render: r => <span className="llm-id-cell"><code className="text-mono">{r.id.slice(0, 10)}…</code><CopyButton value={r.id} label="" /></span> },
    { key: 'region', label: '区域', render: r => <code style={{ fontSize: 11 }}>{r.region_candidate_id?.slice(0, 8) ?? '—'}</code> },
    { key: 'function_term', label: t('mirror.macroClinical.projectionFunction'), render: r => r.function_term },
    { key: 'function_category', label: 'Category', render: r => r.function_category },
    { key: 'relation_type', label: 'Relation', render: r => r.relation_type },
    { key: 'confidence', label: t('mirror.confidence'), width: 90, render: r => <ConfidenceCell value={r.confidence} /> },
    { key: 'mirror_status', label: t('mirror.mirrorStatus'), render: r => <StatusCell status={r.mirror_status} /> },
    { key: 'review_status', label: t('mirror.reviewStatus'), render: r => <StatusCell status={r.review_status} /> },
    { key: 'created_at', label: t('mirror.createdAt'), render: r => r.created_at.slice(0, 10) },
  ], [t])

  const filterKey = JSON.stringify(applied)

  return (
    <>
      <MirrorFilterBar
        filters={filters}
        onChange={p => setFilters(prev => ({ ...prev, ...p }))}
        onApply={() => setApplied(filters)}
        tick={tick}
        onRefresh={() => setTick(x => x + 1)}
        loadedCount={items.length}
        apiTotal={data?.total}
      />
      <MirrorSelectableTable
        items={items}
        loading={loading}
        error={error}
        columns={columns}
        emptyText={t('llm.dataFirst.noMirrorObjects')}
        onOpenDetail={item => onOpenDetail({ id: item.id, type: 'function', data: item as unknown as Record<string, unknown> })}
        filterKey={filterKey}
      />
    </>
  )
}

// ── Circuits sub-panel ────────────────────────────────────────────────────────

function CircuitsPanel({ onOpenDetail }: { onOpenDetail: (item: DrawerItem) => void }) {
  const { t } = useI18n()
  const [filters, setFilters] = useState<FilterState>({ sourceAtlas: '', granularity: '', mirrorStatus: '', reviewStatus: '' })
  const [applied, setApplied] = useState<FilterState>(filters)
  const [tick, setTick] = useState(0)

  const params = useMemo(() => ({
    source_atlas: applied.sourceAtlas || undefined,
    granularity_level: applied.granularity || undefined,
    mirror_status: applied.mirrorStatus || undefined,
    review_status: applied.reviewStatus || undefined,
    limit: API_MAX_LIMIT,
  }), [applied])

  const { data, loading, error } = useData(() => listMirrorCircuits(params), [JSON.stringify(params), tick])
  const items = data?.items ?? []

  const columns: ColDef<MirrorRegionCircuit>[] = useMemo(() => [
    { key: 'id', label: 'ID', width: 120, render: r => <span className="llm-id-cell"><code className="text-mono">{r.id.slice(0, 10)}…</code><CopyButton value={r.id} label="" /></span> },
    { key: 'circuit_name', label: '回路名', render: r => r.circuit_name },
    { key: 'circuit_type', label: 'Type', render: r => r.circuit_type },
    { key: 'function_association', label: 'Function', render: r => r.function_association ?? '—' },
    { key: 'confidence', label: t('mirror.confidence'), width: 90, render: r => <ConfidenceCell value={r.confidence ?? null} /> },
    { key: 'mirror_status', label: t('mirror.mirrorStatus'), render: r => <StatusCell status={r.mirror_status} /> },
    { key: 'review_status', label: t('mirror.reviewStatus'), render: r => <StatusCell status={r.review_status} /> },
    { key: 'promotion_status', label: t('mirror.promotionStatus'), render: r => <StatusCell status={r.promotion_status} /> },
    { key: 'created_at', label: t('mirror.createdAt'), render: r => r.created_at.slice(0, 10) },
  ], [t])

  const filterKey = JSON.stringify(applied)

  return (
    <>
      <MirrorFilterBar
        filters={filters}
        onChange={p => setFilters(prev => ({ ...prev, ...p }))}
        onApply={() => setApplied(filters)}
        tick={tick}
        onRefresh={() => setTick(x => x + 1)}
        loadedCount={items.length}
        apiTotal={data?.total}
      />
      <MirrorSelectableTable
        items={items}
        loading={loading}
        error={error}
        columns={columns}
        emptyText={t('llm.dataFirst.noMirrorObjects')}
        onOpenDetail={item => onOpenDetail({ id: item.id, type: 'circuit', data: item as unknown as Record<string, unknown> })}
        filterKey={filterKey}
      />
    </>
  )
}

// ── Triples sub-panel ─────────────────────────────────────────────────────────

function TriplesPanel({ onOpenDetail }: { onOpenDetail: (item: DrawerItem) => void }) {
  const { t } = useI18n()
  const [filters, setFilters] = useState<FilterState>({ sourceAtlas: '', granularity: '', mirrorStatus: '', reviewStatus: '' })
  const [applied, setApplied] = useState<FilterState>(filters)
  const [tick, setTick] = useState(0)

  const params = useMemo(() => ({
    source_atlas: applied.sourceAtlas || undefined,
    granularity_level: applied.granularity || undefined,
    mirror_status: applied.mirrorStatus || undefined,
    review_status: applied.reviewStatus || undefined,
    limit: API_MAX_LIMIT,
  }), [applied])

  const { data, loading, error } = useData(() => listMirrorTriples(params), [JSON.stringify(params), tick])
  const items = data?.items ?? []

  const columns: ColDef<MirrorKgTriple>[] = useMemo(() => [
    { key: 'id', label: 'ID', width: 120, render: r => <span className="llm-id-cell"><code className="text-mono">{r.id.slice(0, 10)}…</code><CopyButton value={r.id} label="" /></span> },
    { key: 'subject', label: t('mirror.subject'), render: r => r.subject_label },
    { key: 'predicate', label: t('mirror.predicate'), render: r => <code className="triple-predicate" style={{ fontSize: 11 }}>{r.predicate}</code> },
    { key: 'object', label: t('mirror.object'), render: r => r.object_label },
    { key: 'triple_scope', label: 'Scope', render: r => r.triple_scope },
    { key: 'confidence', label: t('mirror.confidence'), width: 90, render: r => <ConfidenceCell value={r.confidence} /> },
    { key: 'mirror_status', label: t('mirror.mirrorStatus'), render: r => <StatusCell status={r.mirror_status} /> },
    { key: 'review_status', label: t('mirror.reviewStatus'), render: r => <StatusCell status={r.review_status} /> },
    { key: 'created_at', label: t('mirror.createdAt'), render: r => r.created_at.slice(0, 10) },
  ], [t])

  const filterKey = JSON.stringify(applied)

  return (
    <>
      <MirrorFilterBar
        filters={filters}
        onChange={p => setFilters(prev => ({ ...prev, ...p }))}
        onApply={() => setApplied(filters)}
        tick={tick}
        onRefresh={() => setTick(x => x + 1)}
        loadedCount={items.length}
        apiTotal={data?.total}
      />
      <MirrorSelectableTable
        items={items}
        loading={loading}
        error={error}
        columns={columns}
        emptyText={t('llm.dataFirst.noMirrorObjects')}
        onOpenDetail={item => onOpenDetail({ id: item.id, type: 'triple', data: item as unknown as Record<string, unknown> })}
        filterKey={filterKey}
      />
    </>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────

const SUB_TABS: MirrorSubTabId[] = ['connections', 'functions', 'circuits', 'triples']

export function MirrorExtractionPanel({
  initialSubTab = 'connections',
}: {
  initialSubTab?: MirrorSubTabId
}) {
  const { t } = useI18n()
  const [subTab, setSubTab] = useState<MirrorSubTabId>(initialSubTab)
  const [drawerItem, setDrawerItem] = useState<DrawerItem | null>(null)

  const SUB_LABELS: Record<MirrorSubTabId, string> = {
    connections: t('llm.dataFirst.connections'),
    functions: t('llm.dataFirst.functions'),
    circuits: t('llm.dataFirst.circuits'),
    triples: t('llm.dataFirst.triples'),
  }

  return (
    <div className="llm-data-workspace">
      <div className="llm-mirror-extraction-notice">
        {t('llm.dataFirst.mirrorExtractionDesc')}
      </div>

      <div className="llm-data-tabs llm-mirror-subtabs">
        {SUB_TABS.map(id => (
          <button
            key={id}
            type="button"
            className={`llm-data-tab${subTab === id ? ' llm-data-tab-active' : ''}`}
            onClick={() => setSubTab(id)}
          >
            {SUB_LABELS[id]}
          </button>
        ))}
      </div>

      {subTab === 'connections' && <ConnectionsPanel onOpenDetail={setDrawerItem} />}
      {subTab === 'functions' && <FunctionsPanel onOpenDetail={setDrawerItem} />}
      {subTab === 'circuits' && <CircuitsPanel onOpenDetail={setDrawerItem} />}
      {subTab === 'triples' && <TriplesPanel onOpenDetail={setDrawerItem} />}

      <MirrorDetailDrawer item={drawerItem} onClose={() => setDrawerItem(null)} />
    </div>
  )
}
