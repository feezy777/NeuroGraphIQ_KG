/**
 * Bridge LLM composite extraction progress into the workbench log console.
 * Dedupes by stable keys so polling does not flood the console.
 */

import type { LlmWorkflowEvent } from '../../../api/endpoints'
import { emitWorkbenchLog } from '../../../logging/logBridge'
import type { CompositeProgressMeta, CompositeSubstepResult } from './compositeExtractionRunner'

const seenWorkflowEventIds = new Set<string>()
const seenProgressLogKeys = new Set<string>()
const lastSubstepStatus = new Map<string, string>()

function logOnce(key: string, entry: Parameters<typeof emitWorkbenchLog>[0]): void {
  if (seenProgressLogKeys.has(key)) return
  seenProgressLogKeys.add(key)
  emitWorkbenchLog(entry)
}

function formatDataBrief(data: Record<string, unknown> | undefined, maxLen = 800): string {
  if (!data || Object.keys(data).length === 0) return ''
  try {
    const text = JSON.stringify(data)
    if (text.length <= maxLen) return text
    return `${text.slice(0, maxLen)}…[truncated]`
  } catch {
    return String(data)
  }
}

export function logWorkflowEvents(events: LlmWorkflowEvent[] | undefined): void {
  if (!events?.length) return
  for (const ev of events) {
    const id = ev.event_id ?? `${ev.ts}:${ev.step_key ?? ''}:${ev.event}:${String(ev.data?.pack_id ?? '')}`
    if (seenWorkflowEventIds.has(id)) continue
    seenWorkflowEventIds.add(id)

    const level = ev.level === 'error' ? 'error' : ev.level === 'warning' ? 'warning' : 'info'
    const packIndex = ev.data?.pack_index
    const packCount = ev.data?.pack_count
    const packInfo = packIndex != null && packCount != null
      ? ` pack=${Number(packIndex)}/${Number(packCount)}`
      : ev.data?.pack_id != null
        ? ` pack=${String(ev.data.pack_id)}`
        : ''
    const dataBrief = formatDataBrief(ev.data as Record<string, unknown> | undefined)
    const previewRaw = ev.data?.raw_response_preview
    const preview = typeof previewRaw === 'string' && previewRaw
      ? `\nraw_response_preview=${previewRaw.slice(0, 500)}`
      : ''

    emitWorkbenchLog({
      level,
      source: 'system',
      title: `[LLM Workflow] ${ev.event}`,
      message: [
        ev.step_key ?? 'workflow',
        packInfo,
        ev.message,
        dataBrief ? `data=${dataBrief}` : '',
        preview,
      ].filter(Boolean).join(' — '),
      detail: ev.data,
      tags: ['llm-workflow', ev.step_key ?? 'workflow', ev.event].filter(Boolean),
    })
  }
}

