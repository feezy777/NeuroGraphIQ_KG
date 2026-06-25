import { ConfirmDialog } from '../ConfirmDialog'
import { useI18n } from '../../i18n-context'

export function BatchCloneDialog({
  open,
  loading,
  batchCode,
  onConfirm,
  onCancel,
}: {
  open: boolean
  loading: boolean
  batchCode: string
  onConfirm: () => void
  onCancel: () => void
}) {
  const { t } = useI18n()
  return (
    <ConfirmDialog
      open={open}
      title={t('pipeline.cloneBatchTitle')}
      message={`${t('pipeline.cloneBatchMessage')}\n\n${batchCode}`}
      onConfirm={onConfirm}
      onCancel={onCancel}
      loading={loading}
    />
  )
}
