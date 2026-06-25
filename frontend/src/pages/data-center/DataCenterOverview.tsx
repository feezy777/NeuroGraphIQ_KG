import { useMemo } from 'react'
import { useI18n } from '../../i18n-context'
import type { DataCenterCounts, DataCenterTabId } from './dataCenterTypes'

interface Props {
  counts: DataCenterCounts
  loading: boolean
  onNavigate: (tab: DataCenterTabId) => void
  onRefresh: () => void
}

interface PipelineStage {
  key: DataCenterTabId
  label: string
  total: number
  detail: string
  color: 'blue' | 'green' | 'purple' | 'orange'
  status: 'empty' | 'has_data' | 'needs_review'
}

export function DataCenterOverview({ counts, loading, onNavigate, onRefresh }: Props) {
  const { t } = useI18n()

  const stages: PipelineStage[] = useMemo(() => {
    const rawTotal = counts.rawAal3Count + counts.rawMacro96Count
    const candReview = counts.candidatePending > 0 ? ` · ${counts.candidatePending} pending` : ''
    const mirrorReview = counts.mirrorConnections > 0 ? ' · 待审核' : ''
    return [
      {
        key: 'raw',
        label: 'Raw 数据',
        total: rawTotal,
        detail: `AAL3 ${counts.rawAal3Count} · Macro96 ${counts.rawMacro96Count}`,
        color: 'blue',
        status: rawTotal > 0 ? 'has_data' : 'empty',
      },
      {
        key: 'candidates',
        label: '候选脑区',
        total: counts.candidateCount,
        detail: `rule_passed ${counts.candidateRulePassed}${candReview}`,
        color: 'green',
        status: counts.candidateCount > 0 ? 'has_data' : 'empty',
      },
      {
        key: 'mirror',
        label: 'Mirror KG',
        total: counts.mirrorConnections + counts.mirrorFunctions + counts.mirrorCircuits + counts.mirrorTriples,
        detail: `conn ${counts.mirrorConnections} · func ${counts.mirrorFunctions} · circuit ${counts.mirrorCircuits} · triple ${counts.mirrorTriples}`,
        color: 'purple',
        status: counts.mirrorConnections > 0 ? 'needs_review' : 'empty',
      },
      {
        key: 'final',
        label: 'Final KG',
        total: counts.finalCircuits + counts.finalProjections + counts.finalSteps + counts.finalFunctions + counts.finalTriples,
        detail: `circuit ${counts.finalCircuits} · proj ${counts.finalProjections} · step ${counts.finalSteps} · func ${counts.finalFunctions} · triple ${counts.finalTriples}`,
        color: 'orange',
        status: (counts.finalCircuits + counts.finalProjections) > 0 ? 'has_data' : 'empty',
      },
    ] as PipelineStage[]
  }, [counts])

  const attentionItems = useMemo(() => {
    const items: Array<{ type: 'error' | 'warning' | 'info'; message: string }> = []
    if (counts.candidatePending > 0) items.push({ type: 'warning', message: `${counts.candidatePending} 条候选脑区待人工审核` })
    if (counts.mirrorConnections > 0) items.push({ type: 'info', message: `${counts.mirrorConnections} 条连接已提取，可进入审核流程` })
    if (counts.rawAal3Count === 0 && counts.rawMacro96Count === 0) items.push({ type: 'warning', message: '暂无 Raw 数据，请先导入并解析批次' })
    if (counts.hasApiError) items.push({ type: 'error', message: counts.warnings.join(' · ') })
    return items
  }, [counts])

  const quickEntries: Array<{ tab: DataCenterTabId; label: string; icon: string; desc: string }> = [
    { tab: 'raw', label: 'Raw 数据', icon: '📄', desc: '浏览原始解析结果' },
    { tab: 'candidates', label: '候选脑区', icon: '🏗️', desc: '候选数据管理与查看' },
    { tab: 'mirror', label: 'Mirror KG', icon: '🔷', desc: 'LLM 提取结果编辑与补全' },
    { tab: 'macro', label: 'Macro Clinical', icon: '🔗', desc: '回路步骤与连接功能' },
    { tab: 'final', label: 'Final KG', icon: '🏁', desc: '正式知识库浏览' },
    { tab: 'exports', label: '导出', icon: '📦', desc: '知识图谱导出' },
  ]

  return (
    <div className="dc-overview">
      {/* Pipeline Flow */}
      <div className="dc-overview-card">
        <div className="dc-overview-card-header">
          <h3>数据流转状态</h3>
          <button type="button" className="btn btn-sm" onClick={onRefresh} disabled={loading}>刷新</button>
        </div>
        <div className="dc-pipeline">
          {stages.map((s, i) => (
            <div key={s.key} className="dc-pipeline-stage">
              <button
                className={`dc-pipeline-card dc-pipeline-${s.color} ${s.status === 'empty' ? 'dc-pipeline-empty' : ''}`}
                onClick={() => onNavigate(s.key)}
              >
                <span className="dc-pipeline-total">{s.total}</span>
                <span className="dc-pipeline-label">{s.label}</span>
                <span className="dc-pipeline-detail">{s.detail}</span>
              </button>
              {i < stages.length - 1 && <div className="dc-pipeline-arrow">→</div>}
            </div>
          ))}
        </div>
      </div>

      {/* Attention Items */}
      {attentionItems.length > 0 && (
        <div className="dc-overview-card">
          <h3 className="dc-overview-card-header">需要关注</h3>
          <div className="dc-attention-list">
            {attentionItems.map((item, i) => (
              <div key={i} className={`dc-attention-item dc-attention-${item.type}`}>
                <span className="dc-attention-icon">
                  {item.type === 'error' ? '🔴' : item.type === 'warning' ? '🟡' : '🔵'}
                </span>
                <span className="dc-attention-text">{item.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Quick Entry */}
      <div className="dc-overview-card">
        <h3 className="dc-overview-card-header">快速入口</h3>
        <div className="dc-quick-grid">
          {quickEntries.map(e => (
            <button key={e.tab} className="dc-quick-card" onClick={() => onNavigate(e.tab)}>
              <span className="dc-quick-icon">{e.icon}</span>
              <div>
                <div className="dc-quick-label">{e.label}</div>
                <div className="dc-quick-desc">{e.desc}</div>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
