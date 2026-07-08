import { useState, useMemo, useEffect } from 'react'
import { useBackgroundTasks, type BgTask } from '../hooks/useBackgroundTasks'
import { useTaskDetailModal } from '../components/TaskDetailModal'
import { StatusBadge } from '../components/StatusBadge'
import { ModelBadge } from '../components/ModelBadge'
import { CancelConfirmDialog } from '../components/CancelConfirmDialog'
import { cancelFieldCompletionRun, cancelCompositeWorkflow, cancelCircuitConnectionExtractionRun } from '../api/endpoints'

// ── Types ───────────────────────────────────────────────────────────────────

type StatusFilter = 'all' | 'running' | 'pending' | 'paused' | 'succeeded' | 'partial' | 'failed' | 'cancelled'
type TypeFilter = 'all' | 'composite_workflow' | 'field_completion' | 'circuit_extraction' | 'circuit_connection_extraction'
type TimeFilter = 'all' | '1h' | 'today' | '7d'
type SortOrder = 'newest' | 'updated' | 'longest' | 'errors'

// ── Helpers ─────────────────────────────────────────────────────────────────

function timeAgo(ts: string | null | undefined): string {
  if (!ts) return '—'
  const sec = Math.round((Date.now() - new Date(ts).getTime()) / 1000)
  if (sec < 60) return `${sec}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h`
  return `${Math.floor(sec / 86400)}d`
}

function elapsed(ts: string | null | undefined): number {
  if (!ts) return 0
  return Math.round((Date.now() - new Date(ts).getTime()) / 1000)
}

function shortId(id: string): string { return id.length > 10 ? id.slice(0, 10) + '…' : id }

const STATUS_FILTERS: { key: StatusFilter; label: string; color: string; states: string[] }[] = [
  { key: 'all', label: '全部', color: '#666', states: [] },
  { key: 'running', label: '进行中', color: '#2563eb', states: ['running'] },
  { key: 'pending', label: '排队中', color: '#d97706', states: ['pending', 'queued'] },
  { key: 'paused', label: '已暂停', color: '#eab308', states: ['paused', 'pause_requested'] },
  { key: 'succeeded', label: '已完成', color: '#16a34a', states: ['succeeded'] },
  { key: 'partial', label: '部分失败', color: '#f59e0b', states: ['partially_succeeded'] },
  { key: 'failed', label: '失败', color: '#dc2626', states: ['failed', 'cleanup_failed'] },
  { key: 'cancelled', label: '已取消', color: '#9ca3af', states: ['cancelled'] },
]

function statusToFilter(status: string): StatusFilter {
  for (const f of STATUS_FILTERS) {
    if (f.states.includes(status)) return f.key
  }
  return 'all'
}

function countTasks(tasks: BgTask[], filter: StatusFilter): number {
  if (filter === 'all') return tasks.length
  const states = STATUS_FILTERS.find(f => f.key === filter)?.states ?? []
  return tasks.filter(t => states.includes(t.status)).length
}

// ── Component ───────────────────────────────────────────────────────────────

