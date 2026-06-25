interface WorkflowNextStepProps {
  nextStep: string
  loading?: boolean
}

export function WorkflowNextStep({ nextStep, loading }: WorkflowNextStepProps) {
  if (loading) return null
  return (
    <div className="workflow-next-step">
      <span className="workflow-next-step-label">下一步建议</span>
      <span className="workflow-next-step-action">{nextStep}</span>
    </div>
  )
}
