import { useState, useEffect } from 'react'
import { useI18n } from '../../../i18n-context'

interface PackProgress {
  index: number
  pair_count: number
  status: 'pending' | 'running' | 'succeeded' | 'parse_error' | 'transport_error' | 'cancelled'
  parsed_projection_count?: number
  parsed_no_connection_count?: number
  error?: string
}

interface ProgressPanelProps {
  visible: boolean
  totalPacks: number
  completedPacks: number
  packProgress: PackProgress[]
  status: 'idle' | 'running' | 'cancelling' | 'paused' | 'completed' | 'failed'
  onCancel: () => void
  onPause?: () => void
  onClose: () => void
  summary?: {
    connection_count?: number
    function_count?: number
    circuit_count?: number
    triple_count?: number
    skipped_duplicate_count?: number
    warnings?: string[]
  }
}

export function ProgressPanel({
  visible,
  totalPacks,
  completedPacks,
  packProgress,
  status,
  onCancel,
  onPause,
  onClose,
  summary,
}: ProgressPanelProps) {
  const { t } = useI18n()
  const [minimized, setMinimized] = useState(false)

  useEffect(() => {
    if (status === 'running') setMinimized(false)
  }, [status])

  if (!visible) return null
  if (minimized) {
    const pct = totalPacks > 0 ? Math.round((completedPacks / totalPacks) * 100) : 0
    return (
      <div className="pp-minimized" onClick={() => setMinimized(false)}>
        <div className="pp-mini-bar"><div className="pp-mini-fill" style={{ width: `${pct}%` }} /></div>
        <span className="pp-mini-text">{pct}% · {completedPacks}/{totalPacks}</span>
      </div>
    )
  }

  const pct = totalPacks > 0 ? Math.round((completedPacks / totalPacks) * 100) : 0
  const isRunning = status === 'running' || status === 'cancelling'
  const recentPacks = packProgress.slice(-8)

  return (
    <div className={`pp-panel ${status === 'failed' ? 'pp-failed' : ''} ${status === 'completed' ? 'pp-completed' : ''}`}>
      {/* Header */}
      <div className="pp-header">
        <span className="pp-title">
          {status === 'running' ? '提取进行中' : status === 'paused' ? '已暂停' : status === 'cancelling' ? '正在取消...' : status === 'completed' ? '提取完成' : '提取失败'}
        </span>
        <div className="pp-header-actions">
          {status === 'running' && onPause && (
            <button className="pp-btn" onClick={onPause}>⏸ 暂停</button>
          )}
          {isRunning && (
            <button className="pp-btn pp-btn-cancel" onClick={onCancel}>⏹ 取消</button>
          )}
          {!isRunning && (
            <button className="pp-btn pp-btn-close" onClick={onClose}>✕</button>
          )}
          <button className="pp-btn pp-btn-min" onClick={() => setMinimized(true)}>—</button>
        </div>
      </div>

      {/* Progress bar */}
      <div className="pp-bar-track">
        <div className="pp-bar-fill" style={{ width: `${pct}%` }} />
        <span className="pp-bar-label">{pct}% ({completedPacks}/{totalPacks} 包)</span>
      </div>

      {/* Errors / Warnings */}
      {summary?.warnings && summary.warnings.length > 0 && (
        <div className="pp-warnings">
          {summary.warnings.slice(0, 3).map((w, i) => (
            <div key={i} className="pp-warning">{w}</div>
          ))}
          {summary.warnings.length > 3 && <div className="pp-warning">…还有 {summary.warnings.length - 3} 条警告</div>}
        </div>
      )}

      {/* Pack list */}
      <div className="pp-pack-list">
        {recentPacks.map(p => (
          <div key={p.index} className={`pp-pack pp-pack-${p.status}`}>
            <span className="pp-pack-index">#{p.index + 1}</span>
            <span className="pp-pack-status">
              {p.status === 'running' && '⏳ 运行中'}
              {p.status === 'succeeded' && `✅ ${p.parsed_projection_count || 0}连接 / ${p.parsed_no_connection_count || 0}无连接`}
              {p.status === 'parse_error' && `❌ 解析失败${p.error ? ': ' + p.error.substring(0, 40) : ''}`}
              {p.status === 'transport_error' && '⚠️ 网络错误'}
              {p.status === 'cancelled' && '⏹ 已取消'}
              {p.status === 'pending' && '⏳ 等待中'}
            </span>
          </div>
        ))}
      </div>

      {/* Summary */}
      {status === 'completed' && summary && (
        <div className="pp-summary">
          <div className="pp-summary-row">
            {summary.connection_count != null && <span>连接: {summary.connection_count}</span>}
            {summary.function_count != null && <span>功能: {summary.function_count}</span>}
            {summary.circuit_count != null && <span>回路: {summary.circuit_count}</span>}
            {summary.triple_count != null && <span>三元组: {summary.triple_count}</span>}
            {summary.skipped_duplicate_count != null && <span>跳过重复: {summary.skipped_duplicate_count}</span>}
          </div>
        </div>
      )}
    </div>
  )
}
