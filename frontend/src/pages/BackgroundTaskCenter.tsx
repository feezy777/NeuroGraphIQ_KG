import { useState, useMemo } from 'react'
import { useBackgroundTasks, type BgTask } from '../hooks/useBackgroundTasks'
import { useTaskDetailModal } from '../components/TaskDetailModal'
import { StatusBadge } from '../components/StatusBadge'
import { ModelBadge } from '../components/ModelBadge'
import { CancelConfirmDialog } from '../components/CancelConfirmDialog'
import { getTaskDef, cancelTask, TASK_TYPE_OPTIONS } from '../services/taskRegistry'

// ── Types ───────────────────────────────────────────────────────────────────

type StatusFilter = 'all' | 'running' | 'pending' | 'paused' | 'succeeded' | 'partial' | 'failed' | 'cancelled'
type TypeFilter = 'all' | BgTask['type']
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

function shortId(id: string): string { return id.length > 12 ? id.slice(0, 12) + '…' : id }

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

const TIME_FILTERS: { key: TimeFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: '1h', label: '最近 1 小时' },
  { key: 'today', label: '今日' },
  { key: '7d', label: '最近 7 天' },
]

const SORT_OPTIONS: { key: SortOrder; label: string }[] = [
  { key: 'newest', label: '最新创建' },
  { key: 'updated', label: '最近更新' },
  { key: 'longest', label: '耗时最长' },
  { key: 'errors', label: '异常优先' },
]

function countTasks(tasks: BgTask[], filter: StatusFilter): number {
  if (filter === 'all') return tasks.length
  const states = STATUS_FILTERS.find(f => f.key === filter)?.states ?? []
  return tasks.filter(t => states.includes(t.status)).length
}

// ── Component ───────────────────────────────────────────────────────────────

