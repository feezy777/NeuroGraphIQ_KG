import { useState, useEffect, useCallback, useRef } from 'react'
import { buildApiUrl } from '../../api/client'

// ── Types ───────────────────────────────────────────────────────────────────────

export interface GraphFilters {
  atlas: string
  granularity: string
  type: string
}

interface GraphSidebarProps {
  filters: GraphFilters
  onFiltersChange: (filters: GraphFilters) => void
  selectedNode: Record<string, unknown> | null
  onSearch: (params?: Record<string, string>) => void
}

interface AtlasOption {
  source_atlas: string
}

interface AutoCompleteOption {
  id: string
  label: string
}

// ── Legend Data ──────────────────────────────────────────────────────────────────

const NODE_COLORS = [
  { label: 'Macro', color: '#3b82f6' },
  { label: 'Meso', color: '#22c55e' },
  { label: 'Subregion', color: '#f97316' },
  { label: 'Fine', color: '#8b5cf6' },
  { label: 'Molecular', color: '#ec4899' },
]

const EDGE_LEGEND = [
  { label: 'Structural Connection', style: 'solid', color: '#1e40af' },
  { label: 'Functional Connection', style: 'solid', color: '#ea580c' },
  { label: 'Has Function', style: 'dashed', color: '#ca8a04' },
]

// ── Sidebar Component ───────────────────────────────────────────────────────────

