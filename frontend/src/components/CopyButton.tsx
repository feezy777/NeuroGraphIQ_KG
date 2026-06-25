import { useState } from 'react'
import { Copy, Check } from 'lucide-react'
import { useI18n } from '../i18n-context'

interface CopyButtonProps {
  value: string
  label?: string
  title?: string
  ariaLabel?: string
}

export function CopyButton({ value, label, title, ariaLabel }: CopyButtonProps) {
  const { t } = useI18n()
  const [copied, setCopied] = useState(false)
  const displayLabel = label ?? t('common.copy')
  const iconOnly = label === ''
  const tooltip = title ?? value
  const aria = ariaLabel ?? title ?? t('common.copy')

  async function handleCopy(e: React.MouseEvent) {
    e.stopPropagation()
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = value
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }
  }

  return (
    <button
      type="button"
      className={`copy-btn${iconOnly ? ' copy-btn--icon-only' : ''}`}
      onClick={handleCopy}
      title={tooltip}
      aria-label={aria}
    >
      {copied ? <Check size={12} /> : <Copy size={12} />}
      {!iconOnly && (copied ? t('common.copied') : displayLabel)}
    </button>
  )
}
