import { AlertCircle, DatabaseZap, Loader2 } from 'lucide-react'
import { useI18n } from '../i18n-context'

export function LoadingState({ text }: { text?: string }) {
  const { t } = useI18n()
  return (
    <div className="state-box">
      <Loader2 size={28} className="spin" />
      <p>{text ?? t('common.loading')}</p>
    </div>
  )
}

export function ErrorState({ error }: { error: string }) {
  return (
    <div className="state-box state-err">
      <AlertCircle size={28} style={{ opacity: 1 }} />
      <p style={{ maxWidth: 480, textAlign: 'center', wordBreak: 'break-word' }}>{error}</p>
    </div>
  )
}

export function EmptyState({ text }: { text?: string }) {
  const { t } = useI18n()
  return (
    <div className="state-box">
      <DatabaseZap size={28} />
      <p>{text ?? t('common.empty')}</p>
    </div>
  )
}
