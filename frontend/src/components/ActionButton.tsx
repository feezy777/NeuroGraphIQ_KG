import { Loader2 } from 'lucide-react'

type Variant = 'primary' | 'danger' | 'success' | 'default'

interface ActionButtonProps {
  label: string
  onClick: () => void
  loading?: boolean
  disabled?: boolean
  variant?: Variant
}

export function ActionButton({
  label,
  onClick,
  loading = false,
  disabled = false,
  variant = 'default',
}: ActionButtonProps) {
  return (
    <button
      className={`action-btn action-btn-${variant}`}
      onClick={onClick}
      disabled={disabled || loading}
    >
      {loading && <Loader2 size={12} className="spin" />}
      {label}
    </button>
  )
}
