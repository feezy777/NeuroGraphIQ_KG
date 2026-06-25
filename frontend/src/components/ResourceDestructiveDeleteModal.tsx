import { useEffect, useMemo, useState } from 'react'
import {
  destructiveDeleteResource,
  getResourceDeletePreview,
  type AtlasResource,
  type DependencyCounts,
  type ResourceDeletePreview,
} from '../api/endpoints'
import { ApiError } from '../api/client'
import { useI18n } from '../i18n-context'
import { ActionButton } from './ActionButton'
import { StatusBadge } from './StatusBadge'

interface ResourceDestructiveDeleteModalProps {
  open: boolean
  target: AtlasResource | null
  thenRecreate?: boolean
  loading?: boolean
  onClose: () => void
  onSuccess: (result: { resourceId: string; resourceCode: string; thenRecreate: boolean }) => void
  onError: (message: string) => void
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return String(error)
}

function formatPreviewCounts(counts: DependencyCounts): Array<{ key: string; value: number }> {
  return Object.entries(counts)
    .filter(([, v]) => (v ?? 0) > 0)
    .map(([key, value]) => ({ key, value: value ?? 0 }))
    .sort((a, b) => b.value - a.value)
}

export function ResourceDestructiveDeleteModal({
  open,
  target,
  thenRecreate = false,
  loading: externalLoading = false,
  onClose,
  onSuccess,
  onError,
}: ResourceDestructiveDeleteModalProps) {
  const { t } = useI18n()
  const [preview, setPreview] = useState<ResourceDeletePreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [operator, setOperator] = useState('')
  const [reason, setReason] = useState('')
  const [confirmationText, setConfirmationText] = useState('')
  const [deletePhysicalFiles, setDeletePhysicalFiles] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open || !target?.id) {
      setPreview(null)
      setPreviewError(null)
      setOperator('')
      setReason('')
      setConfirmationText('')
      setDeletePhysicalFiles(false)
      return
    }
    let cancelled = false
    setPreviewLoading(true)
    setPreviewError(null)
    getResourceDeletePreview(target.id)
      .then(data => {
        if (!cancelled) setPreview(data)
      })
      .catch(err => {
        if (!cancelled) {
          const msg = getErrorMessage(err)
          setPreviewError(
            err instanceof ApiError && err.status === 404
              ? t('resources.deletePreviewNotAvailable')
              : msg,
          )
        }
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false)
      })
    return () => { cancelled = true }
  }, [open, target?.id, t])

  const requiredConfirmation = preview?.required_confirmation ?? (target ? `DELETE ${target.resource_code}` : '')
  const confirmationOk = confirmationText.trim() === requiredConfirmation
  const formValid = confirmationOk && operator.trim().length > 0 && reason.trim().length > 0
  const busy = previewLoading || submitting || externalLoading

  const countEntries = useMemo(
    () => (preview ? formatPreviewCounts(preview.dependency_counts) : []),
    [preview],
  )

  async function handleSubmit() {
    if (!target?.id || !formValid) return
    setSubmitting(true)
    try {
      await destructiveDeleteResource(target.id, {
        confirmation_text: confirmationText.trim(),
        operator: operator.trim(),
        reason: reason.trim(),
        delete_physical_files: deletePhysicalFiles,
      })
      onSuccess({ resourceId: target.id, resourceCode: target.resource_code, thenRecreate })
    } catch (err) {
      onError(getErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (!open || !target) return null

  return (
    <div
      className="dialog-overlay"
      onClick={e => { if (e.target === e.currentTarget && !busy) onClose() }}
    >
      <div className="dialog-box resource-destructive-delete-modal">
        <div className="dialog-title resource-delete-warning">{t('resources.destructiveDeleteTitle')}</div>
        <p className="dialog-msg">{t('resources.destructiveDeleteDescription')}</p>
        <p className="dialog-msg resource-delete-warning">{t('resources.thisCannotBeUndone')}</p>

        <div className="resource-delete-preview">
          <div><strong>{t('resources.resourceCode')}:</strong> <code>{target.resource_code}</code></div>
          <div><strong>{t('resources.sourceAtlas')}:</strong> {target.source_atlas}</div>
          <div><strong>{t('resources.status')}:</strong> <StatusBadge status={target.status} /></div>
          <div className="resource-danger-zone">
            <div>{t('resources.canRecreateNow')}</div>
            <div>{t('resources.resourceCodeReleased')}</div>
          </div>
        </div>

        {previewLoading && <p className="text-muted">{t('resources.deletePreview')}…</p>}
        {previewError && <p className="resource-delete-warning">{previewError}</p>}

        {preview && (
          <div className="resource-delete-preview">
            <div className="resource-delete-warning">{t('resources.dependencyCounts')}</div>
            {countEntries.length === 0 ? (
              <p className="text-muted">—</p>
            ) : (
              <div className="resource-dependency-grid">
                {countEntries.map(({ key, value }) => (
                  <div key={key} className="resource-dependency-grid-item">
                    <span className="resource-dependency-grid-key">{key}</span>
                    <span className="resource-dependency-grid-value">{value}</span>
                  </div>
                ))}
              </div>
            )}
            {preview.warnings.map(w => (
              <p key={w} className="resource-delete-warning">{w}</p>
            ))}
          </div>
        )}

        <div className="resource-destructive-delete-form">
          <label className="form-label">
            {t('resources.operator')}
            <input
              className="form-input"
              value={operator}
              onChange={e => setOperator(e.target.value)}
              disabled={busy}
              autoComplete="off"
            />
          </label>
          <label className="form-label">
            {t('resources.deleteReason')}
            <textarea
              className="form-input"
              rows={2}
              value={reason}
              onChange={e => setReason(e.target.value)}
              disabled={busy}
            />
          </label>
          <label className="form-label">
            {t('resources.requiredConfirmation', { code: target.resource_code })}
            <input
              className="form-input resource-confirmation-input"
              value={confirmationText}
              onChange={e => setConfirmationText(e.target.value)}
              placeholder={requiredConfirmation}
              disabled={busy}
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          {!confirmationOk && confirmationText.length > 0 && (
            <p className="resource-delete-warning">{t('resources.confirmationMismatch')}</p>
          )}
          <label className="form-label resource-delete-physical-checkbox">
            <input
              type="checkbox"
              checked={deletePhysicalFiles}
              onChange={e => setDeletePhysicalFiles(e.target.checked)}
              disabled={busy}
            />
            {t('resources.deletePhysicalFiles')}
          </label>
          <p className="text-muted resource-delete-physical-hint">{t('resources.deletePhysicalFilesHint')}</p>
        </div>

        <div className="dialog-footer">
          <button className="btn" onClick={onClose} disabled={busy}>{t('common.cancel')}</button>
          <ActionButton
            label={thenRecreate ? t('resources.purgeThenRecreate') : t('resources.destructiveDelete')}
            onClick={() => void handleSubmit()}
            loading={submitting}
            disabled={!formValid || previewLoading}
            variant="danger"
          />
        </div>
      </div>
    </div>
  )
}
