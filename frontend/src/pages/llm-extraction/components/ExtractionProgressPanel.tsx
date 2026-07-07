import { useState } from 'react'
import { DryRunDetailPanel } from './DryRunDetailPanel'
import type { ProgressData } from '../types'

// ── Props ───────────────────────────────────────────────────────────────────

export interface ExtractionProgressPanelProps {
  progress: ProgressData
  onPause?: () => void
  onResume?: () => void
  onCancel: () => void
  onClose: () => void
  onRetryFailed?: () => void
  onViewResults?: () => void
  showRetry?: boolean
  showPause?: boolean
  workflowType?: string
  isDryRun?: boolean
  dryRunPlan?: unknown
  lastDryRunPayload?: Record<string, unknown> | null
  onStartExtraction?: (payload: Record<string, unknown>) => void
  starting?: boolean
  isPausing?: boolean
  isResuming?: boolean
  isCancelling?: boolean
  lastPollAt?: string
}

// ── Helpers ─────────────────────────────────────────────────────────────────

const TERMINAL_STATUSES = new Set([
  'succeeded',
  'partially_succeeded',
  'failed',
  'cancelled',
  'cleanup_done',
  'cleanup_failed',
  'no_edges',
  'succeeded_no_edges',
  'dry_run',
  'failed_provider_not_called',
  'failed_provider_empty_response',
  'failed_parse_error',
  'failed_no_output',
])

function isTerminalWorkflowStatus(status: string): boolean {
  return TERMINAL_STATUSES.has(status)
}

function shortId(id: string): string {
  return id.length > 10 ? `${id.slice(0, 10)}…` : id
}