export function FinalKgGraphSidebar({
  filters,
  onFiltersChange,
  selectedNode,
  onSearch,
}: GraphSidebarProps) {
  const [atlasOptions, setAtlasOptions] = useState<string[]>([])
  const [searchTerm, setSearchTerm] = useState('')
  const [autoCompleteResults, setAutoCompleteResults] = useState<AutoCompleteOption[]>([])
  const [showAutoComplete, setShowAutoComplete] = useState(false)
  const autoCompleteRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  // Fetch atlas options
  useEffect(() => {
    const fetchOptions = async () => {
      try {
        const url = buildApiUrl('/api/final-regions/options')
        const res = await fetch(url)
        if (!res.ok) return
        const data: Record<string, unknown> = await res.json()
        const atlases = data.source_atlas as string[] | undefined
        if (Array.isArray(atlases)) {
          setAtlasOptions(atlases)
        }
      } catch {
        // Silently fail: options are optional
      }
    }
    fetchOptions()
  }, [])

  // Autocomplete search
  const handleSearchChange = useCallback(
    (value: string) => {
      setSearchTerm(value)
      if (debounceRef.current) clearTimeout(debounceRef.current)

      if (value.length < 2) {
        setAutoCompleteResults([])
        setShowAutoComplete(false)
        return
      }

      debounceRef.current = setTimeout(async () => {
        try {
          const url = buildApiUrl('/api/final-regions', { keyword: value, limit: 10 })
          const res = await fetch(url)
          if (!res.ok) return
          const data = await res.json()
          const items = (data.items || []).map((item: Record<string, unknown>) => ({
            id: item.id as string,
            label: (item.en_name as string) || (item.cn_name as string) || (item.raw_name as string) || (item.id as string),
          }))
          setAutoCompleteResults(items)
          setShowAutoComplete(true)
        } catch {
          // Silently fail
        }
      }, 300)
    },
    [],
  )

  const selectAutoComplete = useCallback(
    (id: string) => {
      setShowAutoComplete(false)
      setSearchTerm('')
      onSearch({ center_type: 'brain_region', centerId: id, depth: '1', include_functions: 'true', limit: '200' })
    },
    [onSearch],
  )

  // Close autocomplete on outside click
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (autoCompleteRef.current && !autoCompleteRef.current.contains(e.target as Node)) {
        setShowAutoComplete(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const nodeTypeOptions = ['brain_region', 'circuit', 'function', 'circuit_step']

  return (
    <aside className="graph-sidebar">
      {/* ── Filters Section ── */}
      <div className="graph-sidebar-section">
        <h3 className="graph-sidebar-title">Filters</h3>

        <label className="graph-sidebar-label">Atlas</label>
        <select
          className="graph-sidebar-select"
          value={filters.atlas}
          onChange={e => onFiltersChange({ ...filters, atlas: e.target.value })}
        >
          <option value="">All Atlases</option>
          {atlasOptions.map(a => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>

        <label className="graph-sidebar-label">Granularity</label>
        <select
          className="graph-sidebar-select"
          value={filters.granularity}
          onChange={e => onFiltersChange({ ...filters, granularity: e.target.value })}
        >
          <option value="">All Granularities</option>
          <option value="macro">Macro</option>
          <option value="meso">Meso</option>
          <option value="sub">Subregion</option>
          <option value="fine">Fine (Cyto)</option>
          <option value="molecular">Molecular</option>
        </select>

        <label className="graph-sidebar-label">Type</label>
        <select
          className="graph-sidebar-select"
          value={filters.type}
          onChange={e => onFiltersChange({ ...filters, type: e.target.value })}
        >
          {nodeTypeOptions.map(t => (
            <option key={t} value={t}>
              {t.replace(/_/g, ' ')}
            </option>
          ))}
        </select>
      </div>

      {/* ── Search Section ── */}
      <div className="graph-sidebar-section">
        <h3 className="graph-sidebar-title">Search Region</h3>
        <div className="graph-sidebar-autocomplete" ref={autoCompleteRef}>
          <input
            className="graph-sidebar-input"
            type="text"
            placeholder="Type region name..."
            value={searchTerm}
            onChange={e => handleSearchChange(e.target.value)}
            onFocus={() => {
              if (autoCompleteResults.length > 0) setShowAutoComplete(true)
            }}
          />
          {showAutoComplete && autoCompleteResults.length > 0 && (
            <div className="graph-sidebar-autocomplete-dropdown">
              {autoCompleteResults.map(r => (
                <button
                  key={r.id}
                  type="button"
                  className="graph-sidebar-autocomplete-item"
                  onClick={() => selectAutoComplete(r.id)}
                >
                  {r.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Selected Node Detail ── */}
      {selectedNode && (
        <div className="graph-sidebar-section">
          <h3 className="graph-sidebar-title">Selected Node</h3>
          <div className="graph-sidebar-detail-card">
            <div className="graph-detail-row">
              <span className="graph-detail-label">Label</span>
              <span className="graph-detail-value">{(selectedNode.data as Record<string, unknown>)?.label as string || (selectedNode.label as string) || '-'}</span>
            </div>
            <div className="graph-detail-row">
              <span className="graph-detail-label">Type</span>
              <span className="graph-detail-value">{(selectedNode.data as Record<string, unknown>)?.nodeType as string || (selectedNode.type as string) || '-'}</span>
            </div>
            <div className="graph-detail-row">
              <span className="graph-detail-label">Atlas</span>
              <span className="graph-detail-value">
                {((selectedNode.data as Record<string, unknown>)?.metadata as Record<string, unknown>)?.source_atlas as string || '-'}
              </span>
            </div>
            <div className="graph-detail-row">
              <span className="graph-detail-label">Granularity</span>
              <span className="graph-detail-value">
                {((selectedNode.data as Record<string, unknown>)?.metadata as Record<string, unknown>)?.granularity_family as string || '-'}
              </span>
            </div>
            <div className="graph-detail-row">
              <span className="graph-detail-label">Connections</span>
              <span className="graph-detail-value">
                {((selectedNode.data as Record<string, unknown>)?.metadata as Record<string, unknown>)?.connection_count as string || '-'}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* ── Legend Section ── */}
      <div className="graph-sidebar-section">
        <h3 className="graph-sidebar-title">Legend</h3>

        <div className="graph-legend-subtitle">Node Colors</div>
        {NODE_COLORS.map(nc => (
          <div key={nc.label} className="graph-legend-row">
            <span className="graph-legend-swatch" style={{ background: nc.color }} />
            <span className="graph-legend-label">{nc.label}</span>
          </div>
        ))}

        <div className="graph-legend-subtitle" style={{ marginTop: 12 }}>Edge Styles</div>
        {EDGE_LEGEND.map(el => (
          <div key={el.label} className="graph-legend-row">
            <span
              className="graph-legend-line"
              style={{
                borderBottom: `${el.style === 'dashed' ? '2px dashed' : '2px solid'} ${el.color}`,
              }}
            />
            <span className="graph-legend-label">{el.label}</span>
          </div>
        ))}
      </div>
    </aside>
  )
}
