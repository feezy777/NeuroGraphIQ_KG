import { createContext, useContext, useState, useCallback } from 'react'
import type { ReactNode } from 'react'
import type { BgTask } from '../hooks/useBackgroundTasks'
import { fetchTaskDetail } from '../hooks/useBackgroundTasks'
import { FieldCompletionStatsCards } from '../pages/data-center/FieldCompletionStatsCards'
import { ExtractionProgressPanel } from '../pages/llm-extraction/components/ExtractionProgressPanel'
import type { ProgressData } from '../pages/llm-extraction/types'
import { cancelFieldCompletionRun, cancelCompositeWorkflow, cancelCircuitConnectionExtractionRun, pauseCompositeWorkflow } from '../api/endpoints'
import { StatusBadge } from './StatusBadge'
import { ModelBadge } from './ModelBadge'

// ── Context ─────────────────────────────────────────────────────────────────

interface TaskDetailCtx {
  openTask: (task: BgTask) => void
  closeTask: () => void
}

const Ctx = createContext<TaskDetailCtx>({ openTask: () => {}, closeTask: () => {} })

export function useTaskDetailModal() { return useContext(Ctx) }

// ── Mapper: CompositeWorkflowRunRead → ProgressData ─────────────────────────

function mapCwToProgress(detail: any, elapsedSec: number): ProgressData {
  const s = detail.result_summary || detail.result_summary_json || {}
  return {
    workflowRunId: detail.id || '',
    workflowStatus: detail.status || '',
    progressPercent: detail.progress_percent ?? s.progress_percent ?? 0,
    processedPacks: s.completed_pack_count ?? s.processed_packs ?? 0,
    totalPacks: s.total_pack_count ?? s.total_packs ?? detail.pair_count ?? 1,
    successPacks: s.succeeded_pack_count ?? s.success_packs ?? 0,
    failedPacks: s.failed_pack_count ?? s.failed_packs ?? 0,
    noConnectionPacks: s.no_connection_pack_count ?? 0,
    noFindingsPacks: s.no_findings_pack_count ?? 0,
    connectionsFound: s.parsed_connection_count ?? s.parsed_projection_count ?? s.connections_found ?? 0,
    screenedLikelyCount: s.screened_likely_connection_count ?? 0,
    functionCount: s.parsed_function_count ?? s.function_count ?? 0,
    parsedNoConnCount: s.parsed_no_connection_count ?? 0,
    createdCount: s.created_projection_count ?? s.created_count ?? 0,
    updatedCount: s.updated_projection_count ?? s.updated_count ?? 0,
    mergedCount: s.merged_projection_count ?? s.merged_count ?? 0,
    skippedDupCount: s.skipped_duplicate_count ?? 0,
    noConnectionCount: s.no_connection_count ?? 0,
    providerCallCount: s.provider_call_count ?? 0,
    modelCalls: s.model_call_count ?? s.model_calls ?? 0,
    promptSent: s.prompt_sent_count ?? 0,
    inFlightPacks: s.in_flight_pack_count ?? 0,
    concurrency: s.concurrency ?? 1,
    averagePackSec: s.average_pack_sec ?? null,
    estimatedRemainingSec: s.estimated_remaining_sec ?? null,
    zeroDiags: [],
    errors: detail.errors_json ?? detail.errors ?? [],
    elapsedSec,
    startedAt: detail.started_at ?? null,
    lastPauseResponse: '',
    lastPauseError: '',
    lastCancelResponse: '',
    lastCancelError: '',
    estimatedInputTokens: s.estimated_input_tokens ?? 0,
    estimatedOutputTokens: s.estimated_output_tokens ?? 0,
    actualPromptTokens: s.actual_prompt_tokens ?? s.prompt_tokens ?? 0,
    actualCompletionTokens: s.actual_completion_tokens ?? s.completion_tokens ?? 0,
    dryRunSamplePack: false,
  }
}

