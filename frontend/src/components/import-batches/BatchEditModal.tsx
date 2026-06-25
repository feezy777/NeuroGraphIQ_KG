import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { ActionButton } from '../ActionButton'
import { StatusBadge } from '../StatusBadge'
import {
  fetchImportBatchOptions,
  getImportBatch,
  updateImportBatch,
  updateImportBatchFiles,
  type BatchFileBinding,
  type ImportBatchDetail,
} from '../../api/endpoints'
import { ApiError } from '../../api/client'
import { useData } from '../../hooks/useData'
import { useI18n } from '../../i18n-context'
import {
  canEditCoreFields,
  canEditDescription,
  canEditFiles,
} from '../../utils/batchEditPermissions'
import { formatApiErrorMessage } from '../../utils/apiErrorMessage'
import { BatchFileBindingsEditor } from './BatchFileBindingsEditor'
import { formatFileRoleInBatchLabel, type FileBindingRow } from './batchModalUtils'

export function BatchEditModal({
  batchId,
  open,
  onClose,
  onSaved,
}: {
  batchId: string
  open: boolean
  onClose: () => void
  onSaved: (detail: ImportBatchDetail) => void
}) {
  const { t } = useI18n()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editForm, setEditForm] = useState({
    batch_type: 'atlas_import',
    parser_key: '',
    description: '',
    remark: '',
  })
  const [editBindings, setEditBindings] = useState<FileBindingRow[]>([])

  const { data: detail, loading } = useData(
    () => (open ? getImportBatch(batchId) : Promise.resolve(null as ImportBatchDetail | null)),
    [batchId, open],
  )
  const { data: options } = useData(() => fetchImportBatchOptions(), [])

  const batchTypes = options?.batch_type ?? ['atlas_import']
  const fileRoles = options?.file_role_in_batch ?? ['label_dictionary', 'macro_region_pool_source', 'unknown']

  useEffect(() => {
    if (!detail) return
    setEditForm({
      batch_type: detail.batch_type,
      parser_key: detail.parser_key ?? '',
      description: detail.description ?? '',
      remark: detail.remark ?? '',
    })
    setEditBindings(
      detail.files.map(f => ({
        file_id: f.file_id,
        file_role_in_batch: f.file_role_in_batch,
        sort_order: f.sort_order,
      })),
    )
    setError(null)
  }, [detail?.id, detail?.updated_at, detail])

  if (!open) return null

  async function handleSave() {
    if (!detail) return
    setSaving(true)
    setError(null)
    try {
      if (canEditDescription(detail.status)) {
        const body: Record<string, unknown> = {
          description: editForm.description || null,
          remark: editForm.remark || null,
        }
        if (canEditCoreFields(detail.status)) {
          body.batch_type = editForm.batch_type
          body.parser_key = editForm.parser_key || null
        }
        await updateImportBatch(batchId, body)
      }
      if (canEditFiles(detail.status)) {
        const files: BatchFileBinding[] = editBindings
          .filter(b => b.file_id.trim())
          .map((b, i) => ({
            file_id: b.file_id.trim(),
            file_role_in_batch: b.file_role_in_batch,
            sort_order: b.sort_order ?? i,
          }))
        await updateImportBatchFiles(batchId, files)
      }
      const refreshed = await getImportBatch(batchId)
      onSaved(refreshed)
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : formatApiErrorMessage(e))
    } finally {
      setSaving(false)
    }
  }

  const editable = detail ? canEditDescription(detail.status) : false

  return (
    <div className="batch-create-modal-backdrop" role="dialog" aria-modal="true">
      <div className="batch-edit-modal">
        <div className="batch-create-modal-header">
          <div className="batch-create-modal-header-text">
            <h2 className="batch-create-modal-title">{t('pipeline.editBatch')}</h2>
            <p className="batch-create-modal-subtitle">{t('pipeline.batchEditableOnlyInCreatedOrQueued')}</p>
          </div>
          <button type="button" className="batch-create-modal-close" onClick={onClose} disabled={saving} aria-label={t('common.cancel')}>
            <X size={18} />
          </button>
        </div>

        <div className="batch-edit-modal-body">
          {loading && <div>{t('common.loading')}</div>}
          {!loading && detail && (
            <>
              <div className="batch-edit-grid">
                <div className="batch-readonly-field">
                  <span className="form-label">{t('batches.batchCode')}</span>
                  <span>{detail.batch_code}</span>
                </div>
                <div className="batch-readonly-field">
                  <span className="form-label">{t('batches.status')}</span>
                  <StatusBadge status={detail.status} />
                </div>
                <div className="batch-readonly-field">
                  <span className="form-label">{t('batches.resourceId')}</span>
                  <code>{detail.resource_id.slice(0, 12)}…</code>
                </div>
              </div>

              {!editable && (
                <div className="batch-danger-note">{t('pipeline.batchEditNotAllowedAfterRunning')}</div>
              )}

              {canEditCoreFields(detail.status) && (
                <div className="form-row">
                  <div className="form-field">
                    <label className="form-label">{t('batches.batchType')}</label>
                    <select className="form-select" value={editForm.batch_type}
                      onChange={e => setEditForm(f => ({ ...f, batch_type: e.target.value }))}>
                      {batchTypes.map(v => <option key={v} value={v}>{v}</option>)}
                    </select>
                  </div>
                  <div className="form-field">
                    <label className="form-label">{t('batches.parserKey')}</label>
                    <input className="form-input" value={editForm.parser_key}
                      onChange={e => setEditForm(f => ({ ...f, parser_key: e.target.value }))} />
                  </div>
                </div>
              )}

              {canEditDescription(detail.status) && (
                <div className="form-row">
                  <div className="form-field">
                    <label className="form-label">{t('common.description')}</label>
                    <input className="form-input" value={editForm.description}
                      onChange={e => setEditForm(f => ({ ...f, description: e.target.value }))} />
                  </div>
                  <div className="form-field">
                    <label className="form-label">{t('common.remark')}</label>
                    <input className="form-input" value={editForm.remark}
                      onChange={e => setEditForm(f => ({ ...f, remark: e.target.value }))} />
                  </div>
                </div>
              )}

              {canEditFiles(detail.status) && (
                <BatchFileBindingsEditor
                  resourceId={detail.resource_id}
                  parserKey={editForm.parser_key || detail.parser_key || ''}
                  bindings={editBindings}
                  fileRoles={fileRoles}
                  onChange={setEditBindings}
                  formatRoleLabel={role => formatFileRoleInBatchLabel(role, t)}
                />
              )}

              {error && <div className="batch-create-warning">{error}</div>}
            </>
          )}
        </div>

        <div className="batch-create-modal-footer">
          <ActionButton label={t('common.cancel')} variant="default" onClick={onClose} disabled={saving} />
          <ActionButton
            label={t('common.save')}
            variant="primary"
            onClick={handleSave}
            loading={saving}
            disabled={!editable || saving}
          />
        </div>
      </div>
    </div>
  )
}
