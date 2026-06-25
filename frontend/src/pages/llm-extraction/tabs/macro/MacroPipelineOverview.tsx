import type { MacroPipelineStepProgress } from './macroClinicalPipelineTypes'

interface MacroPipelineOverviewProps {
  steps: MacroPipelineStepProgress[]
  nextStep: string
  hasError?: boolean
}

export function MacroPipelineOverview({ steps, nextStep, hasError }: MacroPipelineOverviewProps) {
  const completed = steps.filter(s => s.status === 'completed').length
  const warnings = steps.filter(s => s.status === 'warning').length
  const total = steps.length
  const percent = Math.round((completed / total) * 100)

  return (
    <div className="macro-pipeline-overview">
      <div className="macro-pipeline-overview-header">
        <span className="macro-pipeline-overview-title">Macro Clinical Pipeline</span>
        <div className="macro-pipeline-progress-wrap">
          <div className="macro-pipeline-progress">
            <div className="macro-pipeline-progress-fill" style={{ width: `${percent}%` }} />
          </div>
          <span className="macro-pipeline-progress-label">
            {completed}/{total} 步骤完成 ({percent}%)
          </span>
          {warnings > 0 && (
            <span className="macro-pipeline-warning-badge">⚠ {warnings} 个警告</span>
          )}
        </div>
      </div>

      <div className="macro-pipeline-boundary">
        ⚠ Macro Clinical Pipeline 只写 mirror_* 与 verification signals，不写 final_*，不写 kg_*，不同步外部正式库。
        Cross Validation 和 Dual-Model Verification 是审核信号，不是 final fact。
      </div>

      <div className="macro-pipeline-next-step">
        <span className="macro-pipeline-next-step-label">推荐下一步：</span>
        <span className="macro-pipeline-next-step-action">{nextStep}</span>
      </div>

      {hasError && (
        <div className="notice notice-warning" style={{ margin: '6px 0 0' }}>
          ⚠ 部分进度数据加载失败，已知状态正常显示。
        </div>
      )}
    </div>
  )
}
