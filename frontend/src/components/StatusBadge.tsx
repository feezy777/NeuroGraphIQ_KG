type BadgeColor = 'green' | 'blue' | 'amber' | 'red' | 'purple' | 'indigo' | 'teal' | 'gray'

const COLOR_MAP: Record<string, BadgeColor> = {
  // green — final / approved / passed
  active: 'green',
  succeeded: 'green',
  rule_passed: 'green',
  manual_approved: 'green',
  promoted_to_final: 'green',
  completed: 'green',
  ok: 'green',
  // blue — in progress / LLM suggested
  running: 'blue',
  queued: 'blue',
  rule_validating: 'blue',
  llm_validating: 'blue',
  manual_review_pending: 'blue',
  validation_dispatched: 'blue',
  llm_suggested: 'blue',
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
  // indigo — DeepSeek V4 Pro
  llm_v4_pro: 'indigo',
  applied_overlay: 'indigo',
  applied_direct: 'indigo',
  // violet — DeepSeek R1 (reasoner)
  llm_reasoner: 'purple',
  // teal — Kimi
  llm_kimi: 'teal',
  // gray — archived / inactive / cancelled / skipped
  archived: 'gray',
  cancelled: 'gray',
  inactive: 'gray',
  unknown: 'gray',
  skipped_missing: 'gray',
  skipped_invalid_field: 'gray',
  skipped_target_not_found: 'gray',
  suggested: 'gray',
}

export function StatusBadge({ status }: { status: string }) {
  const color = COLOR_MAP[status] ?? 'gray'
  const label = STATUS_LABEL[status] ?? status
  return <span className={`badge badge-${color}`}>{label}</span>
}

// ── Display labels: map internal status values to human-readable text ────────
const STATUS_LABEL: Record<string, string> = {
  // Model-tier labels
  llm_suggested: 'DeepSeek V3',
  llm_v4_pro: 'DeepSeek V4P',
  llm_reasoner: 'DeepSeek R1',
  llm_kimi: 'Kimi',
  // Common status labels
  applied_overlay: 'Overlay',
  applied_direct: '直接写入',
  suggested: '建议',
  skipped_missing: '跳过',
  skipped_invalid_field: '无效字段',
  skipped_target_not_found: '目标未找到',
  skipped_existing_value: '已有值',
  partially_succeeded: '部分成功',
  succeeded: '已完成',
  pending: '排队中',
  running: '运行中',
  cancelled: '已取消',
  failed: '失败',
  paused: '已暂停',
  pause_requested: '暂停中',
  queued: '队列中',
  // Human review / governance
  manual_approved: '已审核',
  manual_rejected: '已驳回',
  manual_review_pending: '待审核',
  promoted_to_final: '已晋升',
  rule_passed: '规则通过',
  rule_failed: '规则失败',
  // Evidence / data source
  active: '活跃',
  archived: '已归档',
  inactive: '未激活',
  unknown: '未知',
  error: '错误',
  completed: '已完成',
  ok: '正常',
  created: '已创建',
  parsed: '已解析',
  candidate_created: '候选已建',
  candidate_generated: '候选已生成',
  llm_not_required: '无需LLM',
  llm_passed: 'LLM通过',
  llm_validating: 'LLM校验中',
  llm_conflict: 'LLM冲突',
  llm_passed_conflict: 'LLM通过(冲突)',
  rule_validating: '规则校验中',
  validation_dispatched: '校验已派发',
  cleanup_failed: '清理失败',
  cleanup_done: '清理完成',
  no_edges: '无边',
  dry_run: '空跑',
}
