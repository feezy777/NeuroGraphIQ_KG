import { useSessionIds } from '../hooks/useSessionIds'
import { CopyButton } from './CopyButton'
import { useI18n } from '../i18n-context'

const LABELS: Array<{ key: keyof import('../hooks/useSessionIds').PipelineIds; label: string }> = [
  { key: 'resource_id', label: 'resource_id' },
  { key: 'file_id', label: 'file_id' },
  { key: 'batch_id', label: 'batch_id' },
  { key: 'parse_run_id', label: 'parse_run_id' },
  { key: 'generation_run_id', label: 'generation_run_id' },
  { key: 'candidate_id', label: 'candidate_id' },
  { key: 'final_region_id', label: 'final_region_id' },
]

export function SessionIdsPanel() {
  const { ids, clearIds } = useSessionIds()
  const { t } = useI18n()
  const entries = LABELS.filter(e => ids[e.key])

  if (entries.length === 0) return null

  return (
    <div className="card session-ids-panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div className="card-title" style={{ marginBottom: 0 }}>{t('sessionIds.panelTitle')}</div>
        <button className="btn" style={{ fontSize: 11, padding: '2px 8px' }} onClick={clearIds}>{t('sessionIds.clear')}</button>
      </div>
      <div className="session-ids-grid">
        {entries.map(e => (
          <div key={e.key} className="session-id-row">
            <span className="session-id-label">{e.label}</span>
            <code className="text-mono session-id-value">{ids[e.key]}</code>
            <CopyButton value={ids[e.key]!} />
          </div>
        ))}
      </div>
    </div>
  )
}
