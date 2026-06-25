import type { WorkflowStageProgress, StageId } from './workflowTypes'

interface WorkflowStageRailProps {
  stages: WorkflowStageProgress[]
  activeStageId: StageId
  onStageClick: (stageId: StageId) => void
}

const STATUS_BADGE: Record<string, string> = {
  not_started: '○',
  ready: '◔',
  running: '◑',
  warning: '⚠',
  completed: '●',
}

const STATUS_CLASS: Record<string, string> = {
  not_started: 'stage-status-not-started',
  ready: 'stage-status-ready',
  running: 'stage-status-running',
  warning: 'stage-status-warning',
  completed: 'stage-status-completed',
}

export function WorkflowStageRail({ stages, activeStageId, onStageClick }: WorkflowStageRailProps) {
  return (
    <nav className="workflow-stage-rail">
      {stages.map((stage, idx) => {
        const isActive = stage.id === activeStageId
        return (
          <div
            key={stage.id}
            className={`workflow-stage-rail-item${isActive ? ' workflow-stage-rail-item-active' : ''}`}
            onClick={() => onStageClick(stage.id)}
            role="button"
            tabIndex={0}
            onKeyDown={e => e.key === 'Enter' && onStageClick(stage.id)}
          >
            <div className="workflow-stage-rail-header">
              <span className="workflow-stage-rail-num">{idx + 1}</span>
              <span className="workflow-stage-rail-name">{stage.label}</span>
              <span className={`workflow-stage-rail-status ${STATUS_CLASS[stage.status] ?? ''}`}>
                {STATUS_BADGE[stage.status] ?? '○'}
              </span>
            </div>
            <div className="workflow-stage-percent">
              <div
                className="workflow-stage-percent-fill"
                style={{ width: `${stage.percent}%` }}
              />
              <span className="workflow-stage-percent-label">{stage.percent}%</span>
            </div>
            {isActive && stage.checks.length > 0 && (
              <ul className="workflow-stage-checklist">
                {stage.checks.map(c => (
                  <li
                    key={c.id}
                    className={`workflow-stage-checkitem${c.done ? ' done' : ''}`}
                  >
                    {c.done ? '✓' : '○'} {c.label}
                  </li>
                ))}
              </ul>
            )}
            {isActive && stage.warnings > 0 && (
              <div className="workflow-stage-warning-count">
                ⚠ {stage.warnings} 个警告
              </div>
            )}
          </div>
        )
      })}
    </nav>
  )
}
