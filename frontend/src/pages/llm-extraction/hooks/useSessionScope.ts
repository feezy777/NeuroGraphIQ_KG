import { useState, useCallback } from 'react'
import { readSessionIds, type PipelineIds } from '../../../hooks/useSessionIds'

const SESSION_KEY = 'ngiq_pipeline_ids'

export interface SessionScope {
  resource_id: string
  batch_id: string
  source_atlas: string
  granularity_level: string
  granularity_family: string
  source_version: string
}

const EMPTY_SCOPE: SessionScope = {
  resource_id: '',
  batch_id: '',
  source_atlas: '',
  granularity_level: '',
  granularity_family: '',
  source_version: '',
}

function writeSessionPatch(patch: Partial<PipelineIds>) {
  const next = { ...readSessionIds(), ...patch }
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(next))
}

function clearSessionKey(key: keyof PipelineIds) {
  const stored = { ...readSessionIds() }
  delete stored[key]
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(stored))
}

/**
 * Session scope for LLM extraction — reads/writes sessionStorage directly.
 * Does not call useSessionIds() to avoid hook-chain issues on LlmExtractionPage.
 */
export function useSessionScope() {
  const [scope, setScope] = useState<SessionScope>(() => {
    const sess = readSessionIds()
    return {
      resource_id: sess.resource_id ?? '',
      batch_id: sess.batch_id ?? '',
      source_atlas: 'AAL3',
      granularity_level: 'macro',
      granularity_family: 'macro_clinical',
      source_version: '',
    }
  })

  const updateScope = useCallback((patch: Partial<SessionScope>) => {
    setScope(prev => ({ ...prev, ...patch }))
    if ('batch_id' in patch) {
      const batchId = patch.batch_id?.trim() ?? ''
      if (batchId) writeSessionPatch({ batch_id: batchId })
      else clearSessionKey('batch_id')
    }
    if ('resource_id' in patch) {
      const resourceId = patch.resource_id?.trim() ?? ''
      if (resourceId) writeSessionPatch({ resource_id: resourceId })
      else clearSessionKey('resource_id')
    }
  }, [])

  const clearScope = useCallback(() => {
    setScope(EMPTY_SCOPE)
    clearSessionKey('batch_id')
    clearSessionKey('resource_id')
  }, [])

  return { scope, updateScope, clearScope }
}