export function BackgroundTaskCenterPage() {
  const { tasks, loading, error } = useBackgroundTasks()
  const { openTask } = useTaskDetailModal()

  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [timeFilter, setTimeFilter] = useState<TimeFilter>('all')
  const [sortBy, setSortBy] = useState<SortOrder>('newest')
  const [search, setSearch] = useState('')
  const [drawerTask, setDrawerTask] = useState<BgTask | null>(null)
  const [cancelTarget, setCancelTarget] = useState<BgTask | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [bulkCancelling, setBulkCancelling] = useState(false)
  const [bulkResult, setBulkResult] = useState<string | null>(null)

  // Filter + sort
  const filtered = useMemo(() => {
    let list = [...tasks]

    if (statusFilter !== 'all') {
      const states = STATUS_FILTERS.find(f => f.key === statusFilter)?.states ?? []
      list = list.filter(t => states.includes(t.status))
    }
    if (typeFilter !== 'all') {
      list = list.filter(t => t.type === typeFilter)
    }
    const now = Date.now()
    if (timeFilter === '1h') list = list.filter(t => new Date(t.createdAt).getTime() > now - 3600000)
    else if (timeFilter === 'today') list = list.filter(t => new Date(t.createdAt).getTime() > now - 86400000)
    else if (timeFilter === '7d') list = list.filter(t => new Date(t.createdAt).getTime() > now - 604800000)

    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter(t =>
        t.id.toLowerCase().includes(q) ||
        t.label.toLowerCase().includes(q) ||
        (t.targetType ?? '').toLowerCase().includes(q),
      )
    }

    if (sortBy === 'newest') list.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
    else if (sortBy === 'updated') list.sort((a, b) => new Date(b.completedAt ?? b.createdAt).getTime() - new Date(a.completedAt ?? a.createdAt).getTime())
    else if (sortBy === 'longest') list.sort((a, b) => elapsed(b.createdAt) - elapsed(a.createdAt))
    else if (sortBy === 'errors') list.sort((a, b) => {
      const isErr = (s: string) => s === 'failed' || s === 'cleanup_failed' || s === 'partially_succeeded'
      return (isErr(b.status) ? 1 : 0) - (isErr(a.status) ? 1 : 0)
    })

    return list
  }, [tasks, statusFilter, typeFilter, timeFilter, sortBy, search])

  const statCards = STATUS_FILTERS.map(f => ({
    ...f,
    count: countTasks(tasks, f.key),
  }))

  const queuedTasks = tasks.filter(t => t.status === 'pending' || t.status === 'queued')
  const cancellableSelected = [...selectedIds].filter(id => {
    const t = tasks.find(x => x.id === id)
    return t && ['pending', 'queued', 'running'].includes(t.status)
  })

  const handleBulkCancel = async () => {
    setBulkCancelling(true)
    setBulkResult(null)
    let succeeded = 0
    let failed = 0
    // Build cancellable task list without non-null assertions
    const cancellableTasks: BgTask[] = []
    for (const id of selectedIds) {
      const t = tasks.find(x => x.id === id)
      if (t && ['pending', 'queued', 'running'].includes(t.status)) {
        cancellableTasks.push(t)
      }
    }
    // Parallel cancel — all fire at once
    const results = await Promise.allSettled(
      cancellableTasks.map(t => cancelTask(t)),
    )
    for (const r of results) {
      if (r.status === 'fulfilled') succeeded++
      else failed++
    }
    setBulkResult(failed === 0 ? `已取消 ${succeeded} 个任务` : `已取消 ${succeeded} 个，${failed} 个失败`)
    setSelectedIds(new Set())
    setBulkCancelling(false)
    setTimeout(() => setBulkResult(null), 3000)
  }

  return (
    <div className="tc-page">
      {/* ═══ Header ═══════════════════════════════════════════════════════ */}
      <div className="tc-header">
        <div>
          <h2 className="tc-title">后台任务中心</h2>
          <p className="tc-subtitle">统一管理后台运行中的 LLM 提取及异步任务</p>
        </div>
        <div className="tc-header-actions">
          {bulkResult && (
            <span style={{ fontSize: 12, color: bulkResult.includes('失败') ? '#dc2626' : '#16a34a', fontWeight: 600 }}>
              {bulkResult}
            </span>
          )}
          {selectedIds.size > 0 && (
            <>
              <span style={{ fontSize: 12, color: '#666' }}>已选 {selectedIds.size} · 可取消 {cancellableSelected.length}</span>
              <button className="btn" style={{ color: '#dc2626', borderColor: '#dc2626' }}
                disabled={bulkCancelling || cancellableSelected.length === 0}
                onClick={handleBulkCancel}>
                {bulkCancelling ? '取消中…' : `取消选中 (${cancellableSelected.length})`}
              </button>
              <button className="btn" onClick={() => setSelectedIds(new Set())}>清除选择</button>
            </>
          )}
          <button className="btn" onClick={() => setSelectedIds(new Set(queuedTasks.map(t => t.id)))}>
            全选排队 ({queuedTasks.length})
          </button>
          <input className="tc-search" placeholder="搜索任务名 / ID / 类型…" value={search}
            onChange={e => setSearch(e.target.value)} />
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
            <button
              className={`tc-filter-item${typeFilter === 'all' ? ' active' : ''}`}
              onClick={() => setTypeFilter('all')}>
              全部
            </button>
            {TASK_TYPE_OPTIONS.map(f => {
              const def = getTaskDef(f.key)
              return (
                <button key={f.key}
                  className={`tc-filter-item${typeFilter === f.key ? ' active' : ''}`}
                  onClick={() => setTypeFilter(f.key)}>
                  {def.icon} {f.label}
                </button>
              )
            })}
          </FilterGroup>

          <FilterGroup title="时间">
            {TIME_FILTERS.map(f => (
              <button key={f.key}
                className={`tc-filter-item${timeFilter === f.key ? ' active' : ''}`}
                onClick={() => setTimeFilter(f.key)}>
                {f.label}
              </button>
            ))}
          </FilterGroup>

          <FilterGroup title="排序">
            {SORT_OPTIONS.map(f => (
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
          {filtered.length === 0 && loading && tasks.length === 0 ? (
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
  const taskDef = getTaskDef(task.type)
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
            {taskDef.icon} {taskDef.label(task)}
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
            <strong>{taskDef.label(task).split(' · ')[0]}</strong>
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
  const taskDef = getTaskDef(task.type)
  const isRunning = task.status === 'running' || task.status === 'pending' || task.status === 'queued'

  return (
    <>
      <div className="tc-drawer-header">
        <h3>{taskDef.icon} {taskDef.label(task)}</h3>
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