export function BackgroundTaskCenterPage() {
  const { tasks, loading, error, enablePolling, disablePolling } = useBackgroundTasks(5000)
  const { openTask } = useTaskDetailModal()
  useEffect(() => { enablePolling(); return () => disablePolling() }, [enablePolling, disablePolling])

  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [timeFilter, setTimeFilter] = useState<TimeFilter>('all')
  const [sortBy, setSortBy] = useState<SortOrder>('newest')
  const [search, setSearch] = useState('')
  const [drawerTask, setDrawerTask] = useState<BgTask | null>(null)
  const [cancelTarget, setCancelTarget] = useState<BgTask | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [bulkCancelling, setBulkCancelling] = useState(false)

  // Filter + sort
  const filtered = useMemo(() => {
    let list = [...tasks]

    // Status
    if (statusFilter !== 'all') {
      const states = STATUS_FILTERS.find(f => f.key === statusFilter)?.states ?? []
      list = list.filter(t => states.includes(t.status))
    }
    // Type
    if (typeFilter !== 'all') {
      list = list.filter(t => t.type === typeFilter)
    }
    // Time
    const now = Date.now()
    if (timeFilter === '1h') list = list.filter(t => new Date(t.createdAt).getTime() > now - 3600000)
    else if (timeFilter === 'today') list = list.filter(t => new Date(t.createdAt).getTime() > now - 86400000)
    else if (timeFilter === '7d') list = list.filter(t => new Date(t.createdAt).getTime() > now - 604800000)

    // Search
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter(t =>
        t.id.toLowerCase().includes(q) ||
        t.label.toLowerCase().includes(q) ||
        (t.targetType ?? '').toLowerCase().includes(q),
      )
    }

    // Sort
    if (sortBy === 'newest') list.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
    else if (sortBy === 'updated') list.sort((a, b) => new Date(b.completedAt ?? b.createdAt).getTime() - new Date(a.completedAt ?? a.createdAt).getTime())
    else if (sortBy === 'longest') list.sort((a, b) => elapsed(b.createdAt) - elapsed(a.createdAt))
    else if (sortBy === 'errors') list.sort((a, b) => {
      const aErr = a.status === 'failed' || a.status === 'partially_succeeded' ? -1 : 0
      const bErr = b.status === 'failed' || b.status === 'partially_succeeded' ? -1 : 0
      return aErr - bErr
    })

    return list
  }, [tasks, statusFilter, typeFilter, timeFilter, sortBy, search])

  const statCards = STATUS_FILTERS.slice(0, 6).map(f => ({
    ...f,
    count: countTasks(tasks, f.key),
  }))

  return (
    <div className="tc-page">
      {/* ═══ Header ═══════════════════════════════════════════════════════ */}
      <div className="tc-header">
        <div>
          <h2 className="tc-title">后台任务中心</h2>
          <p className="tc-subtitle">统一管理后台运行中的 LLM 提取及异步任务</p>
        </div>
        <div className="tc-header-actions">
          {selectedIds.size > 0 && (
            <>
              <span style={{ fontSize: 12, color: '#666' }}>已选 {selectedIds.size}</span>
              <button className="btn" style={{ color: '#dc2626', borderColor: '#dc2626' }}
                disabled={bulkCancelling}
                onClick={async () => {
                  setBulkCancelling(true)
                  const ids = [...selectedIds]
                  for (const id of ids) {
                    const t = tasks.find(x => x.id === id)
                    if (!t || !['pending','queued','running'].includes(t.status)) continue
                    try {
                      if (t.type === 'field_completion') await cancelFieldCompletionRun(t.id)
                      else if (t.type === 'circuit_connection_extraction') await cancelCircuitConnectionExtractionRun(t.id)
                      else await cancelCompositeWorkflow(t.id)
                    } catch {}
                  }
                  setSelectedIds(new Set())
                  setBulkCancelling(false)
                }}>
                {bulkCancelling ? '取消中…' : `取消选中 (${selectedIds.size})`}
              </button>
              <button className="btn" onClick={() => setSelectedIds(new Set())}>清除选择</button>
            </>
          )}
          <button className="btn" onClick={() => {
            const queued = tasks.filter(t => t.status === 'pending' || t.status === 'queued')
            setSelectedIds(new Set(queued.map(t => t.id)))
          }}>全选排队 ({tasks.filter(t => t.status === 'pending' || t.status === 'queued').length})</button>
          <input className="tc-search" placeholder="搜索任务名 / ID / 类型…" value={search}
            onChange={e => setSearch(e.target.value)} />
          <button className="btn" onClick={() => window.location.reload()}>刷新</button>
        </div>
      </div>

      {/* ═══ Stats bar ════════════════════════════════════════════════════ */}
      <div className="tc-stats">
        {statCards.map(s => (
          <button key={s.key}
            className={`tc-stat${statusFilter === s.key ? ' active' : ''}`}
            style={{ '--stat-color': s.color } as React.CSSProperties}
            onClick={() => setStatusFilter(s.key)}>
            <span className="tc-stat-count">{s.count}</span>
            <span className="tc-stat-label">{s.label}</span>
          </button>
        ))}
      </div>

      {/* ═══ Body: filters + list ═════════════════════════════════════════ */}
      <div className="tc-body">
        {/* Left filters */}
        <aside className="tc-filters">
          <FilterGroup title="状态">
            {STATUS_FILTERS.map(f => (
              <button key={f.key}
                className={`tc-filter-item${statusFilter === f.key ? ' active' : ''}`}
                onClick={() => setStatusFilter(f.key)}>
                <span className="tc-filter-dot" style={{ background: f.color }} />
                {f.label}
                <span className="tc-filter-count">{countTasks(tasks, f.key)}</span>
              </button>
            ))}
          </FilterGroup>

          <FilterGroup title="任务类型">
            {([
              { key: 'all' as TypeFilter, label: '全部' },
              { key: 'composite_workflow' as TypeFilter, label: 'LLM 提取' },
              { key: 'field_completion' as TypeFilter, label: '字段补全' },
              { key: 'circuit_extraction' as TypeFilter, label: '回路提取' },
              { key: 'circuit_connection_extraction' as TypeFilter, label: '回路→连接提取' },
            ]).map(f => (
              <button key={f.key}
                className={`tc-filter-item${typeFilter === f.key ? ' active' : ''}`}
                onClick={() => setTypeFilter(f.key)}>
                {f.label}
              </button>
            ))}
          </FilterGroup>

          <FilterGroup title="时间">
            {([
              { key: 'all' as TimeFilter, label: '全部' },
              { key: '1h' as TimeFilter, label: '最近 1 小时' },
              { key: 'today' as TimeFilter, label: '今日' },
              { key: '7d' as TimeFilter, label: '最近 7 天' },
            ]).map(f => (
              <button key={f.key}
                className={`tc-filter-item${timeFilter === f.key ? ' active' : ''}`}
                onClick={() => setTimeFilter(f.key)}>
                {f.label}
              </button>
            ))}
          </FilterGroup>

          <FilterGroup title="排序">
            {([
              { key: 'newest' as SortOrder, label: '最新创建' },
              { key: 'updated' as SortOrder, label: '最近更新' },
              { key: 'longest' as SortOrder, label: '耗时最长' },
              { key: 'errors' as SortOrder, label: '异常优先' },
            ]).map(f => (
              <button key={f.key}
                className={`tc-filter-item${sortBy === f.key ? ' active' : ''}`}
                onClick={() => setSortBy(f.key)}>
                {f.label}
              </button>
            ))}
          </FilterGroup>
        </aside>

        {/* Right: task cards */}
        <main className="tc-list">
          {error && (
            <div className="tc-error-banner">
              ⚠️ {error}
              <button className="btn btn-sm" style={{ marginLeft: 12 }} onClick={() => window.location.reload()}>重试</button>
            </div>
          )}
          {loading && tasks.length === 0 ? (
            <div className="tc-empty">加载中…</div>
          ) : filtered.length === 0 ? (
            <div className="tc-empty">
              <p style={{ fontSize: 48, margin: '0 0 12px' }}>📋</p>
              <p>暂无后台任务</p>
              <p style={{ fontSize: 12, color: '#999' }}>LLM 提取或字段补全开始后，任务将自动出现在这里</p>
            </div>
          ) : (
            filtered.map(task => (
              <TaskCard key={task.id} task={task}
                selected={selectedIds.has(task.id)}
                onSelect={(id, checked) => setSelectedIds(prev => {
                  const next = new Set(prev); checked ? next.add(id) : next.delete(id); return next
                })}
                onClick={() => openTask(task)}
                onViewDrawer={() => setDrawerTask(task)}
                onCancel={() => setCancelTarget(task)} />
            ))
          )}
        </main>
      </div>

      {/* ═══ Detail Drawer ════════════════════════════════════════════════ */}
      {drawerTask && (
        <div className="tc-drawer-overlay" onClick={() => setDrawerTask(null)}>
          <div className="tc-drawer" onClick={e => e.stopPropagation()}>
            <TaskDetailDrawer task={drawerTask} onClose={() => setDrawerTask(null)}
              onOpenModal={() => { setDrawerTask(null); openTask(drawerTask) }} />
          </div>
        </div>
      )}

      {/* Cancel confirm */}
      {cancelTarget && (
        <CancelConfirmDialog task={cancelTarget} onClose={() => setCancelTarget(null)} />
      )}
    </div>
  )
}

