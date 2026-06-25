/* Redirect to Data Center — Mirror KG browsing is in Data Center. */
import { useEffect } from 'react'

export function MirrorKgPage() {
  useEffect(() => {
    window.location.hash = '#/data-center?tab=mirror'
  }, [])
  return <div className="page" style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>正在跳转到 Data Center → Mirror KG …</div>
}
