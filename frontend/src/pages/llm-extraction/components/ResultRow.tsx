import { useState } from 'react'
import { StatusBadge } from '../../../components/StatusBadge'
import type { ExtractionTypeConfig, ResultAction } from '../types/extractionConfig'
import { ResultCard } from './ResultCard'

interface Props {
  item: Record<string, unknown>
  config: ExtractionTypeConfig
  onAction: (action: ResultAction, item: Record<string, unknown>) => void
}

export function ResultRow({ item, config, onAction }: Props) {
  const [expanded, setExpanded] = useState(false)
  const Icon = config.icon

  const label = String(item[config.labelField] ?? '-')
  const sublabel = config.sublabelField ? String(item[config.sublabelField] ?? '') : ''
  const status = String(item[config.statusField] ?? 'unknown')
  const confidence = config.confidenceField ? Number(item[config.confidenceField]) : NaN

  const confColor = isNaN(confidence) ? undefined
    : confidence >= 0.8 ? '#389e0d'
    : confidence >= 0.5 ? '#d48806'
    : '#cf1322'

  return (
    <div>
      <div
        onClick={() => setExpanded(v => !v)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '10px 14px',
          cursor: 'pointer',
          fontSize: 14,
          borderBottom: '1px solid var(--border)',
          transition: 'background 0.1s',
          minHeight: 48,
        }}
        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = '#f5f5f5' }}
        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = '' }}
      >
        {/* Expand indicator */}
        <span style={{ width: 16, fontSize: 12, color: '#888', flexShrink: 0 }}>
          {expanded ? '▼' : '▶'}
        </span>

        {/* Icon */}
        <Icon size={18} style={{ color: 'var(--primary)', flexShrink: 0 }} />

        {/* Label + sublabel */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {label}
          </div>
          {sublabel && (
            <div style={{ fontSize: 12, color: '#888', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginTop: 1 }}>
              {sublabel}
            </div>
          )}
        </div>

        {/* Confidence badge */}
        {!isNaN(confidence) && (
          <span style={{
            fontSize: 13,
            fontWeight: 600,
            color: confColor,
            background: confColor ? `${confColor}15` : undefined,
            padding: '2px 8px',
            borderRadius: 4,
            flexShrink: 0,
          }}>
            {(confidence * 100).toFixed(0)}%
          </span>
        )}

        {/* Status badge */}
        <StatusBadge status={status} />
      </div>

      {/* Expanded card */}
      {expanded && <ResultCard item={item} config={config} onAction={onAction} />}
    </div>
  )
}
