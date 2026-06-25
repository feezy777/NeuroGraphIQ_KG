import type { WorkflowStageProgress, StageId } from './workflowTypes'

interface WorkflowProgressBarProps {
  stages: WorkflowStageProgress[]
  activeStageId: StageId
  onStageClick: (stageId: StageId) => void
}

const STATUS_COLOR: Record<string, string> = {
  not_started: '#d9d9d9',
  ready: '#91caff',
  running: '#4096ff',
  warning: '#faad14',
  completed: '#52c41a',
}

export function WorkflowProgressBar({ stages, activeStageId, onStageClick }: WorkflowProgressBarProps) {
  return (
    <div className="workflow-progress-bar">
      {stages.map((stage, idx) => {
        const isActive = stage.id === activeStageId
        const isCompleted = stage.status === 'completed'
        const isWarning = stage.status === 'warning'
        return (
          <div
            key={stage.id}
            className={[
              'workflow-progress-step',
              isActive ? 'workflow-progress-step-active' : '',
              isCompleted ? 'workflow-progress-step-completed' : '',
              isWarning ? 'workflow-progress-step-warning' : '',
            ].filter(Boolean).join(' ')}
            onClick={() => onStageClick(stage.id)}
            role="button"
            tabIndex={0}
            onKeyDown={e => e.key === 'Enter' && onStageClick(stage.id)}
            title={stage.description}
          >
            <div className="workflow-progress-step-num">
              {isCompleted ? '✓' : isWarning ? '⚠' : idx + 1}
            </div>
            <div className="workflow-progress-step-label">{stage.label}</div>
            <div className="workflow-progress-step-bar">
              <div
                className="workflow-progress-step-fill"
                style={{
                  width: `${stage.percent}%`,
                  background: STATUS_COLOR[stage.status] ?? '#d9d9d9',
                }}
              />
            </div>
            <div className="workflow-progress-step-pct">{stage.percent}%</div>
            {stage.warnings > 0 && (
              <div className="workflow-progress-step-warn-badge">{stage.warnings}</div>
            )}
            {idx < stages.length - 1 && <div className="workflow-progress-line">→</div>}
          </div>
        )
      })}
    </div>
  )
}
