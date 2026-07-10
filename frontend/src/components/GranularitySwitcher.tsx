import { useGlobalGranularity, GRANULARITY_LEVELS } from '../hooks/useGlobalGranularity'

export function GranularitySwitcher() {
  const { granularity, setGranularity } = useGlobalGranularity()

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      <span style={{ fontSize: 12, color: 'var(--text-secondary, #64748b)', marginRight: 6, fontWeight: 500 }}>
        粒度:
      </span>
      {GRANULARITY_LEVELS.map(g => (
        <button
          key={g.key}
          type="button"
          onClick={() => setGranularity(g.key)}
          style={{
            padding: '3px 10px',
            fontSize: 12,
            fontWeight: granularity === g.key ? 600 : 400,
            border: `1px solid ${granularity === g.key ? 'var(--primary, #2563eb)' : 'var(--border-light, #e2e8f0)'}`,
            borderRadius: 4,
            background: granularity === g.key ? 'var(--primary, #2563eb)' : 'transparent',
            color: granularity === g.key ? '#fff' : 'var(--text-secondary, #64748b)',
            cursor: 'pointer',
            transition: 'all 0.15s',
          }}
        >
          {g.label}
        </button>
      ))}
    </div>
  )
}
