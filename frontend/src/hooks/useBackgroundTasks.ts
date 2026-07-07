import { useState, useEffect, useRef, useCallback } from 'react'
import { listFieldCompletionRuns, getFieldCompletionRun } from '../api/endpoints'
import { listCompositeWorkflowRuns, getCompositeWorkflowRun } from '../api/endpoints'
import { getCircuitExtractionRun } from '../api/endpoints'
import type { FieldCompletionRun, FieldCompletionRunDetail } from '../api/endpoints'

// ── Unified task type ───────────────────────────────────────────────────────

export interface BgTask {
  id: string
  type: 'field_completion' | 'composite_workflow' | 'circuit_extraction'
  status: string
  targetType?: string
  targetCount?: number
  label: string
  provider?: string
  modelName?: string
  createdAt: string
  startedAt?: string | null
  completedAt?: string | null
  detail?: any
}

// ── Hook ────────────────────────────────────────────────────────────────────

export function useBackgroundTasks(pollMs = 3000) {
  const [tasks, setTasks] = useState<BgTask[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)  // M1: surface API errors
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const isActiveRef = useRef(true)        // page visibility
  const needsPollRef = useRef(false)      // task center / dropdown mounted

  // Enable/disable polling from consumers
  const enablePolling = useCallback(() => { needsPollRef.current = true }, [])
  const disablePolling = useCallback(() => { needsPollRef.current = false }, [])

  useEffect(() => {
    const handleVisibility = () => {
      isActiveRef.current = !document.hidden
    }
    document.addEventListener('visibilitychange', handleVisibility)
    return () => document.removeEventListener('visibilitychange', handleVisibility)
  }, [])

  useEffect(() => {
    let cancelled = false
    const fetchAll = async () => {
      // Skip if not needed or page hidden
      if (!needsPollRef.current || !isActiveRef.current) return
      try {
        // Import dynamically to avoid circular deps
        const { listMirrorConnections: _lmc } = await import('../api/endpoints')
        const listCircuitRuns = async () => {
          const resp = await fetch('/api/llm-extraction/circuit-extraction/runs?limit=200')
          return resp.json()
        }
        const [fcRes, cwRes, ccRes] = await Promise.allSettled([
          listFieldCompletionRuns({ limit: 200 }),
          listCompositeWorkflowRuns({ limit: 200 }),
          listCircuitRuns(),
        ])

        if (cancelled) return

        const merged: BgTask[] = []

        if (fcRes.status === 'fulfilled') {
          for (const r of fcRes.value.items) {
            merged.push({
              id: r.id, type: 'field_completion', status: r.status,
              targetType: r.target_type, targetCount: r.target_count,
              label: `字段补全 · ${r.target_type}`,
              provider: r.provider ?? undefined, modelName: r.model_name ?? undefined,
              createdAt: r.created_at, startedAt: r.started_at, completedAt: r.completed_at,
              detail: null,
            })
          }
        }

        if (cwRes.status === 'fulfilled') {
          for (const r of cwRes.value.items) {
            merged.push({
              id: r.id, type: 'composite_workflow', status: r.status,
              targetType: r.workflow_type ?? undefined, targetCount: r.candidate_count,
              label: `LLM 提取 · ${r.workflow_type}`,
              provider: r.provider ?? undefined, modelName: r.model_name ?? undefined,
              createdAt: r.created_at ?? '', startedAt: r.started_at ?? null, completedAt: r.completed_at ?? null,
              detail: null,
            })
          }
        }

        if (ccRes.status === 'fulfilled' && ccRes.value?.items) {
          for (const r of ccRes.value.items) {
            merged.push({
              id: r.id, type: 'circuit_extraction', status: r.status,
              targetType: 'circuit', targetCount: r.candidate_count,
              label: `回路提取 · ${r.candidate_count} 脑区`,
              provider: r.provider ?? undefined, modelName: r.model_name ?? undefined,
              createdAt: r.created_at ?? '', startedAt: r.started_at ?? null, completedAt: r.completed_at ?? null,
              detail: null,
            })
          }
        }

        merged.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
        setTasks(merged)
        setLoading(false)
        setError(null)  // M1: clear error on success
      } catch {
        if (!cancelled) {
          setLoading(false)
          setError('无法加载后台任务，请检查后端服务是否运行')  // M1: surface error
        }
      }
    }

    fetchAll()
    timerRef.current = setInterval(fetchAll, pollMs)
    return () => { cancelled = true; if (timerRef.current) clearInterval(timerRef.current) }
  }, [pollMs])

  return { tasks, loading, error, enablePolling, disablePolling }
}

// ── Detail fetcher ──────────────────────────────────────────────────────────

export async function fetchTaskDetail(task: BgTask): Promise<any> {
  if (task.type === 'field_completion') return getFieldCompletionRun(task.id)
  if (task.type === 'circuit_extraction') return getCircuitExtractionRun(task.id)
  return getCompositeWorkflowRun(task.id)
}
