type BadgeColor = 'green' | 'blue' | 'amber' | 'red' | 'purple' | 'gray'

const COLOR_MAP: Record<string, BadgeColor> = {
  // green — final / approved / passed
  active: 'green',
  succeeded: 'green',
  rule_passed: 'green',
  manual_approved: 'green',
  promoted_to_final: 'green',
  completed: 'green',
  ok: 'green',
  // blue — in progress
  running: 'blue',
  queued: 'blue',
  rule_validating: 'blue',
  llm_validating: 'blue',
  manual_review_pending: 'blue',
  validation_dispatched: 'blue',
  // amber — created / pending start
  created: 'amber',
  parsed: 'amber',
  candidate_created: 'amber',
  candidate_generated: 'amber',
  llm_not_required: 'amber',
  llm_passed: 'amber',
  pending: 'amber',
  // red — failed / rejected
  failed: 'red',
  rule_failed: 'red',
  manual_rejected: 'red',
  llm_conflict: 'red',
  error: 'red',
  // purple — LLM
  llm_passed_conflict: 'purple',
  // gray — archived / inactive / cancelled
  archived: 'gray',
  cancelled: 'gray',
  inactive: 'gray',
  unknown: 'gray',
}

export function StatusBadge({ status }: { status: string }) {
  const color = COLOR_MAP[status] ?? 'gray'
  return <span className={`badge badge-${color}`}>{status}</span>
}
