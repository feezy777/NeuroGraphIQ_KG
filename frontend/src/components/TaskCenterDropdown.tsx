import { useState, useCallback } from 'react'
import { StatusBadge } from './StatusBadge'
import { ModelBadge } from './ModelBadge'
import { CancelConfirmDialog } from './CancelConfirmDialog'
import { getTaskDef } from '../services/taskRegistry'
import { listUnifiedTasks } from '../api/endpoints'
import type { BgTask } from '../hooks/useBackgroundTasks'

interface Props {
  onViewAll: () => void
  onViewTask: (task: BgTask) => void
}

function elapsed(createdAt: string): string {
  const sec = Math.round((Date.now() - new Date(createdAt).getTime()) / 1000)
  if (sec < 60) return `${sec}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m`
  return `${Math.floor(sec / 3600)}h`
}

/**
 * Header bell-dropdown — fetch-on-open only, NO background polling.
 * Only the full task center page runs continuous polling.
 */
export function TaskCenterDropdown({ onViewAll, onViewTask }: Props) {
  const [open, setOpen] = useState(false)
  const [cancelTarget, setCancelTarget] = useState<BgTask | null>(null)
  const [tasks, setTasks] = useState<BgTask[]>([])
  const [loading, setLoading] = useState(false)

  const handleToggle = useCallback(async () => {
    const next = !open
    setOpen(next)
    if (next) {
      setLoading(true)
      try {
        const resp = await listUnifiedTasks({ limit: 40 })
        setTasks(resp.items.map(item => ({
          id: item.id,
          type: item.type,
          status: item.status,
          targetType: item.target_type,
          targetCount: item.target_count,
          label: item.label,
          provider: item.provider,
          modelName: item.model_name,
          createdAt: item.created_at,
          startedAt: item.started_at,
          completedAt: item.completed_at,
          detail: null,
        })))
      } catch { /* ignore */ }
      setLoading(false)
    }
  }, [open])

  const running = tasks.filter(t => t.status === 'running' || t.status === 'pending' || t.status === 'queued')
  const recent = tasks.filter(t => t.status !== 'running' && t.status !== 'pending' && t.status !== 'queued').slice(0, 5)
  const displayTasks = [...running, ...recent].slice(0, 12)
  const count = running.length

  return (
    <div className="task-center-dropdown" style={{ position: 'relative' }}>
      <button className="task-center-bell" onClick={handleToggle} title="后台任务">
        🔔
        {count > 0 && <span className="task-center-badge">{count}</span>}
      </button>

      {open && (
        <>
          <div className="task-center-overlay" onClick={() => setOpen(false)} />
          <div className="task-center-panel">
            <div className="task-center-panel-header">
              <strong>后台任务</strong>
              {count > 0 && <span style={{ color: 'var(--primary)', fontSize: 12 }}>{count} 个运行中</span>}
              <button className="btn btn-sm" onClick={() => { setOpen(false); onViewAll() }}>查看全部</button>
            </div>
            <div className="task-center-panel-body">
              {loading ? (
                <div style={{ padding: 16, textAlign: 'center', color: '#888' }}>加载中…</div>
              ) : displayTasks.length === 0 ? (
                <div style={{ padding: 16, textAlign: 'center', color: '#888' }}>无任务</div>
              ) : (
                displayTasks.map(task => {
                  const def = getTaskDef(task.type)
                  return (
                    <div key={task.id} className="task-center-item" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <button style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 6, border: 'none', background: 'none', cursor: 'pointer', padding: 0, textAlign: 'left' }}
                        onClick={() => { setOpen(false); onViewTask(task) }}>
                        <span className="task-center-item-icon">{def.icon}</span>
                        <span className="task-center-item-label" style={{ flex: 1 }}>{def.label(task)}</span>
                        <ModelBadge provider={task.provider} modelName={task.modelName} />
                        <StatusBadge status={task.status} />
                        <span className="task-center-item-time">{elapsed(task.createdAt)}</span>
                      </button>
                      {(task.status === 'running' || task.status === 'pending' || task.status === 'queued') && (
                        <button className="btn btn-xs" style={{ color: '#dc2626', fontSize: 11, padding: '2px 6px' }}
                          onClick={(e) => { e.stopPropagation(); setCancelTarget(task) }}>
                          ✕
                        </button>
                      )}
                    </div>
                  )
                })
              )}
            </div>
            <div className="task-center-panel-footer">
              总计 {tasks.length} 个任务 · 成功 {tasks.filter(t => t.status === 'succeeded').length}
            </div>
          </div>
        </>
      )}

      {cancelTarget && (
        <CancelConfirmDialog
          task={cancelTarget}
          onClose={() => setCancelTarget(null)}
        />
      )}
    </div>
  )
}
