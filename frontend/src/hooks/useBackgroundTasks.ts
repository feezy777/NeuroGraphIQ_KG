import { useState, useEffect, useRef, useCallback } from 'react'
import {
  listFieldCompletionRuns, getFieldCompletionRun,
  listCompositeWorkflowRuns, getCompositeWorkflowRun,
  listCircuitConnectionExtractionRuns, getCircuitConnectionExtractionRun,
} from '../api/endpoints'
import type { FieldCompletionRun, FieldCompletionRunDetail } from '../api/endpoints'

// ── Unified task type ───────────────────────────────────────────────────────

export interface BgTask {
  id: string
  type: 'field_completion' | 'composite_workflow' | 'circuit_extraction' | 'circuit_connection_extraction'
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
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const isActiveRef = useRef(true)
  const needsPollRef = useRef(false)

  const enablePolling = useCallback(() => { needsPollRef.current = true }, [])
  const disablePolling = useCallback(() => { needsPollRef.current = false }, [])

  useEffect(() => {
    const handleVisibility = () => { isActiveRef.current = !document.hidden }
    document.addEventListener('visibilitychange', handleVisibility)
    return () => document.removeEventListener('visibilitychange', handleVisibility)
  }, [])

  useEffect(() => {
    let cancelled = false
    const fetchAll = async () => {
      if (!needsPollRef.current || !isActiveRef.current) return
      try {
        const [fcRes, cwRes, ceRes, cceRes] = await Promise.allSettled([
          listFieldCompletionRuns({ limit: 200 }),
          listCompositeWorkflowRuns({ limit: 200 }),
          listFieldCompletionRuns({ limit: 200, target_type: 'circuit' as any }), // circuit extraction runs
          listCircuitConnectionExtractionRuns({ limit: 200 }),
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

        if (cceRes.status === 'fulfilled' && cceRes.value?.items) {
          for (const r of cceRes.value.items) {
            merged.push({
              id: r.id, type: 'circuit_connection_extraction', status: r.status,
              targetType: r.mode, targetCount: r.circuit_count,
              label: `回路→连接提取 · ${r.mode}`,
              provider: r.provider ?? undefined, modelName: r.model_name ?? undefined,
              createdAt: r.created_at ?? '', startedAt: r.started_at ?? null, completedAt: r.completed_at ?? null,
              detail: null,
            })
          }
        }

        merged.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
        setTasks(merged)
        setLoading(false)
        setError(null)
      } catch {
        if (!cancelled) { setLoading(false); setError('无法加载后台任务') }
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
  if (task.type === 'circuit_connection_extraction') return getCircuitConnectionExtractionRun(task.id)
  return getCompositeWorkflowRun(task.id)
}