function elapsedStr(sec: number): string {
  if (sec < 60) return `${Math.round(sec)}s`
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}m ${s}s`
}

function estimateCost(inputTokens: number, outputTokens: number): string {
  const inputPrice = 1.0   // ¥1 per 1M input tokens (DeepSeek CN)
  const outputPrice = 2.0  // ¥2 per 1M output tokens (DeepSeek CN)
  const cost = (inputTokens / 1_000_000) * inputPrice + (outputTokens / 1_000_000) * outputPrice
  if (cost < 0.01) return '< ¥0.01'
  return `¥${cost.toFixed(2)}`
}

// ── Component ───────────────────────────────────────────────────────────────

export function ExtractionProgressPanel({
  progress,
  onPause,
  onResume,
  onCancel,
  onClose,
  onRetryFailed,
  onViewResults,
  showRetry = false,
  showPause = true,
  workflowType,
  isDryRun = false,
  dryRunPlan,
  lastDryRunPayload,
  onStartExtraction,
  starting = false,
  isPausing = false,
  isResuming = false,
  isCancelling = false,
  lastPollAt,
}: ExtractionProgressPanelProps) {
  const [showErrors, setShowErrors] = useState(false)

  const avgSec = progress.averagePackSec ?? (progress.processedPacks > 0 ? progress.elapsedSec / progress.processedPacks : null)
  const remSec = progress.estimatedRemainingSec ?? (avgSec !== null ? avgSec * Math.max(0, progress.totalPacks - progress.processedPacks) : null)

  const showProgressView = !dryRunPlan && !isTerminalWorkflowStatus(progress.workflowStatus)

  // ── Render: progress ────────────────────────────────────────────────────
  if (showProgressView) {
    const processed = progress.processedPacks
    const total = Math.max(progress.totalPacks, 1)
    const running = !isTerminalWorkflowStatus(progress.workflowStatus)
      && progress.workflowStatus !== 'paused'
      && progress.workflowStatus !== 'pause_requested'
    const effectiveProcessed = processed + (progress.inFlightPacks || 0)
    const currentPack = effectiveProcessed > processed ? effectiveProcessed : (processed > 0 ? processed : 0)
    const progressPct = Math.min(
      progress.progressPercent,
      (effectiveProcessed / total) * 100,
      100,
    )

    return (
      <>
        <div className="modal-header">
          <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: '#1a1a2e' }}>
            {progress.workflowStatus === 'pause_requested'
              ? '⏸ 正在暂停...'
              : progress.workflowStatus === 'paused'
                ? '⏸ 已暂停'
                : progress.workflowStatus === 'queued' || progress.workflowStatus === 'pending'
                  ? '排队中...'
                  : running && progress.inFlightPacks > 0
                    ? `DeepSeek v4 pro 并发提取（${progress.concurrency || 1} 路）`
                    : running && processed === 0
                      ? '正在等待首批 DeepSeek 响应...'
                      : running && processed > 0
                        ? '提取中...'
                        : progress.workflowStatus === 'succeeded'
                          ? '提取完成'
                          : progress.workflowStatus === 'failed'
                            ? '提取失败'
                            : '提取中...'}
          </h3>
          <button className="btn-close" onClick={onClose}>x</button>
        </div>

        <div style={{ padding: '0 16px 8px', display: 'flex', flexDirection: 'column', gap: 10, flex: 1, overflowY: 'auto', minHeight: 0 }}>
          {/* ── Progress bar ──────────────────────────────────────────────── */}
          <div style={{ marginTop: 4 }}>
            <div className="pool-bar-progress-track" style={{ height: 8, borderRadius: 4, marginBottom: 4 }}>
              <div className="pool-bar-progress-fill" style={{ width: `${progressPct}%`, height: '100%', borderRadius: 4, transition: 'width 0.5s ease' }} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: '#444' }}>
              <span>
                {effectiveProcessed > processed
                  ? `正在处理第 ${currentPack}/${total} 包`
                  : processed > 0
                    ? `已完成 ${processed}/${total} 包`
                    : progress.inFlightPacks > 0
                      ? `${progress.inFlightPacks} 运行中 · ${total - (progress.inFlightPacks || 0)} 排队`
                      : '正在等待首批 DeepSeek 响应...'}
              </span>
              <span style={{ fontWeight: 600 }}>
                {Math.round(progressPct)}% · {elapsedStr(progress.elapsedSec)}
              </span>
            </div>
          </div>

          {/* ── Two-column layout: Pack stats (left) + Parse results (right) ─ */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {/* Left column: Pack progress overview */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#6b7280', marginBottom: -4 }}>包进度概览</div>
              {/* Row 1: 总包 / 已完成 / 成功 */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
                {([
                  { label: '总包', value: progress.totalPacks, color: '#1e40af', bg: '#eff6ff' },
                  { label: '已完成', value: progress.processedPacks, color: '#2563eb', bg: '#eff6ff' },
                  { label: '成功', value: progress.successPacks, color: '#16a34a', bg: '#f0fdf4' },
                ] as const).map((item, i) => (
                  <div key={i} style={{ background: item.bg, borderRadius: 8, padding: '12px 8px', textAlign: 'center', border: '1px solid #e0e7f0' }}>
                    <div style={{ fontSize: 22, fontWeight: 700, color: item.color, lineHeight: 1.2 }}>{item.value}</div>
                    <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>{item.label}</div>
                  </div>
                ))}
              </div>
              {/* Row 2: 失败 / 无发现 / 排队 */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
                {([
                  { label: '失败', value: progress.failedPacks, color: progress.failedPacks > 0 ? '#dc2626' : '#9ca3af', bg: progress.failedPacks > 0 ? '#fef2f2' : '#f9fafb' },
                  { label: '无发现', value: progress.noFindingsPacks || 0, color: '#d97706', bg: '#fffbeb' },
                  { label: '排队', value: Math.max(0, total - effectiveProcessed), color: '#6b7280', bg: '#f9fafb' },
                ] as const).map((item, i) => (
                  <div key={i} style={{ background: item.bg, borderRadius: 8, padding: '12px 8px', textAlign: 'center', border: '1px solid #e0e7f0' }}>
                    <div style={{ fontSize: 22, fontWeight: 700, color: item.color, lineHeight: 1.2 }}>{item.value}</div>
                    <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>{item.label}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Right column: Parse results overview */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#6b7280', marginBottom: -4 }}>解析结果概览</div>
              {/* Row 1: 筛出候选 / 解析连接 / 解析功能 */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
                {([
                  { label: '筛出候选', value: progress.screenedLikelyCount || 0, color: '#7c3aed', bg: '#f5f3ff' },
                  { label: '解析连接', value: progress.connectionsFound, color: '#2563eb', bg: '#eff6ff' },
                  { label: '解析功能', value: progress.functionCount || 0, color: '#0891b2', bg: '#ecfeff' },
                ] as const).map((item, i) => (
                  <div key={i} style={{ background: item.value > 0 ? item.bg : '#fafafa', borderRadius: 8, padding: '12px 4px', textAlign: 'center', border: `1px solid ${item.value > 0 ? '#d4d4f7' : '#e5e7eb'}` }}>
                    <div style={{ fontSize: 22, fontWeight: 700, color: item.value > 0 ? item.color : '#9ca3af', lineHeight: 1.2 }}>{item.value || '0'}</div>
                    <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>{item.label}</div>
                  </div>
                ))}
              </div>
              {/* Row 2: 新增 / 更新 / 跳过 */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
                {([
                  { label: '新增', value: progress.createdCount, color: '#16a34a', bg: '#f0fdf4' },
                  { label: '更新', value: progress.updatedCount || progress.mergedCount || 0, color: '#2563eb', bg: '#eff6ff' },
                  { label: '跳过', value: progress.skippedDupCount || 0, color: '#6b7280', bg: '#f9fafb' },
                ] as const).map((item, i) => (
                  <div key={i} style={{ background: item.value > 0 ? item.bg : '#fafafa', borderRadius: 8, padding: '12px 4px', textAlign: 'center', border: `1px solid ${item.value > 0 ? '#c7d2fe' : '#e5e7eb'}` }}>
                    <div style={{ fontSize: 22, fontWeight: 700, color: item.value > 0 ? item.color : '#9ca3af', lineHeight: 1.2 }}>{item.value || '0'}</div>
                    <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>{item.label}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* ── Usage + timing row ────────────────────────────────────────── */}
          <div style={{ fontSize: 13, color: '#444', display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'center', background: '#f9fafb', borderRadius: 8, padding: '10px 14px', border: '1px solid #e5e7eb' }}>
            <span style={{ fontWeight: 500 }}>🕐 {elapsedStr(progress.elapsedSec)}</span>
            {avgSec !== null && <span>⌀ {elapsedStr(avgSec)}/包</span>}
            {remSec !== null && remSec > 0 && <span>⏳ 剩余 {elapsedStr(remSec)}</span>}
            <span style={{ color: '#d1d5db' }}>|</span>
            {(progress.actualPromptTokens > 0 || progress.actualCompletionTokens > 0) ? <>
              <span>📥 {progress.actualPromptTokens.toLocaleString()}</span>
              <span>📤 {progress.actualCompletionTokens.toLocaleString()}</span>
              <span style={{ fontWeight: 600, color: '#2563eb' }}>💰 {estimateCost(progress.actualPromptTokens, progress.actualCompletionTokens)}</span>
            </> : (progress.estimatedInputTokens > 0 || progress.estimatedOutputTokens > 0) ? <>
              <span>📥 ~{progress.estimatedInputTokens.toLocaleString()}</span>
              <span>📤 ~{progress.estimatedOutputTokens.toLocaleString()}</span>
            </> : <span style={{ color: '#9ca3af', fontStyle: 'italic' }}>等待用量数据...</span>}
          </div>

          {/* ── Raw Progress Debug (dev-only, collapsed) ──────────────────── */}
          <details style={{ fontSize: 10, fontFamily: 'monospace', background: '#f0f4ff', borderRadius: 4, padding: '4px 8px', border: '1px solid #b0c4ff' }}>
            <summary style={{ cursor: 'pointer', color: '#555' }}>🔍 Raw Debug</summary>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1px 12px', marginTop: 4 }}>
              <span>wf: {progress.workflowRunId ? shortId(progress.workflowRunId) : '—'}</span>
              <span>status: {progress.workflowStatus}</span>
              <span>completed: {progress.processedPacks}/{progress.totalPacks}</span>
              <span>succeeded: {progress.successPacks}</span>
              <span>failed: {progress.failedPacks}</span>
              <span>inFlight: {progress.inFlightPacks}</span>
              <span>conn: {progress.connectionsFound}</span>
              <span>created: {progress.createdCount}</span>
              <span>prompt_tok: {progress.actualPromptTokens || '—'}</span>
              <span>completion_tok: {progress.actualCompletionTokens || '—'}</span>
              <span>last_poll: {lastPollAt || '—'}</span>
              <span>elapsed: {elapsedStr(progress.elapsedSec)}</span>
            </div>
          </details>

          {/* Recent errors — compact, collapsible, last 2 only */}
          {progress.errors.length > 0 && (
            <div style={{ fontSize: 11 }}>
              <p
                style={{ color: '#cf1322', cursor: 'pointer', userSelect: 'none', margin: 0 }}
                onClick={() => setShowErrors(!showErrors)}
              >
                {showErrors ? '▾' : '▸'} 异常 ({progress.errors.length})
              </p>
              {showErrors && (
                <div style={{ maxHeight: 100, overflow: 'auto', background: '#fff2f0', borderRadius: 6, padding: '8px 12px' }}>
                  {progress.errors.map((err, i) => (
                    <div key={i} style={{ fontSize: 12, color: '#cf1322', marginBottom: 4, fontFamily: 'monospace' }}>
                      {err.length > 120 ? `${err.slice(0, 120)}…` : err}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer — sticky, always clickable */}
        <div
          className="modal-footer"
          style={{
            flexShrink: 0,
            position: 'sticky',
            bottom: 0,
            zIndex: 20,
            pointerEvents: 'auto',
            background: '#fafafa',
            borderTop: '1px solid var(--border)',
          }}
        >
          {/* Pause / Resume */}
          {progress.workflowStatus === 'pause_requested' || progress.workflowStatus === 'paused' ? (
            <button
              className="llm-btn llm-btn-primary"
              type="button"
              disabled={isResuming}
              onClick={onResume}
            >
              {isResuming ? '恢复中...' : progress.workflowStatus === 'paused' ? '已暂停' : '继续提取'}
            </button>
          ) : (showPause && (progress.workflowStatus === 'running' || progress.workflowStatus === 'pending') && progress.workflowRunId) ? (
            <button
              className="llm-btn"
              type="button"
              disabled={isPausing}
              onClick={onPause}
            >
              {isPausing ? '暂停中...' : '暂停'}
            </button>
          ) : null}
          <button
            className="llm-btn llm-btn-danger"
            type="button"
            disabled={isCancelling || progress.workflowStatus === 'cleanup_done'}
            onClick={onCancel}
          >
            {isCancelling ? '取消中...' : '取消任务'}
          </button>
          <button className="llm-btn" onClick={onClose} type="button">后台运行</button>
        </div>
      </>
    )
  }

  // ── Render: result ────────────────────────────────────────────────────────
  const isSuccess = progress.workflowStatus === 'succeeded' || progress.workflowStatus === 'cleanup_done'
  const isPartial = progress.workflowStatus === 'partially_succeeded'
  const isFailed = progress.workflowStatus === 'failed' || progress.failedPacks > 0
  const isCancelled = progress.workflowStatus === 'cancelled'
  const isCleanupFailed = progress.workflowStatus === 'cleanup_failed'
  const hasCleanupError = isCleanupFailed && progress.errors.length > 0

  return (
    <>
      <div className="modal-header">
        <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: '#1a1a2e' }}>
          {dryRunPlan ? 'Dry Run 费用明细' : '提取结果'}
        </h3>
        <button className="btn-close" onClick={onClose}>x</button>
      </div>

      <div style={{ padding: '0 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* New: Detailed Dry Run plan with full cost breakdown */}
        {!!dryRunPlan && onStartExtraction && (
          <DryRunDetailPanel
            plan={dryRunPlan as any}
            originalRequestPayload={lastDryRunPayload}
            onStartExtraction={onStartExtraction}
            onClose={onClose}
            starting={starting}
          />
        )}

        {/* Legacy: Old dry_run result display (backward compat for non-plan_only dry runs) */}
        {!dryRunPlan && progress.workflowStatus === 'dry_run' && (
          <div className="modal-section" style={{ background: '#f0f7ff', borderRadius: 8, padding: '12px 16px', border: '1px solid #bae0ff' }}>
            <p className="modal-section-title" style={{ color: '#0958d9' }}>📋 Dry Run 预览结果</p>
            <div className="modal-section-row">
              <span className="label">计划包数</span>
              <span className="value" style={{ fontWeight: 600 }}>{progress.totalPacks} 包</span>
            </div>
            <div className="modal-section-row">
              <span className="label">预估输入 tokens</span>
              <span className="value">{progress.estimatedInputTokens.toLocaleString()}</span>
            </div>
            <div className="modal-section-row">
              <span className="label">预估输出 tokens</span>
              <span className="value">{progress.estimatedOutputTokens.toLocaleString()}</span>
            </div>
            <div className="modal-section-row">
              <span className="label">预估费用</span>
              <span className="value" style={{ fontWeight: 600, color: '#2563eb' }}>
                {estimateCost(progress.estimatedInputTokens, progress.estimatedOutputTokens)}
              </span>
            </div>
            {progress.connectionsFound > 0 && (
              <div style={{ marginTop: 8, padding: '8px 12px', background: '#f6ffed', borderRadius: 6, fontSize: 12, border: '1px solid #b7eb8f' }}>
                ✅ 样本包解析到 {progress.connectionsFound} 条连接（仅预览，未写入数据库）
              </div>
            )}
            {progress.errors.length > 0 && (
              <div style={{ marginTop: 8, padding: '8px 12px', background: '#fff2f0', borderRadius: 6, fontSize: 12, border: '1px solid #ffccc7' }}>
                ⚠ 样本包执行异常: {progress.errors[0]}
              </div>
            )}
          </div>
        )}

        {/* Status banner */}
        <div
          style={{
            padding: '12px 16px',
            borderRadius: 8,
            background: isCleanupFailed
              ? '#fff2f0'
              : isCancelled
                ? '#fffbe6'
                : isFailed
                  ? '#fff2f0'
                  : '#f6ffed',
            border: `1px solid ${
              isCleanupFailed ? '#ffa39e' : isCancelled ? '#ffe58f' : isFailed ? '#ffccc7' : '#b7eb8f'
            }`,
            textAlign: 'center',
          }}
        >
          <div style={{ fontSize: 16, fontWeight: 600, color: isCleanupFailed ? '#cf1322' : isCancelled ? '#d48806' : isFailed ? '#cf1322' : '#389e0d' }}>
            {isCleanupFailed
              ? '⚠ 取消失败（数据已清理）'
              : isCancelled
                ? '已取消'
                : isFailed
                  ? '部分失败'
                  : isPartial
                    ? '部分成功'
                    : '提取完成'}
          </div>
          <div style={{ fontSize: 13, color: '#666', marginTop: 4 }}>
            {isCleanupFailed
              ? '已停止提取但清理资源时出错'
              : isCancelled
                ? '用户取消了本次提取'
                : `${progress.processedPacks}/${progress.totalPacks} 包完成`}
          </div>
          {/* Show cleanup errors directly in banner */}
          {hasCleanupError && (
            <div style={{ marginTop: 8, padding: '6px 10px', background: '#fff1f0', borderRadius: 4, fontSize: 11, fontFamily: 'monospace', textAlign: 'left', maxHeight: 80, overflow: 'auto' }}>
              {progress.errors.slice(0, 3).map((e, i) => (
                <div key={i} style={{ color: '#cf1322' }}>{e.length > 150 ? e.slice(0, 150) + '…' : e}</div>
              ))}
            </div>
          )}
        </div>

        {/* Compact stats — single row of 5 cards */}
        <div className="modal-section" style={{ padding: 0 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr 1fr', gap: 6 }}>
            {(['总包', '已完成', '成功', '失败', '跳过'] as const).map((label, i) => {
              const vals = [progress.totalPacks, progress.processedPacks, progress.successPacks, progress.failedPacks, progress.skippedDupCount || 0]
              const colors = ['#2563eb', '#2563eb', '#389e0d', progress.failedPacks > 0 ? '#cf1322' : '#bbb', '#888']
              return (
                <div key={i} style={{ background: '#f8faff', borderRadius: 6, padding: '6px 4px', textAlign: 'center' }}>
                  <div style={{ fontSize: 16, fontWeight: 700, color: colors[i] }}>{vals[i]}</div>
                  <div style={{ fontSize: 10, color: '#888' }}>{label}</div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Compact row: connections + mirror stats */}
        <div className="modal-section" style={{ padding: 0 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 6 }}>
            <div style={{ background: '#f0f7ff', borderRadius: 4, padding: '4px 6px', textAlign: 'center' }}>
              <span style={{ fontSize: 14, fontWeight: 600, color: '#2563eb' }}>{progress.connectionsFound || '—'}</span>
              <span style={{ fontSize: 10, color: '#888', marginLeft: 4 }}>解析连接</span>
            </div>
            <div style={{ background: '#f6ffed', borderRadius: 4, padding: '4px 6px', textAlign: 'center' }}>
              <span style={{ fontSize: 14, fontWeight: 600, color: '#389e0d' }}>{progress.createdCount || '—'}</span>
              <span style={{ fontSize: 10, color: '#888', marginLeft: 4 }}>新建</span>
            </div>
            <div style={{ background: '#f8faff', borderRadius: 4, padding: '4px 6px', textAlign: 'center' }}>
              <span style={{ fontSize: 14, fontWeight: 600, color: '#2563eb' }}>{progress.updatedCount || progress.mergedCount || '—'}</span>
              <span style={{ fontSize: 10, color: '#888', marginLeft: 4 }}>更新</span>
            </div>
            <div style={{ background: '#fafafa', borderRadius: 4, padding: '4px 6px', textAlign: 'center' }}>
              <span style={{ fontSize: 14, fontWeight: 600, color: '#888' }}>{progress.skippedDupCount || '—'}</span>
              <span style={{ fontSize: 10, color: '#888', marginLeft: 4 }}>跳过</span>
            </div>
          </div>
        </div>

        {/* Compact row: tokens + time + cost */}
        <div className="modal-section" style={{ padding: 0 }}>
          <div style={{ fontSize: 12, color: '#555', display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: '#fafafa', borderRadius: 6, padding: '6px 10px' }}>
            <span>🕐 {elapsedStr(progress.elapsedSec)}</span>
            {(progress.actualPromptTokens > 0 || progress.actualCompletionTokens > 0) ? (
              <>
                <span>📥 {progress.actualPromptTokens.toLocaleString()} tok</span>
                <span>📤 {progress.actualCompletionTokens.toLocaleString()} tok</span>
                <span style={{ fontWeight: 600, color: '#2563eb' }}>💰 {estimateCost(progress.actualPromptTokens, progress.actualCompletionTokens)}</span>
              </>
            ) : (progress.estimatedInputTokens > 0 || progress.estimatedOutputTokens > 0) ? (
              <>
                <span>📥 ~{progress.estimatedInputTokens.toLocaleString()} tok</span>
                <span>📤 ~{progress.estimatedOutputTokens.toLocaleString()} tok</span>
              </>
            ) : null}
          </div>
        </div>

        {/* Error details — compact, collapsible, only last 2 */}
        {progress.errors.length > 0 && (
          <div className="modal-section" style={{ padding: 0 }}>
            <p
              className="modal-section-title"
              style={{ color: '#cf1322', cursor: 'pointer', userSelect: 'none', marginBottom: showErrors ? 6 : 0, fontSize: 12 }}
              onClick={() => setShowErrors(!showErrors)}
            >
              {showErrors ? '▾' : '▸'} 异常 ({progress.errors.length})
            </p>
            {showErrors && (
              <div style={{ maxHeight: 100, overflow: 'auto', background: '#fff2f0', borderRadius: 6, padding: '6px 10px' }}>
                {progress.errors.slice(0, 10).map((err, i) => (
                  <div key={i} style={{ fontSize: 12, color: '#cf1322', marginBottom: 6, fontFamily: 'monospace', lineHeight: 1.4 }}>
                    {err}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="modal-footer">
        {showRetry && onRetryFailed && progress.failedPacks > 0 && (
          <button className="llm-btn llm-btn-primary" onClick={onRetryFailed}>
            重试失败包 ({progress.failedPacks})
          </button>
        )}
        {onViewResults && (
          <button className="llm-btn llm-btn-primary" onClick={onViewResults}>
            查看 Mirror KG 连接
          </button>
        )}
        <button className="llm-btn llm-btn-primary" onClick={onClose}>
          关闭
        </button>
      </div>
    </>
  )
}
