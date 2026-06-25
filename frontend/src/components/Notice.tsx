import { useEffect } from 'react'

export interface NoticeState {
  type: 'success' | 'error' | 'warning'
  message: string
}

interface NoticeProps {
  notice: NoticeState | null
  onClose: () => void
  autoDismissMs?: number
}

export function Notice({ notice, onClose, autoDismissMs = 7000 }: NoticeProps) {
  useEffect(() => {
    if (!notice) return
    const t = setTimeout(onClose, autoDismissMs)
    return () => clearTimeout(t)
  }, [notice, onClose, autoDismissMs])

  if (!notice) return null

  return (
    <div className={`notice notice-${notice.type}`}>
      <span className="notice-msg">{notice.message}</span>
      <button className="notice-close" onClick={onClose}>×</button>
    </div>
  )
}
