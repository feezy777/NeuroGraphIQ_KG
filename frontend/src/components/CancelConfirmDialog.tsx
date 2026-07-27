import { cancelTask } from '../services/taskRegistry'
import type { BgTask } from '../hooks/useBackgroundTasks'

interface Props { task: BgTask; onClose: () => void }

export function CancelConfirmDialog({ task, onClose }: Props) {
  const handleConfirm = async () => {
    try {
      await cancelTask(task)
    } catch { /* ignore */ }
    onClose()
  }

  return (
    <div className="tc-cancel-overlay" onClick={onClose}>
      <div className="tc-cancel-dialog" onClick={e => e.stopPropagation()}>
        <h4>确认取消任务？</h4>
        <p style={{ fontSize: 13, color: '#666' }}>{task.label}</p>
        <code style={{ fontSize: 11 }}>{task.id.slice(0, 12)}…</code>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
          <button className="btn" onClick={onClose}>返回</button>
          <button className="btn" style={{ color: '#dc2626', borderColor: '#dc2626' }} onClick={handleConfirm}>
            确认取消
          </button>
        </div>
      </div>
    </div>
  )
}
