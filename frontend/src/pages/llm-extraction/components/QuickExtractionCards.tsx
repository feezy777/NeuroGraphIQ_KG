import { useState } from 'react'

interface QuickCard {
  key: string
  icon: string
  label: string
  desc: string
  className: string
  disabled: boolean
  onClick: () => void
}

interface Props {
  selectedCount: number
  connectionCount?: number
  connectionMode?: boolean
  onExtractFunction: () => void
  onExtractConnection: () => void
  onExtractCircuit: () => void
}

export function QuickExtractionCards({
  selectedCount,
  connectionCount = 0,
  connectionMode = false,
  onExtractFunction,
  onExtractConnection,
  onExtractCircuit,
}: Props) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})

  const toggle = (key: string) => {
    setCollapsed(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const cards: QuickCard[] = [
    {
      key: 'fn',
      icon: '🏷️',
      label: '脑区功能提取',
      desc: connectionMode
        ? '请切换到「脑区」模式'
        : selectedCount >= 1
          ? `为选中的 ${selectedCount} 个脑区提取功能`
          : '选择脑区后提取功能',
      className: 'llm-quick-card llm-quick-card-fn',
      disabled: connectionMode || selectedCount < 1,
      onClick: onExtractFunction,
    },
    {
      key: 'conn',
      icon: '🔗',
      label: '连接提取',
      desc: connectionMode
        ? selectedCount >= 1
          ? `${selectedCount} 条连接的字段补全与功能提取`
          : '选择连接后进入连接池'
        : selectedCount >= 2
          ? `${selectedCount} 个脑区 all_pairs 连接提取`
          : '选择 ≥2 个脑区后提取连接',
      className: 'llm-quick-card llm-quick-card-conn',
      disabled: selectedCount < (connectionMode ? 1 : 2),
      onClick: onExtractConnection,
    },
    {
      key: 'circuit',
      icon: '⭕',
      label: '回路+步骤+功能',
      desc: connectionMode
        ? connectionCount >= 2
          ? `基于 ${connectionCount} 条连接提取回路`
          : '勾选连接后提取回路（需 ≥2 条）'
        : selectedCount >= 2
          ? '从选中脑区提取回路、步骤和功能'
          : '选择 ≥2 个脑区后提取回路',
      className: 'llm-quick-card llm-quick-card-circuit',
      disabled: !connectionMode && selectedCount < 2,
      onClick: onExtractCircuit,
    },
  ]

  return (
    <div className="llm-quick-extract-row">
      {cards.map(card => {
        const isCollapsed = collapsed[card.key] ?? false
        return (
          <div
            key={card.key}
            className={`${card.className}${card.disabled ? ' llm-quick-card-disabled' : ''}`}
          >
            <div
              className="llm-quick-card-header"
              onClick={() => toggle(card.key)}
            >
              <span className="llm-quick-icon">{card.icon}</span>
              <span className="llm-quick-label">{card.label}</span>
              <span className="llm-quick-count">
                {card.disabled
                  ? `需 ≥${card.key === 'fn' ? 1 : 2}`
                  : connectionMode && card.key === 'circuit'
                    ? `${connectionCount}`
                    : `${selectedCount}`}
              </span>
              <span className="llm-quick-toggle">{isCollapsed ? '▷' : '▽'}</span>
            </div>
            <div className={`llm-quick-card-body${isCollapsed ? ' llm-quick-card-body-collapsed' : ''}`}>
              <p className="llm-quick-desc">{card.desc}</p>
              <button
                className="llm-quick-action-btn"
                disabled={card.disabled}
                onClick={card.onClick}
              >
                {card.disabled ? '暂不可用' : '开始提取'}
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}
