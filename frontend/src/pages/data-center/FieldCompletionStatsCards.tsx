import { StatusBadge } from '../../components/StatusBadge'
import { ModelBadge } from '../../components/ModelBadge'
import type { FieldCompletionRunDetail } from '../../api/endpoints'

// ── Props ───────────────────────────────────────────────────────────────────

export interface FieldCompletionStatsCardsProps {
  detail: FieldCompletionRunDetail | null
  status: string
  targetCount: number
  elapsedSec: number
  onCancel?: () => void
  onClose: () => void
  cancelling?: boolean
}

// ── Helpers ─────────────────────────────────────────────────────────────────

const TERMINAL = new Set(['succeeded', 'partially_succeeded', 'failed', 'cancelled'])
function isTerminal(s: string) { return TERMINAL.has(s) }

function elapsedStr(sec: number): string {
  if (sec < 60) return `${Math.round(sec)}s`
  return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`
}

function estimateCost(inputTokens: number, outputTokens: number): string {
  const cost = (inputTokens / 1_000_000) * 1.0 + (outputTokens / 1_000_000) * 2.0
  if (cost < 0.01) return '< ¥0.01'
  return `¥${cost.toFixed(2)}`
}

// ── Component ───────────────────────────────────────────────────────────────

export function FieldCompletionStatsCards({
  detail,
  status,
  targetCount,
  elapsedSec,
  onCancel,
  onClose,
  cancelling = false,
}: FieldCompletionStatsCardsProps) {
  const summary: Record<string, number> = (detail?.summary_json || {}) as Record<string, number>
  const items = detail?.items ?? []
  const itemCount = items.length
  const terminal = isTerminal(status)

  // During execution: use incremental progress from summary_json
  // After completion: use final committed counts
  const totalPacks = summary.total_packs ?? 0
  const processedPacks = summary.processed_packs ?? 0
  const currentField = (detail?.summary_json as any)?.current_field ?? ''
  const processedItems = summary.processed_items ?? 0
  const liveModelCalls = summary.model_call_count ?? 0

  // Live counts during execution (from incremental commits)
  const liveApplied = summary.llm_applied ?? 0
  const liveSkipped = summary.skipped_existing ?? 0
  const updated = terminal ? (summary.updated_count ?? 0) : liveApplied
  const suggested = terminal ? (summary.suggested_count ?? 0) : 0
  const skipped = terminal ? (summary.skipped_count ?? 0) : liveSkipped
  const failed = terminal ? (summary.failed_count ?? 0) : 0
  const modelCalls = terminal ? (summary.model_call_count ?? 0) : liveModelCalls
  const estInput = terminal ? (summary.estimated_input_tokens ?? 0) : 0
  const estOutput = terminal ? (summary.estimated_output_tokens ?? 0) : 0
  const fieldCount = terminal
    ? (summary.llm_fields_count ?? summary.deterministic_fields_count ?? itemCount)
    : (itemCount || targetCount * 3)
  const applied = terminal ? ((summary.applied_direct_count ?? 0) + (summary.applied_overlay_count ?? 0)) : 0
  const totalFields = fieldCount || Math.max(itemCount, 1)
  const processed = terminal ? itemCount : processedItems
  const progressPct = terminal ? 100
    : totalPacks > 0 ? Math.min(99, Math.round((processedPacks / totalPacks) * 100))
    : processedItems > 0 ? Math.min(99, Math.round((processedItems / Math.max(totalFields, 1)) * 100))
    : 0

  const isSuccess = status === 'succeeded'
  const isPartial = status === 'partially_succeeded'
  const isFailed = status === 'failed' || status === 'cancelled'
  const isRunning = !terminal

  const errors: string[] = (detail?.errors_json ?? []) as string[]

  return (
    <div className="dc-fc-stats">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="dc-fc-stats-header">
        <h3>
          {cancelling ? '🛑 正在取消任务...' :
           status === 'pending' ? '⏳ 排队等待执行...' :
           status === 'running' ? '🔧 正在执行字段补全' :
           isSuccess ? '✅ 字段补全完成' :
           isPartial ? '⚠️ 部分完成' :
           isFailed ? '❌ 执行失败' : `状态: ${status}`}
        </h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <ModelBadge provider={detail?.provider} modelName={detail?.model_name ?? undefined} />
          <button className="btn-close" onClick={onClose}>✕</button>
        </div>
      </div>

      {/* ── Body ────────────────────────────────────────────────────────── */}
      <div className="dc-fc-stats-body">
        {/* Status banner */}
        <div className={`dc-fc-stats-banner ${cancelling ? 'warning' : isSuccess ? 'success' : isPartial ? 'warning' : isFailed ? 'error' : 'running'}`}>
          <div className="dc-fc-stats-banner-title">
            {cancelling ? '正在通知后端停止执行，请稍候...' :
             status === 'pending' ? '任务已提交，等待后台执行...' :
             status === 'running' ? `执行中 · ${elapsedStr(elapsedSec)}` :
             isSuccess ? '所有字段补全成功' :
             isPartial ? '部分字段补全成功' :
             isFailed ? status === 'cancelled' ? '任务已取消' : '执行失败' : status}
          </div>
          {!terminal && (
            <div className="dc-fc-stats-banner-sub">
              {targetCount} 个目标 · {processed} 项已处理 · {elapsedStr(elapsedSec)}
            </div>
          )}
        </div>

        {/* Progress bar — indeterminate during running */}
        {isRunning && (
          <div className="dc-fc-progress">
            <div className="dc-fc-progress-track">
              <div className={`dc-fc-progress-fill${processed === 0 ? ' dc-fc-progress-indeterminate' : ''}`}
                style={processed > 0 ? { width: `${progressPct}%`, animation: 'none' } : undefined} />
            </div>
            <div className="dc-fc-progress-label">
              <span>{totalPacks > 0
                ? `包 ${processedPacks}/${totalPacks}${currentField ? ` · ${currentField}` : ''}`
                : processed > 0
                  ? `已处理 ${processed}/${totalFields} 个字段`
                  : 'LLM 调用中，等待首批响应...'}</span>
              <span>{progressPct > 0 ? `${progressPct}%` : ''}</span>
            </div>
          </div>
        )}

        {/* Two-column stat cards */}
        <div className="dc-fc-stats-grid">
          <div className="dc-fc-stats-col">
            <div className="dc-fc-stats-col-title">{terminal ? '执行概览' : '预估'}</div>
            <div className="dc-fc-stats-cards">
              <StatCard label="总字段" value={totalFields} color="#1e40af" bg="#eff6ff" />
              <StatCard label={terminal ? '已处理字段' : totalPacks > 0 ? `包 ${processedPacks}/${totalPacks}` : '目标数'} value={terminal ? processed : (totalPacks > 0 ? processedPacks : targetCount)} color="#2563eb" bg="#eff6ff" />
              <StatCard label="模型调用" value={modelCalls} color={modelCalls > 0 ? '#7c3aed' : '#9ca3af'} bg={modelCalls > 0 ? '#f5f3ff' : '#f9fafb'} />
            </div>
          </div>
          <div className="dc-fc-stats-col">
            <div className="dc-fc-stats-col-title">{terminal ? '补全结果' : '状态'}</div>
            <div className="dc-fc-stats-cards">
              <StatCard label="已更新" value={updated} color="#16a34a" bg="#f0fdf4" />
              <StatCard label="已建议" value={suggested} color={suggested > 0 ? '#2563eb' : '#9ca3af'} bg={suggested > 0 ? '#eff6ff' : '#f9fafb'} />
              <StatCard label="已跳过" value={skipped} color={skipped > 0 ? '#d97706' : '#9ca3af'} bg={skipped > 0 ? '#fffbeb' : '#f9fafb'} />
              <StatCard label="失败" value={failed} color={failed > 0 ? '#dc2626' : '#9ca3af'} bg={failed > 0 ? '#fef2f2' : '#f9fafb'} />
            </div>
          </div>
        </div>

        {/* Usage row */}
        <div className="dc-fc-stats-usage">
          <span>🕐 {elapsedStr(elapsedSec)}</span>
          {terminal && <span>{targetCount} 个目标 · {processed} 个字段</span>}
          {(estInput > 0 || estOutput > 0) && (
            <>
              <span className="dc-fc-stats-usage-sep">|</span>
              <span>📥 ~{estInput.toLocaleString()}</span>
              <span>📤 ~{estOutput.toLocaleString()}</span>
              <span className="dc-fc-stats-cost">💰 {estimateCost(estInput, estOutput)}</span>
            </>
          )}
        </div>

        {/* Items table (terminal only) */}
        {terminal && items.length > 0 && (
          <div className="dc-fc-stats-table-wrap">
            <table className="dc-fc-stats-table">
              <thead>
                <tr>
                  <th>字段</th>
                  <th>状态</th>
                  <th>新值</th>
                </tr>
              </thead>
              <tbody>
                {items.slice(0, 50).map((item, i) => (
                  <tr key={i}>
                    <td className="dc-fc-stats-field">{item.field_name}</td>
                    <td><StatusBadge status={item.update_status} /></td>
                    <td className="dc-fc-stats-value">
                      {item.applied_value_json != null
                        ? typeof item.applied_value_json === 'string'
                          ? item.applied_value_json.slice(0, 60)
                          : JSON.stringify(item.applied_value_json).slice(0, 60)
                        : item.suggested_value_json != null
                          ? typeof item.suggested_value_json === 'string'
                            ? item.suggested_value_json.slice(0, 60)
                            : JSON.stringify(item.suggested_value_json).slice(0, 60)
                          : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Errors */}
        {errors.length > 0 && (
          <details className="dc-fc-stats-errors">
            <summary>异常 ({errors.length})</summary>
            {errors.slice(0, 10).map((e, i) => (
              <div key={i}>{e.length > 150 ? e.slice(0, 150) + '…' : e}</div>
            ))}
          </details>
        )}
      </div>

      {/* ── Footer ──────────────────────────────────────────────────────── */}
      {!terminal && (
        <div className="dc-fc-stats-footer">
          {onCancel && (
            <button className="llm-btn llm-btn-danger" onClick={onCancel} disabled={cancelling}>
              {cancelling ? '取消中…' : '取消任务'}
            </button>
          )}
          <button className="llm-btn" onClick={onClose}>后台运行</button>
        </div>
      )}
      {terminal && (
        <div className="dc-fc-stats-footer">
          <button className="llm-btn llm-btn-primary" onClick={onClose}>关闭</button>
        </div>
      )}
    </div>
  )
}

// ── Mini stat card ──────────────────────────────────────────────────────────

function StatCard({ label, value, color, bg }: { label: string; value: number; color: string; bg: string }) {
  return (
    <div className="dc-fc-stat-card" style={{ background: bg, borderColor: `${color}20` }}>
      <div className="dc-fc-stat-value" style={{ color }}>{value}</div>
      <div className="dc-fc-stat-label">{label}</div>
    </div>
  )
}
