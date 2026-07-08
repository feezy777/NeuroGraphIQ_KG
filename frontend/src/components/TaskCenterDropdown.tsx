import { useState } from 'react'
import { StatusBadge } from './StatusBadge'
import { ModelBadge } from './ModelBadge'
import { CancelConfirmDialog } from './CancelConfirmDialog'
import type { BgTask } from '../hooks/useBackgroundTasks'

interface Props {
  tasks: BgTask[]
  loading: boolean
  onViewAll: () => void
  onViewTask: (task: BgTask) => void
  onOpen?: () => void
  onClose?: () => void
}

function elapsed(createdAt: string): string {
  const sec = Math.round((Date.now() - new Date(createdAt).getTime()) / 1000)
  if (sec < 60) return `${sec}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m`
  return `${Math.floor(sec / 3600)}h`
}

function taskIcon(type: string): string {
  if (type === 'field_completion') return '🔧'
  if (type === 'circuit_connection_extraction') return '🔄'
  if (type === 'composite_workflow') return '🔗'
  return '⭕'
}

export function TaskCenterDropdown({ tasks, loading, onViewAll, onViewTask, onOpen, onClose }: Props) {
  const [open, setOpen] = useState(false)
  const [cancelTarget, setCancelTarget] = useState<BgTask | null>(null)

  const toggle = () => {
    const next = !open
    setOpen(next)
    if (next) onOpen?.()
    else onClose?.()
  }

  const running = tasks.filter(t => t.status === 'running' || t.status === 'pending')
  const recent = tasks.filter(t => t.status !== 'running' && t.status !== 'pending').slice(0, 5)
  const displayTasks = [...running, ...recent]
  const count = running.length

  return (
    <div className="task-center-dropdown" style={{ position: 'relative' }}>
      <button className="task-center-bell" onClick={toggle} title="后台任务">
        🔔
        {count > 0 && <span className="task-center-badge">{count}</span>}
      </button>

      {open && (
        <>
          <div className="task-center-overlay" onClick={() => { setOpen(false); onClose?.() }} />
          <div className="task-center-panel">
            <div className="task-center-panel-header">
              <strong>后台任务</strong>
              {count > 0 && <span style={{ color: 'var(--primary)', fontSize: 12 }}>{count} 个运行中</span>}
              <button className="btn btn-sm" onClick={() => { setOpen(false); onClose?.(); onViewAll() }}>查看全部</button>
            </div>
            <div className="task-center-panel-body">
              {loading ? (
                <div style={{ padding: 16, textAlign: 'center', color: '#888' }}>加载中…</div>
              ) : displayTasks.length === 0 ? (
                <div style={{ padding: 16, textAlign: 'center', color: '#888' }}>无任务</div>
              ) : (
                displayTasks.slice(0, 10).map(task => (
                  <div key={task.id} className="task-center-item" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <button style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 6, border: 'none', background: 'none', cursor: 'pointer', padding: 0, textAlign: 'left' }}
                      onClick={() => { setOpen(false); onViewTask(task) }}>
                      <span className="task-center-item-icon">{taskIcon(task.type)}</span>
                      <span className="task-center-item-label" style={{ flex: 1 }}>{task.label}</span>
                      <ModelBadge provider={task.provider} modelName={task.modelName} />
                      <StatusBadge status={task.status} />
                      <span className="task-center-item-time">{elapsed(task.createdAt)}</span>
                    </button>
                    {(task.status === 'running' || task.status === 'pending') && (
                      <button className="btn btn-xs" style={{ color: '#dc2626', fontSize: 11, padding: '2px 6px' }}
                        onClick={(e) => { e.stopPropagation(); setCancelTarget(task) }}>
                        ✕
                      </button>
                    )}
                  </div>
                ))
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
