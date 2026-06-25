import type { ReactNode } from 'react'
import type { MacroPipelineStepProgress } from './macroClinicalPipelineTypes'

const STATUS_CLASS: Record<string, string> = {
  not_started: 'macro-pipeline-status-not-started',
  ready: 'macro-pipeline-status-ready',
  running: 'macro-pipeline-status-running',
  warning: 'macro-pipeline-status-warning',
  completed: 'macro-pipeline-status-completed',
}

const STATUS_LABEL: Record<string, string> = {
  not_started: '未开始',
  ready: '就绪',
  running: '运行中',
  warning: '有警告',
  completed: '已完成',
}

const STEP_BOUNDARY: Partial<Record<string, string>> = {
  cross_validation: '不调用 LLM；只写 cross validation runs/results；可选更新 membership.verification_status。',
  dual_model_verification: '会分别调用 DeepSeek 与 Kimi；结果不自动 approve/review/promote。',
}

function primaryActionLabel(status: string): string {
  switch (status) {
    case 'not_started': return '查看输入要求'
    case 'ready': return '开始本步骤'
    case 'warning': return '查看问题'
    case 'completed': return '查看结果 / 重新运行'
    default: return '展开'
  }
}

interface MacroPipelineCardProps {
  step: MacroPipelineStepProgress
  expanded: boolean
  onToggle: () => void
  onOpenResults?: () => void
  children?: ReactNode
}

export function MacroPipelineCard({
  step,
  expanded,
  onToggle,
  onOpenResults,
  children,
}: MacroPipelineCardProps) {
  const isReady = step.status === 'ready'
  const isWarning = step.status === 'warning'
  const boundary = STEP_BOUNDARY[step.id]

  return (
    <div
      className={[
        'macro-pipeline-card',
        expanded ? 'macro-pipeline-card-expanded' : '',
        `macro-pipeline-card-status-${step.status}`,
        isReady ? 'macro-pipeline-card-recommended' : '',
      ].filter(Boolean).join(' ')}
    >
      {/* Compact header — always visible */}
      <div
        className="macro-pipeline-card-header"
        onClick={onToggle}
        role="button"
        tabIndex={0}
        onKeyDown={e => e.key === 'Enter' && onToggle()}
      >
        <span className="macro-pipeline-step-index">{step.index}</span>
        <div className="macro-pipeline-card-main">
          <div className="macro-pipeline-card-title-row">
            <strong className="macro-pipeline-card-title">{step.title}</strong>
            <span className={`macro-pipeline-status ${STATUS_CLASS[step.status] ?? ''}`}>
              {STATUS_LABEL[step.status] ?? step.status}
            </span>
          </div>
          <div className="macro-pipeline-card-subtitle">{step.subtitle}</div>
          <div className="macro-pipeline-card-meta">
            <span className="macro-pipeline-count-chip">输入: {step.inputLabel}</span>
            {step.inputCount !== undefined && (
              <span className="macro-pipeline-count-chip macro-pipeline-count-num">{step.inputCount}</span>
            )}
            <span className="macro-pipeline-count-chip">→ 输出: {step.outputLabel}</span>
            {step.outputCount !== undefined && (
              <span className="macro-pipeline-count-chip macro-pipeline-count-num">{step.outputCount}</span>
            )}
            {step.warningCount !== undefined && step.warningCount > 0 && (
              <span className="macro-pipeline-count-chip macro-pipeline-warning">⚠ {step.warningCount}</span>
            )}
          </div>
        </div>
        <div className="macro-pipeline-card-actions" onClick={e => e.stopPropagation()}>
          <button type="button" className="btn btn-sm" onClick={onToggle}>
            {primaryActionLabel(step.status)}
          </button>
          {onOpenResults && (step.outputCount ?? 0) > 0 && (
            <button type="button" className="btn btn-sm" onClick={onOpenResults}>
              查看结果
            </button>
          )}
          <span className="macro-pipeline-expand-icon" aria-hidden>{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      {/* Step-specific boundary if applicable */}
      {boundary && !expanded && isWarning && (
        <div className="macro-pipeline-warning" style={{ padding: '4px 16px 4px 52px', fontSize: 11 }}>
          ⚠ {boundary}
        </div>
      )}

      {/* Expanded workspace */}
      {expanded && (
        <div className="macro-pipeline-card-body">
          {boundary && (
            <div className="macro-pipeline-boundary" style={{ marginBottom: 12, fontSize: 12 }}>
              ⚠ {boundary}
            </div>
          )}
          {children}
        </div>
      )}
    </div>
  )
}
