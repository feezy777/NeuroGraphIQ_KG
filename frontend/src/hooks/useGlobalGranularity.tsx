import { createContext, useContext, useMemo, useState, useCallback, useEffect } from 'react'
import { readHashQueryParams, buildHashUrl } from '../utils/pipelineNavigation'

export type GranularityLevel = 'macro' | 'meso' | 'sub_connectivity' | 'fine_cyto' | 'molecular_attr'

export const GRANULARITY_LEVELS: { key: GranularityLevel; label: string }[] = [
  { key: 'macro', label: 'Macro' },
  { key: 'meso', label: 'Meso' },
  { key: 'sub_connectivity', label: 'Subregion' },
  { key: 'fine_cyto', label: 'Cyto' },
  { key: 'molecular_attr', label: 'Molecular' },
]

function resolveGranularity(): GranularityLevel {
  const q = readHashQueryParams()
  const v = q.granularity_level
  if (v && GRANULARITY_LEVELS.some(g => g.key === v)) {
    return v as GranularityLevel
  }
  return 'macro'
}

/** Sync current granularity to URL hash (for bookmarking), without triggering hashchange loops */
function syncHash(level: GranularityLevel) {
  const currentHash = typeof window !== 'undefined' ? window.location.hash : ''
  const path = currentHash.slice(1).split('?')[0] || '/'
  const q = readHashQueryParams()
  q.granularity_level = level
  // Use replaceState to avoid hashchange event / re-render
  const newHash = buildHashUrl(path, q)
  history.replaceState(null, '', newHash)
}

interface GranularityContextValue {
  granularity: GranularityLevel
  setGranularity: (level: GranularityLevel) => void
}

const GranularityContext = createContext<GranularityContextValue>({
  granularity: 'macro',
  setGranularity: () => {},
})

export function GranularityProvider({ children }: { children: React.ReactNode }) {
  const [granularity, setGranularityState] = useState<GranularityLevel>(resolveGranularity)

  const setGranularity = useCallback((level: GranularityLevel) => {
    setGranularityState(level)
    syncHash(level)
  }, [])

  // Initialize from hash on mount only
  useEffect(() => {
    const fromHash = resolveGranularity()
    if (fromHash !== granularity) {
      setGranularityState(fromHash)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const value = useMemo<GranularityContextValue>(() => ({
    granularity,
    setGranularity,
  }), [granularity, setGranularity])

  return (
    <GranularityContext.Provider value={value}>
      {children}
    </GranularityContext.Provider>
  )
}

export function useGlobalGranularity(): GranularityContextValue {
  return useContext(GranularityContext)
}