// ── Provider ────────────────────────────────────────────────────────────────

export function TaskDetailModalProvider({ children }: { children: ReactNode }) {
  const [task, setTask] = useState<BgTask | null>(null)
  const [detail, setDetail] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const openTask = useCallback(async (t: BgTask) => {
    setTask(t)
    setDetail(null)
    setLoading(true)
    try { setDetail(await fetchTaskDetail(t)) } catch { /* ignore */ }
    setLoading(false)
  }, [])

  const closeTask = useCallback(() => { setTask(null); setDetail(null) }, [])

  // "后台运行" — just close modal, task keeps running
  const handleBackground = useCallback(() => {
    setTask(null)
    setDetail(null)
  }, [])

  const handleCancel = useCallback(async () => {
    if (!task) return
    try {
      if (task.type === 'field_completion') await cancelFieldCompletionRun(task.id)
      else if (task.type === 'circuit_connection_extraction') await cancelCircuitConnectionExtractionRun(task.id)
      else await cancelCompositeWorkflow(task.id)
      // Re-fetch to show updated status
      const updated = await fetchTaskDetail(task)
      setDetail(updated)
    } catch { /* ignore */ }
  }, [task])

  const handlePause = useCallback(async () => {
    if (!task || task.type === 'field_completion') return
    try {
      await pauseCompositeWorkflow(task.id)
      const updated = await fetchTaskDetail(task)
      setDetail(updated)
    } catch { /* ignore */ }
  }, [task])

  const isRunning = task?.status === 'running' || task?.status === 'pending' || task?.status === 'queued'
  const isCancelling = task?.status === 'cancelling'
  const isTerminal = !isRunning && !isCancelling

  const elapsed = task?.startedAt
    ? Math.round((Date.now() - new Date(task.startedAt).getTime()) / 1000)
    : 0

  return (
    <Ctx.Provider value={{ openTask, closeTask }}>
      {children}
      {task && (
        <div className="task-center-modal">
          <div className="task-center-modal-backdrop" onClick={closeTask} />
          <div className="task-center-modal-panel">
            <div className="task-center-modal-header">
              <h3>{task.type === 'field_completion' ? '🔧 字段补全' : task.type === 'circuit_connection_extraction' ? '🔄 回路→连接提取' : '🔗 LLM 提取'}</h3>
              <span style={{ fontSize: 12, color: '#888' }}>{task.label}</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <ModelBadge provider={task.provider} modelName={task.modelName} />
                <StatusBadge status={task.status} />
              </div>
              <button className="btn-close" onClick={closeTask}>✕</button>
            </div>
            <div className="task-center-modal-body">
              {loading ? (
                <div style={{ textAlign: 'center', padding: 40, color: '#888' }}>
                  <div className="dc-wizard-loading" />
                  <p style={{ marginTop: 12 }}>加载任务详情…</p>
                </div>
              ) : detail ? (
                (task.type === 'field_completion' || task.type === 'circuit_connection_extraction') ? (
                  <FieldCompletionStatsCards
                    detail={detail}
                    status={detail.status || task.status}
                    targetCount={task.targetCount ?? 0}
                    elapsedSec={elapsed}
                    onCancel={isRunning && !isCancelling ? handleCancel : undefined}
                    onClose={isRunning ? handleBackground : closeTask}
                  />
                ) : (
                  <ExtractionProgressPanel
                    progress={mapCwToProgress(detail, elapsed)}
                    onPause={isRunning && !isCancelling ? handlePause : undefined}
                    onCancel={isRunning ? handleCancel : () => {}}
                    onClose={isRunning ? handleBackground : closeTask}
                    showPause={isRunning && !isCancelling}
                    showRetry={false}
                  />
                )
              ) : (
                <div style={{ padding: 40, textAlign: 'center', color: '#888' }}>暂无详情</div>
              )}
            </div>
          </div>
        </div>
      )}
    </Ctx.Provider>
  )
}