// ── Filter group ────────────────────────────────────────────────────────────

function FilterGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="tc-filter-group">
      <div className="tc-filter-group-title">{title}</div>
      {children}
    </div>
  )
}

// ── Task Card ───────────────────────────────────────────────────────────────

function TaskCard({ task, onClick, onViewDrawer, onCancel, selected, onSelect }: {
  task: BgTask; onClick: () => void; onViewDrawer: () => void; onCancel: () => void
  selected?: boolean; onSelect?: (id: string, checked: boolean) => void
}) {
  const isRunning = task.status === 'running'
  const isPending = task.status === 'pending' || task.status === 'queued'
  const isPaused = task.status === 'paused' || task.status === 'pause_requested'
  const isFailed = task.status === 'failed' || task.status === 'cleanup_failed'
  const isPartial = task.status === 'partially_succeeded'
  const isDone = task.status === 'succeeded'

  const edgeColor = isRunning || isPending ? '#2563eb'
    : isPaused ? '#eab308'
    : isFailed ? '#dc2626'
    : isPartial ? '#f59e0b'
    : isDone ? '#16a34a'
    : '#9ca3af'

  return (
    <div className="tc-card" style={{ borderLeft: `3px solid ${edgeColor}` }}>
      {(isRunning || isPending) && onSelect && (
        <input type="checkbox" checked={selected ?? false} style={{ margin: '0 8px 0 0', flexShrink: 0, cursor: 'pointer' }}
          onChange={e => onSelect(task.id, e.target.checked)}
          onClick={e => e.stopPropagation()} />
      )}
      <div className="tc-card-main" onClick={onClick}>
        <div className="tc-card-col">
          <div className="tc-card-title">
            {task.type === 'field_completion' ? '🔧' : task.type === 'circuit_extraction' ? '⭕' : '🔗'} {task.label}
          </div>
          <div className="tc-card-meta">
            <code>{shortId(task.id)}</code>
            {task.targetType && <span>· {task.targetType}</span>}
            <span>· {task.createdAt.slice(0, 19)}</span>
          </div>
        </div>

        <div className="tc-card-col">
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <StatusBadge status={task.status} />
            <ModelBadge provider={task.provider} modelName={task.modelName} />
          </div>
          {(isRunning || isPending) && (
            <div className="tc-card-progress">
              <div className="tc-card-progress-track">
                <div className="tc-card-progress-fill tc-card-progress-indeterminate" />
              </div>
              <span className="tc-card-progress-text">{elapsed(task.startedAt || task.createdAt)}s</span>
            </div>
          )}
          {isDone && <span className="tc-card-done">{timeAgo(task.completedAt)} ago</span>}
        </div>

        <div className="tc-card-col tc-card-stats">
          {task.targetCount != null && (
            <span className="tc-card-stat">
              <strong>{task.targetCount}</strong> <small>目标</small>
            </span>
          )}
          <span className="tc-card-stat">
            <strong>{task.type === 'field_completion' ? '字段补全' : task.type === 'circuit_connection_extraction' ? '回路→连接提取' : task.type === 'circuit_extraction' ? '回路提取' : 'LLM 提取'}</strong>
          </span>
        </div>
      </div>

      <div className="tc-card-actions">
        <button className="btn btn-primary btn-sm" onClick={e => { e.stopPropagation(); onViewDrawer() }}>
          详情
        </button>
        {(isRunning || isPending) && (
          <button className="btn btn-sm" style={{ color: '#dc2626' }} onClick={e => { e.stopPropagation(); onCancel() }}>
            取消
          </button>
        )}
      </div>
    </div>
  )
}

