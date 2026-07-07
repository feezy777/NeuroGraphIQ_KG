import { useMemo } from 'react'
import type { DryRunPlan, StagePlan, CompositeWorkflowRunRequest } from '../../../api/endpoints'
import './DryRunDetailPanel.css'

type Props = {
  plan: DryRunPlan
  originalRequestPayload?: Record<string, unknown> | null
  onStartExtraction: (formalPayload: Record<string, unknown>) => void
  onClose?: () => void
  starting: boolean
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function fmtCost(n: number): string {
  if (n < 0) return 'N/A'
  if (n < 0.005) return '< ¥0.01'
  return `¥${n.toFixed(2)}`
}

function hasPrice(n: number): boolean {
  return n >= 0
}

function estimationBadge(method: string): { label: string; className: string } {
  switch (method) {
    case 'historical_usage':
      return { label: '基于历史', className: 'badge-historical' }
    case 'schema_based':
      return { label: '基于 Schema', className: 'badge-schema' }
    default:
      return { label: '粗略估算', className: 'badge-fallback' }
  }
}

function StageCard({ stage }: { stage: StagePlan }) {
  const badge = estimationBadge(stage.estimation_method)

  return (
    <div className="dryrun-stage-card">
      <div className="dryrun-stage-header">
        <span className="dryrun-stage-name">
          Step {stage.step_order}: {stage.stage_name === 'extract_connections' ? '连接提取' : stage.stage_name === 'extract_projection_functions' ? '功能提取' : stage.stage_name === 'connection_screening' ? '连接筛查' : stage.stage_name === 'connection_detail' ? '连接详情' : stage.stage_name === 'function_extraction' ? '功能提取' : stage.stage_name}
        </span>
        <span className={`dryrun-estimation-badge ${badge.className}`}>{badge.label}</span>
        {!stage.required && <span className="dryrun-stage-optional">可选</span>}
        {stage.depends_on && (
          <span className="dryrun-stage-depends">依赖: {stage.depends_on}</span>
        )}
      </div>

      <div className="dryrun-stage-grid">
        <div className="dryrun-metric">
          <span className="dryrun-metric-label">计划 LLM 调用数</span>
          <span className="dryrun-metric-value">{stage.planned_call_count} 次</span>
        </div>
        <div className="dryrun-metric">
          <span className="dryrun-metric-label">预估输入 Tokens</span>
          <span className="dryrun-metric-value">{fmtTokens(stage.total_input_tokens)}</span>
        </div>
        <div className="dryrun-metric">
          <span className="dryrun-metric-label">预估输出 Tokens</span>
          <span className="dryrun-metric-value">{fmtTokens(stage.total_expected_output_tokens)}</span>
        </div>
        <div className="dryrun-metric">
          <span className="dryrun-metric-label">最大输出 Tokens</span>
          <span className="dryrun-metric-value dryrun-metric-secondary">{fmtTokens(stage.total_max_output_tokens)}</span>
        </div>
      </div>

      <div className="dryrun-stage-costs">
        {hasPrice(stage.total_base_cost) ? (
          <>
            <div className="dryrun-cost-row">
              <span className="dryrun-cost-label">基础预估费用</span>
              <span className="dryrun-cost-value">{fmtCost(stage.total_base_cost)}</span>
            </div>
            {stage.total_retry_risk_cost > 0 && (
              <div className="dryrun-cost-row dryrun-cost-risk">
                <span className="dryrun-cost-label">Retry 风险费用</span>
                <span className="dryrun-cost-value">{fmtCost(stage.total_retry_risk_cost)}</span>
              </div>
            )}
            <div className="dryrun-cost-row dryrun-cost-upper">
              <span className="dryrun-cost-label">最坏情况上限</span>
              <span className="dryrun-cost-value">{fmtCost(stage.total_upper_bound_cost)}</span>
            </div>
          </>
        ) : (
          <div className="dryrun-cost-row">
            <span className="dryrun-cost-label" style={{ color: '#dc2626' }}>价格未配置，无法估算</span>
          </div>
        )}
      </div>
    </div>
  )
}

export function DryRunDetailPanel({ plan, originalRequestPayload, onStartExtraction, onClose, starting }: Props) {
  const stages = plan.stages || []
  const summaryBadge = useMemo(() => {
    const methods = stages.map(s => s.estimation_method)
    if (methods.every(m => m === 'historical_usage')) return estimationBadge('historical_usage')
    if (methods.some(m => m === 'historical_usage')) return estimationBadge('schema_based')
    return estimationBadge('fallback')
  }, [stages])

  // Compute disabled reason from plan data
  const priceMissing = (plan.pricing_missing || []).length > 0
  const candidateIds = (originalRequestPayload as any)?.candidate_ids as string[] | undefined
  const budgetCny = plan.budget_cny ?? 10
  const budgetExceeded = hasPrice(plan.total_base_cost) && plan.total_base_cost > budgetCny
  const hasOriginalPayload = !!originalRequestPayload
  const hasCandidates = (candidateIds?.length ?? 0) >= 2

  const disabledReason: string | null =
    priceMissing ? '模型价格未配置，无法开始正式提取'
    : !hasOriginalPayload ? '缺少原始 Dry Run 请求参数，无法开始正式提取'
    : !hasCandidates ? '请至少选择 2 个脑区'
    : budgetExceeded ? `预计费用 ¥${plan.total_base_cost.toFixed(2)} 超过预算 ¥${budgetCny.toFixed(2)}，请调整预算后再开始`
    : null

  const upperBoundWarning = hasPrice(plan.total_upper_bound_cost) && plan.total_upper_bound_cost > budgetCny * 2
    ? `⚠️ 最坏情况 ¥${plan.total_upper_bound_cost.toFixed(2)} 远超预算 ¥${budgetCny.toFixed(2)}，建议增加预算`
    : null

  const handleStart = () => {
    if (disabledReason) {
      console.debug('[DryRunDetailPanel] start disabled', {
        reason: disabledReason,
        priceMissing,
        budgetExceeded,
        hasOriginalRequestPayload: hasOriginalPayload,
        candidate_ids_length: candidateIds?.length ?? 0,
      })
      return
    }

    const formalPayload = {
      ...(originalRequestPayload || {}),
      plan_only: false,
    }

    console.debug('[DryRunDetailPanel] start formal extraction clicked', {
      workflow_type: (formalPayload as any).workflow_type,
      extraction_mode: (formalPayload as any).extraction_mode,
      candidate_ids_length: (candidateIds?.length ?? 0),
      plan_only: false,
      budget_cny: (formalPayload as any).budget_cny,
    })

    onStartExtraction(formalPayload)
  }

  // Guard against malformed plan data — no stages and no warnings means the backend
  // failed to produce a usable plan, so extraction must not be allowed.
  if (!stages.length && !plan.warnings?.length) {
    return (
      <div className="dryrun-panel-root">
        <div className="dryrun-panel-body" style={{ overflow: 'auto', flex: 1 }}>
          <div className="dryrun-panel-header">
            <h3>Dry Run 费用明细</h3>
          </div>
          <div className="dryrun-warnings">
            <div className="dryrun-warning">⚠️ 无法生成费用计划 — 请检查后端日志</div>
          </div>
        </div>
        <div className="dryrun-panel-footer">
          {onClose && <button className="llm-btn" onClick={onClose}>关闭</button>}
        </div>
      </div>
    )
  }

  return (
    <div className="dryrun-panel-root">
      <div className="dryrun-panel-header">
        <h3>Dry Run 费用明细</h3>
        <span className={`dryrun-estimation-badge ${summaryBadge.className}`}>{summaryBadge.label}</span>
      </div>

      <div className="dryrun-panel-body" style={{ overflow: 'auto', flex: 1 }}>
        <div className="dryrun-summary-row">
          <div className="dryrun-summary-item">
            <span className="dryrun-summary-label">Workflow</span>
            <span className="dryrun-summary-value">{plan.workflow_type}</span>
          </div>
          <div className="dryrun-summary-item">
            <span className="dryrun-summary-label">Mode</span>
            <span className="dryrun-summary-value">{plan.extraction_mode || 'exhaustive'}</span>
          </div>
          <div className="dryrun-summary-item">
            <span className="dryrun-summary-label">Provider / Model</span>
            <span className="dryrun-summary-value">{plan.provider} / {plan.model}</span>
          </div>
          <div className="dryrun-summary-item">
            <span className="dryrun-summary-label">Candidates</span>
            <span className="dryrun-summary-value">{plan.candidate_count}</span>
          </div>
          <div className="dryrun-summary-item">
            <span className="dryrun-summary-label">Pairs</span>
            <span className="dryrun-summary-value">{(plan.total_pair_count ?? plan.pair_count)?.toLocaleString()}</span>
          </div>
          <div className="dryrun-summary-item">
            <span className="dryrun-summary-label">总 LLM 调用数</span>
            <span className="dryrun-summary-value">{plan.total_planned_llm_calls}</span>
          </div>
          {(plan.skipped_existing_connections ?? 0) > 0 && (
            <div className="dryrun-summary-item">
              <span className="dryrun-summary-label">已跳过连接</span>
              <span className="dryrun-summary-value">{plan.skipped_existing_connections}</span>
            </div>
          )}
        </div>

        <div className="dryrun-stages">
          {stages.map((stage, idx) => (
            <StageCard key={idx} stage={stage} />
          ))}
        </div>

        <div className="dryrun-total-section">
          {!hasPrice(plan.total_base_cost) ? (
            <div className="dryrun-total-row">
              <span className="dryrun-total-label" style={{ color: '#dc2626' }}>
                ⚠️ 部分模型价格未配置，无法估算总费用
              </span>
            </div>
          ) : (
            <>
              <div className="dryrun-total-row">
                <span className="dryrun-total-label">总计预估费用 (Base)</span>
                <span className="dryrun-total-value">{fmtCost(plan.total_base_cost)}</span>
              </div>
              <div className="dryrun-total-row dryrun-total-upper">
                <span className="dryrun-total-label">最坏情况上限</span>
                <span className="dryrun-total-value">{fmtCost(plan.total_upper_bound_cost)}</span>
              </div>
              {plan.budget_cny != null && hasPrice(plan.total_base_cost) && (
                <div className="dryrun-total-row">
                  <span className="dryrun-total-label">预算对比</span>
                  <span className="dryrun-total-value" style={{ color: plan.total_base_cost > (plan.budget_cny ?? 0) ? '#dc2626' : '#16a34a' }}>
                    {plan.total_base_cost > (plan.budget_cny ?? 0) ? '超出' : '未超'}预算 ¥{(plan.budget_cny ?? 0).toFixed(2)}
                  </span>
                </div>
              )}
            </>
          )}
        </div>

        <div className="dryrun-meta">
          <span>💰 价格版本: {plan.pricing_model_version || 'unknown'}</span>
          <span>📦 Cache: {plan.cache_strategy}</span>
          {(plan.pricing_missing || []).length > 0 && (
            <span className="dryrun-pricing-missing">
              ⚠️ 未配置价格: {(plan.pricing_missing ?? []).join(', ')}
            </span>
          )}
          {stages.some(s => s.estimation_method === 'schema_based' || s.estimation_method === 'fallback') && (
            <span className="dryrun-estimation-note">
              📊 部分估算非基于历史数据，实际费用可能有偏差
            </span>
          )}
          {stages.length > 1 && stages[1]?.estimation_method !== 'historical_usage' && (
            <span className="dryrun-estimation-note">
              📊 Stage 2 连接数基于历史推算，实际可能有偏差
            </span>
          )}
          {upperBoundWarning && (
            <span className="dryrun-estimation-note" style={{ fontWeight: 600, color: '#d97706' }}>
              {upperBoundWarning}
            </span>
          )}
        </div>

        {(plan.warnings || []).length > 0 && (
          <div className="dryrun-warnings">
            {(plan.warnings ?? []).map((w, i) => (
              <div key={i} className="dryrun-warning">⚠️ {w}</div>
            ))}
          </div>
        )}
      </div>

      {/* Footer — always visible, sticky */}
      <div className="dryrun-panel-footer">
        {disabledReason && (
          <div className="dryrun-disabled-reason">无法开始：{disabledReason}</div>
        )}
        <div className="dryrun-footer-buttons">
          {onClose && <button className="llm-btn" onClick={onClose}>关闭</button>}
          <button
            className="llm-btn llm-btn-primary"
            onClick={handleStart}
            disabled={!!disabledReason || starting}
          >
            {starting ? '启动中...' : '开始正式提取'}
          </button>
        </div>
      </div>
    </div>
  )
}