export function logCompositeProgressSnapshot(
  substeps: CompositeSubstepResult[],
  meta?: CompositeProgressMeta,
  extras?: {
    workflowWarnings?: string[]
    workflowErrors?: string[]
    workflowRunId?: string
  },
): void {
  const runId = meta?.workflowRunId ?? extras?.workflowRunId ?? 'unknown'

  if (meta?.phase === 'starting') {
    logOnce(`phase:start:${runId}`, {
      level: 'info',
      source: 'system',
      title: '[LLM Extraction] 开始',
      message: `workflow_run_id=${runId} — 正在启动 composite workflow`,
      tags: ['llm-extraction', 'start'],
    })
  }

  if (meta?.workflowStatus) {
    logOnce(`wf-status:${runId}:${meta.workflowStatus}`, {
      level: meta.workflowStatus.includes('fail') || meta.workflowStatus === 'cleanup_failed'
        ? 'error'
        : meta.workflowStatus.includes('cancel') || meta.workflowStatus === 'cancelling'
          ? 'warning'
          : 'info',
      source: 'system',
      title: '[LLM Extraction] Workflow 状态',
      message: `workflow_run_id=${runId.slice(0, 12)}… status=${meta.workflowStatus} elapsed=${meta.elapsedMs ?? 0}ms progress=${meta.progressPercent ?? '?'}`,
      tags: ['llm-extraction', 'workflow-status'],
    })
  }

  for (const step of substeps) {
    const prev = lastSubstepStatus.get(step.id)
    if (prev !== step.status) {
      lastSubstepStatus.set(step.id, step.status)
      if (prev != null || step.status !== 'pending') {
        const level =
          step.status === 'failed' || step.status === 'failed_validation' ? 'error'
          : step.status === 'skipped_dependency_failed' ? 'warning'
          : 'info'
        logOnce(`step-status:${runId}:${step.id}:${step.status}`, {
          level,
          source: 'system',
          title: `[LLM Extraction] 子步骤 ${step.id}`,
          message: `${step.label} → ${step.status}${step.createdCount != null ? ` created=${step.createdCount}` : ''}`,
          tags: ['llm-extraction', 'substep', step.id],
        })
      }
    }

    for (const w of step.warnings ?? []) {
      logOnce(`step-warn:${runId}:${step.id}:${w.slice(0, 200)}`, {
        level: 'warning',
        source: 'system',
        title: `[LLM Extraction] 警告 · ${step.id}`,
        message: w,
        tags: ['llm-extraction', 'warning', step.id],
      })
    }

    if (step.error) {
      logOnce(`step-err:${runId}:${step.id}:${step.error.slice(0, 200)}`, {
        level: 'error',
        source: 'system',
        title: `[LLM Extraction] 错误 · ${step.id}`,
        message: step.error,
        tags: ['llm-extraction', 'error', step.id],
      })
    }

    const summary = step.executionSummary
    if (summary && step.id === 'connection') {
      const callCount = summary.provider_call_count
      if (callCount != null) {
        logOnce(
          `audit-calls:${runId}:${String(callCount)}:${String(summary.prompt_sent_count ?? 0)}`,
          {
            level: 'info',
            source: 'system',
            title: '[LLM Extraction] Provider 审计',
            message: [
              `provider_call_count=${callCount}`,
              `prompt_sent_count=${summary.prompt_sent_count ?? 0}`,
              `parse_error_count=${summary.parse_error_count ?? 0}`,
              `transport_error_count=${summary.provider_transport_error_count ?? 0}`,
              `pack_count=${summary.pack_count ?? '?'}`,
            ].join(' '),
            detail: summary,
            tags: ['llm-extraction', 'provider-audit'],
          },
        )
      }
    }
  }

  for (const w of extras?.workflowWarnings ?? []) {
    logOnce(`wf-warn:${runId}:${w.slice(0, 200)}`, {
      level: 'warning',
      source: 'system',
      title: '[LLM Extraction] Workflow 警告',
      message: w,
      tags: ['llm-extraction', 'workflow-warning'],
    })
  }

  for (const e of extras?.workflowErrors ?? []) {
    logOnce(`wf-err:${runId}:${e.slice(0, 200)}`, {
      level: 'error',
      source: 'system',
      title: '[LLM Extraction] Workflow 错误',
      message: e,
      tags: ['llm-extraction', 'workflow-error'],
    })
  }

  if (meta?.phase === 'complete') {
    logOnce(`phase:complete:${runId}:${meta.workflowStatus ?? 'done'}`, {
      level: meta.workflowStatus?.includes('fail') ? 'error' : 'info',
      source: 'system',
      title: '[LLM Extraction] 完成',
      message: `workflow_run_id=${runId.slice(0, 12)}… final_status=${meta.workflowStatus ?? 'unknown'} elapsed=${meta.elapsedMs ?? 0}ms`,
      tags: ['llm-extraction', 'complete'],
    })
  }
}

export function resetExtractionLogDedup(): void {
  seenWorkflowEventIds.clear()
  seenProgressLogKeys.clear()
  lastSubstepStatus.clear()
}
