import { Fragment } from 'react'
import React from 'react'

interface KVEntry {
  label: string
  value: React.ReactNode
}

export function KeyValuePanel({ entries }: { entries: KVEntry[] }) {
  return (
    <div className="kv-grid">
      {entries.map((e, i) => (
        <Fragment key={i}>
          <span className="kv-key">{e.label}</span>
          <span className="kv-val">
            {e.value !== null && e.value !== undefined && e.value !== ''
              ? e.value
              : <span className="text-muted">—</span>}
          </span>
        </Fragment>
      ))}
    </div>
  )
}
