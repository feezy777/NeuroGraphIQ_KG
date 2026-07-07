import { useState } from 'react'
import { StatusBadge } from './StatusBadge'
import { ModelBadge } from './ModelBadge'
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

export function TaskCenterDropdown({ tasks, loading, onViewAll, onViewTask, onOpen, onClose }: Props) {
  const [open, setOpen] = useState(false)

  const toggle = () => {
    const next = !open
    setOpen(next)
    if (next) onOpen?.()
    else onClose?.()
  }

  const running = tasks.filter(t => t.status === 'running' || t.status === 'pending')
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
              ) : running.length === 0 ? (
                <div style={{ padding: 16, textAlign: 'center', color: '#888' }}>无运行中任务</div>
              ) : (
                running.slice(0, 8).map(task => (
                  <button key={task.id} className="task-center-item"
                    onClick={() => { setOpen(false); onViewTask(task) }}>
                    <span className="task-center-item-icon">
                      {task.type === 'field_completion' ? '🔧' : task.type === 'circuit_extraction' ? '⭕' : '🔗'}
                    </span>
                    <span className="task-center-item-label">{task.label}</span>
                    <ModelBadge provider={task.provider} modelName={task.modelName} />
                    <StatusBadge status={task.status} />
                    <span className="task-center-item-time">{elapsed(task.createdAt)}</span>
                  </button>
                ))
              )}
            </div>
            {running.length > 0 && (
              <div className="task-center-panel-footer">
                最近完成: {tasks.filter(t => t.status === 'succeeded').length} 个
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
