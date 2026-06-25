/* Redirect — Import Pipeline merged into Batch Management. */
import { useEffect } from 'react'

export function ImportPipelinePage() {
  useEffect(() => {
    window.location.hash = '#/import-batches'
  }, [])
  return <div className="page" style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>正在跳转到批次管理...</div>
}
