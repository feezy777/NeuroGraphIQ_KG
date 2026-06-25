import { useState, useEffect, useCallback } from 'react'

interface DataState<T> {
  data: T | null
  loading: boolean
  error: string | null
}

export function useData<T>(
  fetchFn: () => Promise<T>,
  deps: unknown[],
): DataState<T> & { reload: () => void } {
  const [state, setState] = useState<DataState<T>>({ data: null, loading: true, error: null })
  const [tick, setTick] = useState(0)
  const reload = useCallback(() => setTick(t => t + 1), [])

  useEffect(() => {
    let cancelled = false
    setState(s => ({ ...s, loading: true, error: null }))
    fetchFn()
      .then(data => {
        if (!cancelled) setState({ data, loading: false, error: null })
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : String(err)
          setState({ data: null, loading: false, error: msg })
        }
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  return { ...state, reload }
}
