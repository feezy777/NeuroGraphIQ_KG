import { useCallback, useState } from 'react'

const KEY = 'ngiq_pipeline_ids'

export interface PipelineIds {
  resource_id?: string
  file_id?: string
  batch_id?: string
  parse_run_id?: string
  generation_run_id?: string
  validation_run_id?: string
  rollback_record_id?: string
  candidate_id?: string
  final_region_id?: string
  source_atlas?: string
  granularity_family?: string
}

export function readSessionIds(): PipelineIds {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) ?? '{}') as PipelineIds
  } catch {
    return {}
  }
}

function read(): PipelineIds {
  return readSessionIds()
}

export function useSessionIds() {
  const [ids, setIdsState] = useState<PipelineIds>(read)

  const setIds = useCallback((patch: Partial<PipelineIds>) => {
    const next = { ...read(), ...patch }
    sessionStorage.setItem(KEY, JSON.stringify(next))
    setIdsState(next)
  }, [])

  const clearIds = useCallback(() => {
    sessionStorage.removeItem(KEY)
    setIdsState({})
  }, [])

  const clearKey = useCallback((key: keyof PipelineIds) => {
    const stored = read()
    delete stored[key]
    sessionStorage.setItem(KEY, JSON.stringify(stored))
    setIdsState({ ...stored })
  }, [])

  return { ids, setIds, clearIds, clearKey }
}
