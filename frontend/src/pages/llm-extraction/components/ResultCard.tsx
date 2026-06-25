import { StatusBadge } from '../../../components/StatusBadge'
import type { ExtractionTypeConfig, DetailField, ResultAction } from '../types/extractionConfig'

interface Props {
  item: Record<string, unknown>
  config: ExtractionTypeConfig
  onAction: (action: ResultAction, item: Record<string, unknown>) => void
}

function fieldValue(item: Record<string, unknown>, field: DetailField): unknown {
  return item[field.key] ?? field.fallback ?? null
}

function renderFieldValue(value: unknown, field: DetailField): React.ReactNode {
  if (value === null || value === undefined) {
    return <span style={{ color: '#bbb' }}>-</span>
  }

  switch (field.render) {
    case 'badge': {
      const s = String(value)
      return <StatusBadge status={s} />
    }
    case 'confidence': {
      const n = Number(value)
      if (isNaN(n)) return <span style={{ color: '#bbb' }}>-</span>
      const color = n >= 0.8 ? '#389e0d' : n >= 0.5 ? '#d48806' : '#cf1322'
      return <span style={{ color, fontWeight: 600 }}>{(n * 100).toFixed(0)}%</span>
    }
    case 'truncated': {
      const s = String(value)
      return s.length > 150 ? <span title={s}>{s.slice(0, 150)}…</span> : s
    }
    case 'json': {
      try {
        const obj = typeof value === 'string' ? JSON.parse(value) : value
        return <code style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>{JSON.stringify(obj, null, 1)}</code>
      } catch {
        return String(value)
      }
    }
    case 'date': {
      const s = String(value)
      return s.slice(0, 16).replace('T', ' ')
    }
    default:
      return String(value)
  }
}

export function ResultCard({ item, config, onAction }: Props) {
  return (
    <div
      style={{
        padding: '14px 18px',
        borderTop: '1px solid var(--border)',
        background: '#fafafa',
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
        gap: '8px 20px',
      }}
    >
      {config.detailFields.map(field => {
        const val = fieldValue(item, field)
        return (
          <div key={field.key} style={{ fontSize: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: '#888', flexShrink: 0, minWidth: 85 }}>{field.label}:</span>
            <span style={{ wordBreak: 'break-word' }}>{renderFieldValue(val, field)}</span>
          </div>
        )
      })}

      {/* Action buttons */}
      {config.actions.length > 0 && (
        <div style={{ gridColumn: '1 / -1', display: 'flex', gap: 8, marginTop: 6, paddingTop: 10, borderTop: '1px solid #eee' }}>
          {config.actions.map(action => (
            <button
              key={action.key}
              className="btn"
              style={{ fontSize: 13, padding: '4px 14px' }}
              onClick={() => onAction(action, item)}
            >
              {action.icon && <action.icon size={14} style={{ marginRight: 4 }} />}
              {action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
