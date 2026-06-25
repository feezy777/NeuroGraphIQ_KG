import type { ReactNode } from 'react'
import { type Column } from '../../components/DataTable'
import { StatusBadge } from '../../components/StatusBadge'
import { CopyButton } from '../../components/CopyButton'
import {
  type FormalFieldMapping,
  getFieldValue,
  computeMissingFields,
  isValueFromOverlay,
} from './formalFieldMappings'
import { MissingFieldsBadge } from './MissingFieldsBadge'

type FormalRow = Record<string, unknown> & { id: string }

function formatCellValue(value: unknown, renderType?: string): ReactNode {
  if (value == null || value === '') return '—'
  if (renderType === 'status') return <StatusBadge status={String(value)} />
  if (renderType === 'confidence') {
    const n = typeof value === 'number' ? value : parseFloat(String(value))
    return Number.isFinite(n) ? n.toFixed(2) : String(value)
  }
  if (renderType === 'date') return String(value).slice(0, 19).replace('T', ' ')
  if (renderType === 'json') {
    const text = typeof value === 'string' ? value : JSON.stringify(value)
    return <code className="data-center-json-cell">{text.slice(0, 80)}{text.length > 80 ? '…' : ''}</code>
  }
  if (renderType === 'id') {
    const s = String(value)
    return (
      <span className="data-center-id-cell">
        <code>{s.length > 14 ? `${s.slice(0, 12)}…` : s}</code>
        <CopyButton value={s} />
      </span>
    )
  }
  const s = String(value)
  if (s.length > 120) return `${s.slice(0, 117)}…`
  return s
}

export interface FormalColumnBuilderOptions {
  mapping: FormalFieldMapping
  onCompleteRow: (row: FormalRow) => void
  onOpenDetail: (row: FormalRow) => void
  t: (key: string) => string
}

export function buildFormalColumns({
  mapping,
  onCompleteRow,
  onOpenDetail,
  t,
}: FormalColumnBuilderOptions): Column<FormalRow>[] {
  const dataCols: Column<FormalRow>[] = mapping.columns.map(column => ({
    key: column.key,
    header: column.label,
    width: column.width,
    render: row => {
      const value = getFieldValue(row, column, mapping)
      const fromOverlay = isValueFromOverlay(row, column)
      return (
        <span className="data-center-formal-cell">
          {formatCellValue(value, column.renderType)}
          {fromOverlay && (
            <span className="data-center-overlay-badge data-center-overlay-badge-inline">overlay</span>
          )}
        </span>
      )
    },
  }))

  return [
    {
      key: '_missing',
      header: t('dataCenter.missingFields'),
      width: 100,
      render: row => <MissingFieldsBadge missingFields={computeMissingFields(row, mapping)} />,
    },
    ...dataCols,
    {
      key: '_actions',
      header: '',
      width: 160,
      render: row => (
        <div className="data-center-formal-row-actions" onClick={e => e.stopPropagation()}>
          <button type="button" className="btn btn-sm" onClick={() => onCompleteRow(row)}>
            {t('dataCenter.fieldCompletionRow')}
          </button>
          <button type="button" className="btn btn-sm" onClick={() => onOpenDetail(row)}>
            {t('dataCenter.openDetail')}
          </button>
        </div>
      ),
    },
  ]
}
