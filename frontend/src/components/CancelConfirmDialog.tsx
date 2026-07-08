import { cancelFieldCompletionRun, cancelCompositeWorkflow, cancelCircuitExtractionRun, cancelCircuitConnectionExtractionRun } from '../api/endpoints'
import type { BgTask } from '../hooks/useBackgroundTasks'

interface Props { task: BgTask; onClose: () => void }

export function CancelConfirmDialog({ task, onClose }: Props) {
  const handleConfirm = async () => {
    try {
      if (task.type === 'field_completion') await cancelFieldCompletionRun(task.id)
      else if (task.type === 'circuit_connection_extraction') await cancelCircuitConnectionExtractionRun(task.id)
      else await cancelCompositeWorkflow(task.id)
    } catch { /* ignore */ }
    onClose()
  }

  return (
    <div className="tc-cancel-overlay" onClick={onClose}>
      <div className="tc-cancel-dialog" onClick={e => e.stopPropagation()}>
        <h4>确认取消任务？</h4>
        <p style={{ fontSize: 13, color: '#666' }}>{task.label}</p>
        <code style={{ fontSize: 11 }}>{task.id}</code>
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
