import React from 'react'
import { ActionButton } from './ActionButton'
import { useI18n } from '../i18n-context'

interface ConfirmDialogProps {
  open: boolean
  title: string
  message?: string
  children?: React.ReactNode
  onConfirm: () => void
  onCancel: () => void
  confirmLabel?: string
  danger?: boolean
  loading?: boolean
}

export function ConfirmDialog({
  open,
  title,
  message,
  children,
  onConfirm,
  onCancel,
  confirmLabel,
  danger = false,
  loading = false,
}: ConfirmDialogProps) {
  const { t } = useI18n()

  if (!open) return null

  return (
    <div className="dialog-overlay" onClick={e => { if (e.target === e.currentTarget) onCancel() }}>
      <div className="dialog-box">
        <div className="dialog-title">{title}</div>
        {message && <p className="dialog-msg">{message}</p>}
        {children}
        <div className="dialog-footer">
          <button className="btn" onClick={onCancel} disabled={loading}>
            {t('common.cancel')}
          </button>
          <ActionButton
            label={confirmLabel ?? t('common.confirm')}
            onClick={onConfirm}
            loading={loading}
            variant={danger ? 'danger' : 'primary'}
          />
        </div>
      </div>
    </div>
  )
}
