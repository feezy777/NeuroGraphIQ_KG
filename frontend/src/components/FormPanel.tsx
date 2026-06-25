import React, { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

interface FormPanelProps {
  title: string
  defaultOpen?: boolean
  children: React.ReactNode
}

export function FormPanel({ title, defaultOpen = false, children }: FormPanelProps) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="form-panel">
      <button className="form-toggle" onClick={() => setOpen(o => !o)}>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {title}
      </button>
      {open && <div className="form-body">{children}</div>}
    </div>
  )
}