// ── Detail Drawer ───────────────────────────────────────────────────────────

function TaskDetailDrawer({ task, onClose, onOpenModal }: {
  task: BgTask; onClose: () => void; onOpenModal: () => void
}) {
  const isRunning = task.status === 'running' || task.status === 'pending'

  return (
    <>
      <div className="tc-drawer-header">
        <h3>{task.type === 'field_completion' ? '🔧 字段补全' : '🔗 LLM 提取'}</h3>
        <button className="btn-close" onClick={onClose}>✕</button>
      </div>
      <div className="tc-drawer-body">
        <div className="tc-drawer-section">
          <div className="tc-drawer-label">基本信息</div>
          <div className="tc-drawer-grid">
            <span><small>ID</small> <code>{shortId(task.id)}</code></span>
            <span><small>状态</small> <StatusBadge status={task.status} /></span>
            <span><small>模型</small> <ModelBadge provider={task.provider} modelName={task.modelName} /></span>
            <span><small>类型</small> {task.label}</span>
            <span><small>目标数</small> {task.targetCount ?? '—'}</span>
            <span><small>创建</small> {task.createdAt.slice(0, 19)}</span>
            <span><small>开始</small> {task.startedAt?.slice(0, 19) ?? '—'}</span>
            {task.completedAt && <span><small>完成</small> {task.completedAt.slice(0, 19)}</span>}
          </div>
        </div>

        {isRunning && (
          <div className="tc-drawer-section">
            <div className="tc-drawer-label">实时进度</div>
            <div className="tc-drawer-progress">
              <div className="tc-drawer-progress-bar">
                <div className="tc-drawer-progress-fill tc-drawer-progress-indeterminate" />
              </div>
              <span>⏱ {elapsed(task.createdAt)}s</span>
            </div>
          </div>
        )}
      </div>
      <div className="tc-drawer-footer">
        <button className="btn btn-primary" onClick={onOpenModal}>打开进度弹窗</button>
        <button className="btn" onClick={onClose}>关闭</button>
      </div>
    </>
  )
}
