import { useState, useCallback } from 'react'
import { CopyButton } from '../../components/CopyButton'
import { StatusBadge } from '../../components/StatusBadge'
import { useI18n } from '../../i18n-context'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { MissingFieldsBadge } from './MissingFieldsBadge'
import {
  type FormalFieldMapping,
  computeMissingFields,
} from './formalFieldMappings'

interface Props {
  open: boolean
  row: Record<string, unknown> | null
  mapping: FormalFieldMapping | null
  onClose: () => void
  onFieldCompletion: () => void
  onSave?: (rowId: string, field: string, value: unknown) => Promise<void>
  onDelete?: (rowId: string) => Promise<void>
  onRefresh?: () => void
}

function renderFieldValue(value: unknown): string {
  if (value == null || value === '') return ''
  if (typeof value === 'object') {
    try { return JSON.stringify(value, null, 2) } catch { return String(value) }
  }
  return String(value)
}

function shortId(value: unknown): string {
  const text = String(value ?? '')
  if (text.length <= 12) return text
  return `${text.slice(0, 8)}…`
}

export function FormalObjectDetailDrawer({
  open,
  row,
  mapping,
  onClose,
  onFieldCompletion,
  onSave,
  onDelete,
  onRefresh,
}: Props) {
  const { t } = useI18n()
  const [editingField, setEditingField] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)

  const missingFields = row && mapping ? computeMissingFields(row, mapping) : []

  const handleStartEdit = useCallback((key: string, value: unknown) => {
    setEditingField(key)
    setEditValue(renderFieldValue(value))
  }, [])

  const handleSave = useCallback(async (rowId: string, field: string) => {
    if (!onSave) return
    setSaving(true)
    try {
      await onSave(rowId, field, editValue)
      setEditingField(null)
      onRefresh?.()
    } finally {
      setSaving(false)
    }
  }, [editValue, onSave, onRefresh])

  const handleDelete = useCallback(async (rowId: string) => {
    if (!onDelete) return
    setSaving(true)
    try {
      await onDelete(rowId)
      setDeleteConfirm(null)
      onClose()
      onRefresh?.()
    } finally {
      setSaving(false)
    }
  }, [onDelete, onClose, onRefresh])

  if (!open || !row || !mapping) return null

  const emptyFieldSet = new Set(missingFields)

  return (
    <>
      <div className="drawer-overlay" onClick={onClose}>
        <div className="drawer" onClick={e => e.stopPropagation()}>
          <div className="drawer-header">
            <h3>{mapping.label} <span className="drawer-subtitle">Detail</span></h3>
            <div className="drawer-header-actions">
              {onDelete && (
                <button className="btn btn-sm btn-danger" onClick={() => setDeleteConfirm(row.id as string)} title="删除">
                  🗑 Delete
                </button>
              )}
              {onFieldCompletion && (
                <button className="btn btn-sm btn-primary" onClick={onFieldCompletion} title="LLM field completion">
                  ✨ AI Complete
                </button>
              )}
              <MissingFieldsBadge missingFields={missingFields} />
              <button className="btn btn-sm" onClick={onClose}>✕</button>
            </div>
          </div>
          <div className="drawer-body">
            {mapping.columns.map(col => {
              const raw = row[col.key]
              const val = renderFieldValue(raw)
              const isEmpty = raw == null || raw === '' || raw === undefined
              const isMissing = (emptyFieldSet.has(col.key) || (isEmpty && col.required))
              const isEditing = editingField === col.key
              return (
                <div key={col.key} className={`detail-field${isMissing ? ' detail-field-missing' : ''}`}>
                  <label className="detail-field-label">
                    <span>{col.label}</span>
                    {col.enrichable && <span className="detail-enrichable" title="可用 AI 补全">AI</span>}
                    {col.required && <span className="detail-required" title="必填">*</span>}
                  </label>
                  <div className="detail-field-value">
                    {isEditing ? (
                      <div className="detail-field-edit-row">
                        <input
                          className="form-input"
                          value={editValue}
                          onChange={e => setEditValue(e.target.value)}
                          autoFocus
                          onKeyDown={e => { if (e.key === 'Enter') handleSave(row.id as string, col.key); if (e.key === 'Escape') setEditingField(null) }}
                        />
                        <button className="btn btn-sm btn-primary" disabled={saving} onClick={() => handleSave(row.id as string, col.key)}>保存</button>
                        <button className="btn btn-sm" onClick={() => setEditingField(null)}>取消</button>
                      </div>
                    ) : (
                      <div className="detail-field-display">
                        {isMissing ? (
                          <span className="detail-empty-value" onClick={onSave ? () => handleStartEdit(col.key, '') : undefined}>
                            {onSave ? '— 点击编辑' : '—'}
                          </span>
                        ) : col.renderType === 'status' ? (
                          <StatusBadge status={String(raw)} />
                        ) : col.renderType === 'id' ? (
                          <span className="detail-id"><code>{shortId(raw)}</code><CopyButton value={String(raw)} /></span>
                        ) : col.renderType === 'json' ? (
                          <pre className="detail-json">{val}</pre>
                        ) : (
                          <span className="detail-text">{val || '—'}</span>
                        )}
                        {onSave && !isMissing && !col.derived && (
                          <button className="btn-text" onClick={() => handleStartEdit(col.key, raw ?? '')} title="编辑">
                            ✎
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {deleteConfirm && (
        <ConfirmDialog
          open={true}
          title={`删除 ${mapping.label}`}
          message={`确定删除此 ${mapping.label}？此操作不可撤销。`}
          onConfirm={() => handleDelete(deleteConfirm)}
          onCancel={() => setDeleteConfirm(null)}
          danger
        />
      )}
    </>
  )
}
