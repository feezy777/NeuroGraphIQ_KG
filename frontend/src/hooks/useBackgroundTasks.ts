import { useState, useEffect, useRef } from 'react'
import {
  listUnifiedTasks,
  getFieldCompletionRun,
  getCompositeWorkflowRun,
  getCircuitExtractionRun,
  getCircuitConnectionExtractionRun,
  getMolecularCircuitRun,
  type UnifiedTaskItem,
} from '../api/endpoints'

// ── Unified task type ───────────────────────────────────────────────────────

export interface BgTask {
  id: string
  type: UnifiedTaskItem['type']
  status: string
  targetType: string | null
  targetCount: number | null
  label: string
  provider: string | null
  modelName: string | null
  createdAt: string
  startedAt: string | null
  completedAt: string | null
  detail: any | null
}

const LIST_LIMIT = 100
const FAST_POLL_MS = 3000
const SLOW_POLL_MS = 15000

// ── Normalizer ──────────────────────────────────────────────────────────────

function mapToBgTask(item: UnifiedTaskItem): BgTask {
  return {
    id: item.id,
    type: item.type,
    status: item.status,
    targetType: item.target_type,
    targetCount: item.target_count,
    label: item.label,
    provider: item.provider,
    modelName: item.model_name,
    createdAt: item.created_at,
    startedAt: item.started_at,
    completedAt: item.completed_at,
    detail: null,
  }
}

// ── Hook ────────────────────────────────────────────────────────────────────

/**
 * Shared hook for both the TaskCenter Page and the Dropdown.
 *
 * Polling strategy:
 *  - If any task is 'running' / 'pending' / 'queued' → 3s interval
 *  - Otherwise → 15s interval (battery-friendly)
 *  - Paused when tab is hidden (visibilitychange), resumed on return
 *  - Deduplication: skips fetch if previous request is still in flight
 */
export function useBackgroundTasks() {
  const [tasks, setTasks] = useState<BgTask[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isActiveRef = useRef(true)
  const inFlightRef = useRef(false)
  const tasksRef = useRef<BgTask[]>([])

  // Keep ref in sync so scheduleNext always reads latest tasks
  tasksRef.current = tasks

  useEffect(() => {
    let cancelled = false
    // Reset on every mount (Strict Mode double-mount sets these to false in cleanup)
    isActiveRef.current = !document.hidden

    const fetchAll = async () => {
      // Guard: prevent concurrent fetches. Check+set is synchronous (no await
      // between) so two calls within the same microtask can't both pass.
      if (!isActiveRef.current || cancelled) return
      if (inFlightRef.current) return
      inFlightRef.current = true
      try {
        const resp = await listUnifiedTasks({ limit: LIST_LIMIT })
        if (cancelled) return
        const mapped = resp.items.map(mapToBgTask)
        setTasks(mapped)
        setLoading(false)
        setError(null)
      } catch {
        if (!cancelled) {
          setLoading(false)
          setError('无法加载后台任务')
        }
      } finally {
        inFlightRef.current = false
      }
    }

    const scheduleNext = () => {
      // Don't schedule if cancelled, hidden, or already scheduled
      if (cancelled || !isActiveRef.current) return
      if (timerRef.current) return  // already have a pending timer
      const hasActive = tasksRef.current.some(
        t => t.status === 'running' || t.status === 'pending' || t.status === 'queued',
      )
      const interval = hasActive ? FAST_POLL_MS : SLOW_POLL_MS
      timerRef.current = setTimeout(() => {
        timerRef.current = null
        fetchAll().then(() => scheduleNext())
      }, interval)
    }

    // ── Visibility-aware pause / resume ─────────────────────────────────
    const handleVisibility = () => {
      isActiveRef.current = !document.hidden
      if (isActiveRef.current && !cancelled && !timerRef.current) {
        fetchAll().then(() => scheduleNext())
      }
    }
    document.addEventListener('visibilitychange', handleVisibility)

    // ── Initial fetch ───────────────────────────────────────────────────
    fetchAll().then(() => scheduleNext())

    return () => {
      cancelled = true
      isActiveRef.current = false
      inFlightRef.current = false  // release lock so next mount can fetch
      if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null }
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [])  // runs once on mount

  return { tasks, loading, error }
}

// ── Detail fetcher ──────────────────────────────────────────────────────────

export async function fetchTaskDetail(task: BgTask): Promise<any> {
  switch (task.type) {
    case 'field_completion': return getFieldCompletionRun(task.id)
    case 'circuit_extraction': return getCircuitExtractionRun(task.id)
    case 'circuit_connection_extraction': return getCircuitConnectionExtractionRun(task.id)
    case 'molecular_circuit': return getMolecularCircuitRun(task.id)
    default: return getCompositeWorkflowRun(task.id)
  }
}
